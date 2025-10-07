#!/usr/bin/env python3
import asyncio
import os
import sys
import yaml
import sops
import json
import tempfile
import io
import aiohttp
import subprocess
from kubernetes_asyncio import client, config, dynamic, watch
from kubernetes_asyncio.dynamic import DynamicClient
from kubernetes_asyncio.utils import create_from_yaml, FailToCreateError
from kubernetes_asyncio.client.exceptions import ApiException
import hvac

# -------------------------------
# Kubernetes helpers
# -------------------------------
async def load_k8s_client():
    """Properly load Kubernetes dynamic client"""
    await config.load_kube_config()
    api_client = client.ApiClient()
    dyn = await DynamicClient(api_client)
    return dyn

async def ensure_namespace(dyn: dynamic.DynamicClient, namespace: str):
    """Ensure namespace exists using dynamic client"""
    api = await dyn.resources.get(api_version="v1", kind="Namespace")
    try:
        await api.get(name=namespace)
        print(f"Namespace '{namespace}' already exists")
    except ApiException as e:
        if e.status == 404:
            body = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}}
            await api.server_side_apply(body=body, field_manager="flux-client-side-apply", force_conflicts=True)
            print(f"Created namespace '{namespace}'")
        else:
            raise

async def apply_manifest_file(dyn, file_path: str, namespace: str = None):
    with open(file_path) as f:
        for doc in yaml.safe_load_all(f):
            if not doc:
                continue
            api = await dyn.resources.get(api_version=doc['apiVersion'], kind=doc['kind'])
            if 'namespace' not in doc['metadata'] and namespace:
                doc['metadata']['namespace'] = namespace
            await api.apply(body=doc, field_manager="kustomize-controller")
            print(f"Applied {doc['kind']} {doc['metadata']['name']}")

async def apply_sops_manifest(dyn: DynamicClient, file_path: str, namespace: str):
    import subprocess # Required for calling the sops CLI binary
    import os         # Required for accessing environment variables

    age_key_file = os.environ.get("SOPS_AGE_KEY_FILE")
    if not age_key_file:
        print("Fatal Error: SOPS_AGE_KEY_FILE environment variable is not set. Cannot decrypt.")
        # Added instructional context on where to check the environment for SOPS
        print("Please ensure the 'SOPS_AGE_KEY_FILE' is exported in your shell (e.g., via 'envcr').")
        return

    # 1. Execute the sops command to decrypt the file path
    try:
        # FIX: Reverting the command to use the shorthand flag '-d' to perfectly match the
        # user's known working shell command ('sops -d <file>').
        # The 'env=os.environ' remains to inherit SOPS_AGE_KEY_FILE correctly.
        decrypted_str = subprocess.check_output(
            ['sops', '-d', file_path],  # Using '-d' shorthand
            env=os.environ,                 # CRITICAL: Pass the shell's environment
            universal_newlines=True,        # Decodes output to string (YAML text)
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print("Fatal Error: The 'sops' CLI binary is not installed or available in PATH. Cannot proceed.")
        return
    except subprocess.CalledProcessError as e:
        # SOPS CLI failed to decrypt (e.g., bad key, bad file format)
        print(f"Error decrypting SOPS file '{file_path}' (SOPS CLI Failed). Output:")
        # Print only the stderr output from the SOPS CLI for clear debugging
        print(e.stderr.strip())
        print(f"Attempted to use key file path from SOPS_AGE_KEY_FILE: {age_key_file}")
        return # Stop execution if decryption fails
    except Exception as e:
        print(f"An unexpected error occurred during SOPS decryption: {e}")
        return

    for doc in yaml.safe_load_all(decrypted_str):
        if not doc:
            continue

        # Ensures that 'doc' is actually a dictionary before attempting to access its keys.
        if not isinstance(doc, dict):
            # This check is still necessary to skip non-document content in the YAML stream
            print(f"Skipping non-dictionary document from SOPS file: {type(doc)}")
            continue

        api = await dyn.resources.get(api_version=doc['apiVersion'], kind=doc['kind'])
        if 'namespace' not in doc.get('metadata', {}):
            doc.setdefault('metadata', {})['namespace'] = namespace

        name = doc['metadata']['name']
        # The field manager for SOPS-applied manifests is typically 'kustomize-controller'
        # or a specific flux manager. Using 'kustomize-controller' for consistency.
        await api.server_side_apply(body=doc, field_manager="kustomize-controller", name=name)
        print(f"Applied {doc['kind']} {doc['metadata']['name']} (SOPS)")


async def wait_for_crds(dyn, crd_names, timeout: int = 600):
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
                raise TimeoutError(f"Timeout waiting for deployments: {remaining}")
    finally:
        await watcher.close()

async def wait_for_deployments(dyn, namespace: str, deployments: list[str], timeout: int = 600):
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


async def wait_for_daemonsets(dyn, namespace, daemonsets, timeout=600):
    api = dyn.resources.get(api_version="apps/v1", kind="DaemonSet")
    end_time = asyncio.get_event_loop().time() + timeout
    for name in daemonsets:
        while True:
            try:
                ds = await api.get(name=name, namespace=namespace)
                ready = ds.status.number_ready or 0
                desired = ds.status.desired_number_scheduled or 0
                if ready >= desired:
                    print(f"DaemonSet {name} ready")
                    break
            except ApiException:
                pass
            if asyncio.get_event_loop().time() > end_time:
                raise TimeoutError(f"DaemonSet {name} in {namespace} did not become ready")
            await asyncio.sleep(5)

# -------------------------------
# Vault helpers
# -------------------------------
async def vault_init_unseal_restore(vault_addr, backup_file="/project/.vault/vault-backup.yaml"):
    client_vault = hvac.Client(url=vault_addr)
    token_file = "/tmp/vault-keys.json"

    # Initialize
    if not client_vault.sys.is_initialized():
        init_result = client_vault.sys.initialize()
        with open(token_file, "w") as f:
            json.dump(init_result, f)
        print("Vault initialized")
    else:
        print("Vault already initialized")

    # Unseal
    with open(token_file) as f:
        keys = json.load(f)['keys']
    if client_vault.sys.is_sealed():
        print("Submitting first unseal key with reset")
        client_vault.sys.submit_unseal_key(key=keys[0], reset=True)
        
        for key in keys[1:]:
            if client_vault.sys.is_sealed():
                client_vault.sys.submit_unseal_key(key=key)
    
    print("Vault unsealed")

    # Restore
    #with open(token_file) as f:
        #root_token = json.load(f)['root_token']
    #client_vault.token = root_token
    # Placeholder for vault-backup restore logic
    #print(f"Restoring Vault backup from {backup_file} (implement your custom logic here)")

# -------------------------------
# CRD fetching
# -------------------------------
async def fetch_and_apply_crds(dyn, crd_yaml_path):
    # Register the custom constructor to handle the specific PyYAML bug in Prometheus CRDs.
    register_yaml_value_constructor()

    # 1. Read the list of URLs from your YAML file (just URLs starting with https)
    try:
        # Use the passed argument path instead of hardcoded path
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

    # 2. Create one aiohttp session for all fetches
    async with aiohttp.ClientSession() as session:
        for url in urls:
            print(f"Fetching CRDs from {url}")
            yaml_text = None

            # --- FETCHING ---
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        print(f"Failed to fetch {url}: HTTP {resp.status}")
                        continue
                    yaml_text = await resp.text()
            except Exception as e:
                print(f"Failed to fetch {url} (network error): {e}")
                continue

            # --- APPLICATION ---
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
    """Registers a constructor for the problematic implicit YAML tag."""
    def yaml_constructor_value(loader, node):
        # Instruct the loader to construct this node as a simple scalar (string)
        return loader.construct_scalar(node)

    # Use UnsafeLoader since we rely on it for complex CRDs anyway, and register the fix there.
    # Check if the constructor is already registered before adding it.
    if 'tag:yaml.org,2002:value' not in yaml.UnsafeLoader.yaml_constructors:
        yaml.UnsafeLoader.add_constructor('tag:yaml.org,2002:value', yaml_constructor_value)
# -------------------------------
# CLI dispatcher for testing individual functions
# -------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kubernetes hook executor")
    subparsers = parser.add_subparsers(dest="command")

    # Namespace
    ns_parser = subparsers.add_parser("namespace", help="Ensure namespace exists")
    ns_parser.add_argument("--name", required=True, help="Namespace to create/check")

    # Apply manifest
    mf_parser = subparsers.add_parser("manifest", help="Apply manifest file")
    mf_parser.add_argument("--file", required=True, help="YAML manifest file")
    mf_parser.add_argument("--namespace", help="Namespace override")

    # Apply SOPS
    sops_parser = subparsers.add_parser("sops", help="Apply SOPS manifest")
    sops_parser.add_argument("--file", required=True, help="SOPS YAML file")
    sops_parser.add_argument("--namespace", required=True, help="Namespace to apply in")

    # Fetch & apply CRDs
    fetch_crd_parser = subparsers.add_parser("crds-apply", help="Fetch and apply CRDs from YAML")
    fetch_crd_parser.add_argument("--file", required=True, help="YAML file listing CRD URLs")

    # Wait for CRDs
    wait_crd_parser = subparsers.add_parser("crds-wait", help="Wait for CRDs to be established")
    wait_crd_parser.add_argument("--names", required=True, help="Comma-separated CRD names to wait for")

    # Deployments
    dep_parser = subparsers.add_parser("deployments", help="Wait for deployments")
    dep_parser.add_argument("--namespace", required=True)
    dep_parser.add_argument("--names", required=True, help="Comma-separated deployment names")

    # Daemonsets
    ds_parser = subparsers.add_parser("daemonsets", help="Wait for daemonsets")
    ds_parser.add_argument("--namespace", required=True)
    ds_parser.add_argument("--names", required=True, help="Comma-separated daemonset names")

    # Vault
    vault_parser = subparsers.add_parser("vault", help="Init/unseal/restore Vault")
    vault_parser.add_argument("--addr", required=True, help="Vault address")
    vault_parser.add_argument("--backup", default="/project/.vault/vault-backup.yaml", help="Vault backup file")

    args = parser.parse_args()

    async def cli_run():
        await config.load_kube_config()

        async with client.ApiClient() as api_client:
            dyn = await DynamicClient(api_client)
            if args.command == "namespace":
                await ensure_namespace(dyn, args.name)
            elif args.command == "manifest":
                await apply_manifest_file(dyn, args.file, args.namespace)
            elif args.command == "sops":
                await apply_sops_manifest(dyn, args.file, args.namespace)
            elif args.command == "crds-apply":
                await fetch_and_apply_crds(dyn, args.file)
            elif args.command == "crds-wait":
                await wait_for_crds(dyn, args.names.split(","))
            elif args.command == "deployments":
                await wait_for_deployments(dyn, args.namespace, args.names.split(","))
            elif args.command == "daemonsets":
                await wait_for_daemonsets(dyn, args.namespace, args.names.split(","))
            elif args.command == "vault":
                await vault_init_unseal_restore(args.addr, args.backup)
            else:
                parser.print_help()

    asyncio.run(cli_run())
