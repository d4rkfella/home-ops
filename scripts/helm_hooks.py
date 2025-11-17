#!/usr/bin/env python3
import asyncio
import aiohttp
import yaml
from kubernetes_asyncio import client, config, dynamic, watch # type: ignore
from kubernetes_asyncio.dynamic import DynamicClient # type: ignore
from kubernetes_asyncio.client.exceptions import ApiException # type: ignore
import hvac


async def load_k8s_client():
    await config.load_kube_config()
    api_client = client.ApiClient()
    dyn = await DynamicClient(api_client)
    return dyn

async def ensure_namespace(dyn: dynamic.DynamicClient, namespace: str):
    api = await dyn.resources.get(api_version="v1", kind="Namespace")
    try:
        await api.get(name=namespace)
        print(f"Namespace '{namespace}' already exists")
    except ApiException as e:
        if e.status == 404:
            body = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}}
            await api.server_side_apply(body=body, field_manager="flux-client-side-apply")
            print(f"Created namespace '{namespace}'")
        else:
            raise

async def apply_manifest_file(dyn, file_path: str, namespace: str):
    with open(file_path) as f:
        for doc in yaml.safe_load_all(f):
            if not doc:
                continue
            api = await dyn.resources.get(api_version=doc['apiVersion'], kind=doc['kind'])
            if 'namespace' not in doc['metadata'] and namespace:
                doc['metadata']['namespace'] = namespace
            await api.apply(body=doc, field_manager="flux-client-side-apply")
            print(f"Applied {doc['kind']} {doc['metadata']['name']}")

async def apply_sops_manifest(dyn: DynamicClient, file_path: str, namespace: str):
    import subprocess
    import os

    age_key_file = os.environ.get("SOPS_AGE_KEY_FILE")
    if not age_key_file:
        print("Fatal Error: SOPS_AGE_KEY_FILE environment variable is not set. Cannot decrypt.")
        print("Please ensure the 'SOPS_AGE_KEY_FILE' is exported in your shell (e.g., via 'envcr').")
        return

    try:
        decrypted_str = subprocess.check_output(
            ['sops', '-d', file_path],
            env=os.environ,
            universal_newlines=True,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print("Fatal Error: The 'sops' CLI binary is not installed or available in PATH. Cannot proceed.")
        return
    except subprocess.CalledProcessError as e:
        print(f"Error decrypting SOPS file '{file_path}' (SOPS CLI Failed). Output:")
        print(e.stderr.strip())
        return
    except Exception as e:
        print(f"An unexpected error occurred during SOPS decryption: {e}")
        return

    for doc in yaml.safe_load_all(decrypted_str):
        if not doc:
            continue

        if not isinstance(doc, dict):
            print(f"Skipping non-dictionary document from SOPS file: {type(doc)}")
            continue

        api = await dyn.resources.get(api_version=doc['apiVersion'], kind=doc['kind'])
        if 'namespace' not in doc.get('metadata', {}):
            doc.setdefault('metadata', {})['namespace'] = namespace

        name = doc['metadata']['name']
        await api.server_side_apply(body=doc, field_manager="flux-client-side-apply", name=name)
        print(f"Applied {doc['kind']} {doc['metadata']['name']} (SOPS)")


async def wait_for_crds(dyn, crd_names, timeout: int = 60):
    api = await dyn.resources.get(api_version="apiextensions.k8s.io/v1", kind="CustomResourceDefinition")
    remaining = set(crd_names)
    watcher = watch.Watch()
    end_time = asyncio.get_event_loop().time() + timeout
    try:
        async for event in api.watch(watcher=watcher):
            name = event['object'].metadata.name
            if name in remaining:
                remaining.remove(name)
                print(f"CRD {name} exists")
            if not remaining:
                break
            if asyncio.get_event_loop().time() > end_time:
                raise TimeoutError(f"Timeout checking for the existence of provided CRDs: {remaining}")
    finally:
        await watcher.close()

async def wait_for_deployments(dyn, namespace: str, deployments: list[str], timeout: int = 120):
    api = await dyn.resources.get(api_version="apps/v1", kind="Deployment")
    remaining = set(deployments)
    end_time = asyncio.get_event_loop().time() + timeout

    watcher = watch.Watch()
    try:
        async for event in api.watch(namespace=namespace, watcher=watcher):
            obj = event["object"]
            dep_name = obj.metadata.name
            if dep_name not in remaining:
                continue

            spec = obj.spec or {}
            status = obj.status or {}

            desired = getattr(spec, "replicas", 0) or 0
            ready = getattr(status, "readyReplicas", 0) or 0

            if desired == 0:
                print(f"Deployment {dep_name} has 0 desired replicas, not ready")
            elif ready >= desired:
                print(f"Deployment {dep_name} became ready ({ready}/{desired})")
                remaining.remove(dep_name)
            else:
                print(f"Event {event['type']} {dep_name}: {ready}/{desired} ready")

            if not remaining:
                print("All deployments ready")
                break

            if asyncio.get_event_loop().time() > end_time:
                raise TimeoutError(f"Timeout waiting for deployments: {remaining}")
    finally:
        await watcher.close()


async def wait_for_daemonsets(dyn, namespace: str, daemonsets: list[str], timeout: int = 120):
    api = await dyn.resources.get(api_version="apps/v1", kind="DaemonSet")
    remaining = set(daemonsets)
    end_time = asyncio.get_event_loop().time() + timeout

    watcher = watch.Watch()
    try:
        async for event in api.watch(namespace=namespace, watcher=watcher):
            obj = event["object"]
            dep_name = obj.metadata.name
            if dep_name not in remaining:
                continue

            desired = obj.status.desiredNumberScheduled or 0
            ready = obj.status.numberReady or 0

            if desired == 0:
                print(f"DaemonSet {dep_name} has 0 desired replicas, not ready")
            elif ready >= desired:
                print(f"DaemonSet {dep_name} is ready ({ready}/{desired})")
                remaining.remove(dep_name)
            else:
                print(f"Event {event['type']} {dep_name}: {ready}/{desired} ready")

            if not remaining:
                print("All daemonsets ready")
                break

            if asyncio.get_event_loop().time() > end_time:
                raise TimeoutError(f"Timeout waiting for daemonsets: {remaining}")
    finally:
        await watcher.close()


async def vault_init_unseal_restore(vault_addr: str, config_file: str):
    client = hvac.Client(url=vault_addr)

    if not client.sys.is_initialized():
        print("Vault not initialized. Initializing now...")
        try:
            result = client.sys.initialize()
            root_token = result['root_token']
            keys = result['keys']
        except Exception as e:
            print(f"Vault initialization failed: {e}")
            return
    else:
        print("Vault already initialized. Skipping unseal and restore operations...")
        return

    if client.sys.is_sealed():
        try:
            print("Vault is sealed. Attempting unseal...")
            client.sys.submit_unseal_keys(keys)
        except Exception as e:
            print(f"Vault unseal failed: {e}")
            return
    else:
        print("Vault already unsealed. Skipping restore procedure...")
        return

    try:
        command = [
            "vault-backup",
            "restore",
            "--force",
            f"--config={config_file}",
            f"--vault-token={root_token}",
            f"--vault-address={vault_addr}"
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(f"Vault restore FAILED (Exit Code {process.returncode}):")
            print("STDOUT:\n", stdout.decode().strip())
            print("STDERR:\n", stderr.decode().strip())
            raise RuntimeError(f"Vault restore failed with exit code {process.returncode}")
        else:
            print("Vault restore completed successfully.")
            print("STDOUT:\n", stdout.decode().strip())

    except FileNotFoundError:
        print("Vault restore FAILED: 'vault-backup' command not found. Ensure it's in the PATH.")
    except Exception as e:
        print(f"An unexpected error occurred during vault restore: {e}")



async def fetch_and_apply_crds(dyn, crd_yaml_path):
    register_yaml_value_constructor()

    try:
        with open(crd_yaml_path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: CRD list file not found at {crd_yaml_path}")
        return
    except yaml.YAMLError as e:
        print(f"Error: Could not parse CRD list file at {crd_yaml_path}: {e}")
        return

    urls = data.get("crds", [])
    if not urls:
        print(f"No CRD URLs found in {crd_yaml_path}")
        return
    else:
        print(urls)

    async with aiohttp.ClientSession() as session:
        for url in urls:
            print(f"Fetching CRDs from {url}")
            yaml_text = None

            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        print(f"Failed to fetch {url}: HTTP {resp.status}")
                        continue
                    yaml_text = await resp.text()
            except Exception as e:
                print(f"Failed to fetch {url} (network error): {e}")
                continue

            try:
                docs_applied = 0

                for doc in yaml.load_all(yaml_text, Loader=yaml.UnsafeLoader):
                    if not doc:
                        continue

                    if 'apiVersion' not in doc or 'kind' not in doc or 'metadata' not in doc or 'name' not in doc['metadata']:
                        print(f"Skipping malformed document (missing required fields) in {url}")
                        continue

                    api = await dyn.resources.get(api_version=doc['apiVersion'], kind=doc['kind'])

                    await api.server_side_apply(body=doc, field_manager="flux-client-side-apply", name=doc['metadata']['name'], force_conflicts=True)

                    print(f"Applied {doc['kind']} {doc['metadata']['name']} from {url}")
                    docs_applied += 1

                if docs_applied == 0:
                    print(f"No documents applied from {url}")

            except ApiException as e:
                print(f"Failed to apply CRDs from {url}: Kubernetes API Error {e.status}")
                print(f"  Reason: {e.reason}")

            except yaml.YAMLError as e:
                print(f"YAML parsing error when applying CRDs from {url}: {e}")

            except Exception as e:
                print(f"Unexpected error while applying CRDs from {url}: {e}")

def register_yaml_value_constructor():
    def yaml_constructor_value(loader, node):
        return loader.construct_scalar(node)

    if 'tag:yaml.org,2002:value' not in yaml.UnsafeLoader.yaml_constructors:
        yaml.UnsafeLoader.add_constructor('tag:yaml.org,2002:value', yaml_constructor_value)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kubernetes hook executor")
    subparsers = parser.add_subparsers(dest="command")

    ns_parser = subparsers.add_parser("ensure-namespace", help="Ensure namespace exists")
    ns_parser.add_argument("--name", required=True, help="Namespace to create/check")

    mf_parser = subparsers.add_parser("apply-manifest", help="Apply manifest file")
    mf_parser.add_argument("--file", required=True, help="YAML manifest file")
    mf_parser.add_argument("--namespace", help="Namespace override")

    sops_parser = subparsers.add_parser("apply-sops-encrypted-manifest", help="Apply SOPS encrypted manifest")
    sops_parser.add_argument("--file", required=True, help="SOPS YAML file")
    sops_parser.add_argument("--namespace", required=True, help="Namespace to apply in")

    fetch_crd_parser = subparsers.add_parser("apply-crds", help="Fetch and apply CRDs from YAML")
    fetch_crd_parser.add_argument("--file", required=True, help="YAML file listing CRD URLs")

    wait_crd_parser = subparsers.add_parser("wait-crds", help="Wait for CRDs to be established")
    wait_crd_parser.add_argument("--names", required=True, help="Comma-separated CRD names to wait for")

    dep_parser = subparsers.add_parser("wait-deployments", help="Wait for deployments")
    dep_parser.add_argument("--namespace", required=True)
    dep_parser.add_argument("--names", required=True, help="Comma-separated deployment names")

    ds_parser = subparsers.add_parser("wait-daemonsets", help="Wait for daemonsets")
    ds_parser.add_argument("--namespace", required=True)
    ds_parser.add_argument("--names", required=True, help="Comma-separated daemonset names")

    vault_parser = subparsers.add_parser("init-vault", help="Init/unseal/restore Vault")
    vault_parser.add_argument("--addr", required=True, help="Vault address")
    vault_parser.add_argument("--config", default="/project/.vault/vault-backup.yaml", help="vault-backup cli config file")

    args = parser.parse_args()

    async def cli_run():
        await config.load_kube_config()

        async with client.ApiClient() as api_client:
            dyn = await DynamicClient(api_client)
            if args.command == "ensure-namespace":
                await ensure_namespace(dyn, args.name)
            elif args.command == "apply-manifest":
                await apply_manifest_file(dyn, args.file, args.namespace)
            elif args.command == "apply-sops-encrypted-manifest":
                await apply_sops_manifest(dyn, args.file, args.namespace)
            elif args.command == "apply-crds":
                await fetch_and_apply_crds(dyn, args.file)
            elif args.command == "wait-crds":
                await wait_for_crds(dyn, args.names.split(","))
            elif args.command == "wait-deployments":
                await wait_for_deployments(dyn, args.namespace, args.names.split(","))
            elif args.command == "wait-daemonsets":
                await wait_for_daemonsets(dyn, args.namespace, args.names.split(","))
            elif args.command == "init-vault":
                await vault_init_unseal_restore(args.addr, args.config)
            else:
                parser.print_help()

    asyncio.run(cli_run())
