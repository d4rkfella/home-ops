import os
import time
import string
import random
import requests

from kubernetes import client as k8s_client, config as k8s_config
from kubernetes.client import V1DeleteOptions
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
OUTPUT_PATH = "/project/truenas.img"

IN_CLUSTER = "KUBERNETES_SERVICE_HOST" in os.environ

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
custom_api = k8s_client.CustomObjectsApi()

def random_token(length=16):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))

def wait_for_vmexport_ready(name, namespace, timeout=600):
    for _ in range(timeout // 5):
        vm_export = kv_api.read_namespaced_virtual_machine_export(name, namespace)
        conditions = getattr(vm_export.status, "conditions", [])
        for c in conditions:
            if c.type == "Ready" and c.status == "True":
                return vm_export
        time.sleep(5)
    raise TimeoutError("VMExport did not become ready in time")

def create_temp_secret(export_name, namespace):
    secret_name = f"{export_name}-secret"
    token_value = random_token()
    secret_body = k8s_client.V1Secret(
        metadata=k8s_client.V1ObjectMeta(name=secret_name, namespace=namespace),
        string_data={"token": token_value},
    )
    k8s_api.create_namespaced_secret(namespace=namespace, body=secret_body)
    print(f"Temporary Secret '{secret_name}' created")
    return token_value

def create_vmexport(pvc_name, export_name, namespace):
    spec = V1beta1VirtualMachineExportSpec(
        source={
            "apiGroup": "",
            "kind": "PersistentVolumeClaim",
            "name": pvc_name,
        },
        token_secret_ref=f"{export_name}-secret",
        ttl_duration="30m",
    )
    export = V1beta1VirtualMachineExport(
        api_version="export.kubevirt.io/v1beta1",
        kind="VirtualMachineExport",
        metadata=K8sIoApimachineryPkgApisMetaV1ObjectMeta(
            name=export_name, namespace=namespace
        ),
        spec=spec,
    )
    kv_api.create_namespaced_virtual_machine_export(namespace=namespace, body=export)
    print(f"VMExport '{export_name}' created, waiting to become Ready...")
    return wait_for_vmexport_ready(export_name, namespace)


def delete_temporary_resources(export_name, namespace):
    try:
        kv_api.delete_namespaced_virtual_machine_export(
            name=export_name,
            namespace=namespace,
            body=None,
        )
        print(f"VMExport '{export_name}' deleted")
    except Exception as e:
        print(f"Failed to delete VMExport '{export_name}': {e}")

    try:
        k8s_api.delete_namespaced_secret(f"{export_name}-secret", namespace)
        print(f"Secret '{export_name}-secret' deleted")
    except Exception as e:
        print(f"Failed to delete Secret: {e}")

def download_disk(url, token, output_path, chunk_size=10*1024*1024, retries=5):
    downloaded = 0
    if os.path.exists(output_path):
        downloaded = os.path.getsize(output_path)

    headers = {"x-kubevirt-export-token": token}
    if downloaded > 0:
        headers["Range"] = f"bytes={downloaded}-"

    for attempt in range(retries):
        try:
            with requests.get(url, headers=headers, stream=True, timeout=600) as resp:
                resp.raise_for_status()
                mode = "ab" if downloaded > 0 else "wb"
                with open(output_path, mode) as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
            print(f"Downloaded disk to {output_path}")
            return
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError) as e:
            print(f"Download interrupted, retry {attempt+1}/{retries}…")
            time.sleep(5)
            downloaded = os.path.getsize(output_path)
            headers["Range"] = f"bytes={downloaded}-"
    delete_temporary_resources(vm_export.metadata.name, vm_export.metadata.namespace)
    raise RuntimeError("Failed to download disk after multiple attempts")


token = create_temp_secret(EXPORT_NAME, NAMESPACE)
vm_export = create_vmexport(PVC_NAME, EXPORT_NAME, NAMESPACE)


if not IN_CLUSTER:
    external_url = vm_export.status.links.external.volumes[0].formats[0].url
else:
    external_url = vm_export.status.links.internal.volumes[0].formats[0].url

download_disk(external_url, token, OUTPUT_PATH)
delete_temporary_resources(vm_export.metadata.name, vm_export.metadata.namespace)
