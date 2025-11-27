import os
import time
import string
import random
import requests
import guestfs

from kubernetes_asyncio import client as k8s_client, config as k8s_config
from kubevirt import ApiClient, DefaultApi
from kubevirt.configuration import Configuration
from kubevirt.models import (
    V1beta1VirtualMachineExport,
    V1beta1VirtualMachineExportSpec,
    K8sIoApimachineryPkgApisMetaV1ObjectMeta,
)

NAMESPACE = "virtualization"
PVC_NAME = "truenas-os-disk"
EXPORT_NAME = "truenas-export"

# Paths
DOWNLOAD_PATH = "/project/truenas.img"       # Intermediate RAW file
FINAL_OUTPUT_PATH = "/project/truenas.qcow2" # Final QCOW2 file

IN_CLUSTER = "KUBERNETES_SERVICE_HOST" in os.environ

# --- K8s Setup (Unchanged) ---
k8s_config.load_kube_config()
k8s_api = k8s_client.CoreV1Api()
k8s_conf_obj = k8s_client.Configuration.get_default_copy()
kv_conf = Configuration()
kv_conf.host = k8s_conf_obj.host
kv_conf.verify_ssl = k8s_conf_obj.verify_ssl
kv_conf.ssl_ca_cert = k8s_conf_obj.ssl_ca_cert
kv_conf.cert_file = k8s_conf_obj.cert_file
kv_conf.key_file = k8s_conf_obj.key_file
kv_client = ApiClient(configuration=kv_conf)
kv_api = DefaultApi(kv_client)

def random_token(length=16):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))

async def wait_for_vmexport_ready(name, namespace, timeout=600):
    for _ in range(timeout // 5):
        vm_export = await kv_api.read_namespaced_virtual_machine_export(name, namespace)
        conditions = getattr(vm_export.status, "conditions", [])
        for c in conditions:
            if c.type == "Ready" and c.status == "True":
                return vm_export
        time.sleep(5)
    raise TimeoutError("VMExport did not become ready in time")

async def create_temp_secret(export_name, namespace):
    secret_name = f"{export_name}-secret"
    token_value = random_token()
    secret_body = k8s_client.V1Secret(
        metadata=k8s_client.V1ObjectMeta(name=secret_name, namespace=namespace),
        string_data={"token": token_value},
    )
    await k8s_api.create_namespaced_secret(namespace=namespace, body=secret_body)
    return token_value

def create_vmexport(pvc_name, export_name, namespace):
    spec = V1beta1VirtualMachineExportSpec(
        source={"apiGroup": "", "kind": "PersistentVolumeClaim", "name": pvc_name},
        token_secret_ref=f"{export_name}-secret",
        ttl_duration="30m",
    )
    export = V1beta1VirtualMachineExport(
        api_version="export.kubevirt.io/v1beta1",
        kind="VirtualMachineExport",
        metadata=K8sIoApimachineryPkgApisMetaV1ObjectMeta(name=export_name, namespace=namespace),
        spec=spec,
    )
    try:
        kv_api.create_namespaced_virtual_machine_export(namespace=namespace, body=export)
    except Exception:
        pass
    return wait_for_vmexport_ready(export_name, namespace)

def delete_temporary_resources(export_name, namespace):
    try:
        kv_api.delete_namespaced_virtual_machine_export(name=export_name, namespace=namespace, body=None)
    except Exception: pass
    try:
        k8s_api.delete_namespaced_secret(f"{export_name}-secret", namespace)
    except Exception: pass

def download_disk(url, token, output_path, chunk_size=10*1024*1024):
    print(f"Downloading disk to {output_path}...")
    headers = {"x-kubevirt-export-token": token}
    mode = "wb"
    if os.path.exists(output_path):
        downloaded = os.path.getsize(output_path)
        if downloaded > 0:
            headers["Range"] = f"bytes={downloaded}-"
            mode = "ab"

    with requests.get(url, headers=headers, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        with open(output_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
    print("Download complete.")

# ---------------------------------------------------------
# PURE GUESTFS BINDINGS IMPLEMENTATION
# ---------------------------------------------------------

def process_disk_image(raw_input_path, qcow_output_path):
    """
    1. Sparsifies the RAW image in-place (fstrim).
    2. Converts to QCOW2 by creating a new disk and copying data (sparse copy).
    """

    # --- STEP 1: Sparsify (In-Place) ---
    print(f"Phase 1: Analyzing and Sparsifying {raw_input_path}...")

    g = guestfs.GuestFS(python_return_dict=True)

    # Enable read-write to allow fstrim to modify the disk
    g.add_drive_opts(raw_input_path, format="raw", readonly=0)
    g.launch()

    # Inspect OS (Logic from Example 2 in man page)
    roots = g.inspect_os()
    if not roots:
        print("Warning: No OS found. Skipping filesystem trim.")
    else:
        for root in roots:
            mps = g.inspect_get_mountpoints(root)
            # Sort by length (shortest first) to mount parents before children
            for device, mp in sorted(mps.items(), key=lambda k: len(k[0])):
                try:
                    g.mount(mp, device)
                except Exception as e:
                    print(f"Warning: Failed to mount {device}: {e}")

            # Run fstrim on all mountpoints
            # This punches holes in the RAW file where the filesystem sees empty space
            print("Running fstrim to zero out unused blocks...")
            try:
                g.fstrim("/")
            except Exception as e:
                print(f"fstrim failed: {e}")

            g.umount_all()

    g.shutdown()
    g.close()
    print("Sparsification complete.")

    # --- STEP 2: Convert to QCOW2 (Copying) ---
    print(f"Phase 2: Converting {raw_input_path} -> {qcow_output_path}...")

    # Get the size of the original raw disk
    virtual_size = os.path.getsize(raw_input_path)

    g_conv = guestfs.GuestFS(python_return_dict=True)

    # 1. Create the target QCOW2 container (Example 1 in man page)
    # This creates an empty qcow2 file with the correct size
    g_conv.disk_create(qcow_output_path, "qcow2", virtual_size)

    # 2. Add Source (Read-Only)
    g_conv.add_drive_opts(raw_input_path, format="raw", readonly=1)

    # 3. Add Destination (Read-Write)
    g_conv.add_drive_opts(qcow_output_path, format="qcow2", readonly=0)

    g_conv.launch()

    # Get device names. Usually /dev/sda is source, /dev/sdb is dest
    devices = g_conv.list_devices()
    src_dev = devices[0] # /dev/sda
    dst_dev = devices[1] # /dev/sdb

    print(f"Copying sparse data from {src_dev} to {dst_dev}...")

    # copy_device_to_device(src, dest, sparse=True)
    # This efficiently copies the data. Since we ran fstrim in Step 1,
    # the zeros are actual holes, and this function preserves them.
    g_conv.copy_device_to_device(src_dev, dst_dev, sparse=True)

    g_conv.shutdown()
    g_conv.close()

    print(f"Conversion complete: {qcow_output_path}")

# ---------------------------------------------------------

try:
    # 1. Setup Export
    token = await create_temp_secret(EXPORT_NAME, NAMESPACE)
    vm_export = create_vmexport(PVC_NAME, EXPORT_NAME, NAMESPACE)

    # 2. Get Link
    if not IN_CLUSTER:
        external_url = vm_export.status.links.external.volumes[0].formats[0].url
    else:
        external_url = vm_export.status.links.internal.volumes[0].formats[0].url

    # 3. Download Raw
    download_disk(external_url, token, DOWNLOAD_PATH)

    # 4. Sparsify & Convert using GuestFS Bindings
    process_disk_image(DOWNLOAD_PATH, FINAL_OUTPUT_PATH)

    # 5. Cleanup Raw File
    if os.path.exists(FINAL_OUTPUT_PATH):
        os.remove(DOWNLOAD_PATH)

finally:
    if 'vm_export' in locals():
        delete_temporary_resources(vm_export.metadata.name, vm_export.metadata.namespace)
