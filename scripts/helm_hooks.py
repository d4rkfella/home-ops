#!/usr/bin/env python3
import asyncio
import os
import sys
import yaml
import sops
import json
import subprocess
from kubernetes_asyncio import client, config, dynamic, watch
from kubernetes_asyncio.client.exceptions import ApiException
import hvac

# -------------------------------
# Kubernetes helpers
# -------------------------------
async def load_k8s_client():
    await config.load_kube_config()
    return dynamic.DynamicClient(dynamic.ApiClient())

async def ensure_namespace(namespace: str):
    v1 = client.CoreV1Api()
    try:
        await v1.read_namespace(namespace)
        print(f"Namespace '{namespace}' already exists")
    except ApiException as e:
        if e.status == 404:
            ns_body = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
            await v1.create_namespace(ns_body)
            print(f"Created namespace '{namespace}'")
        else:
            raise

async def apply_manifest_file(dyn, file_path: str, namespace: str = None):
    with open(file_path) as f:
        for doc in yaml.safe_load_all(f):
            if not doc:
                continue
            api = dyn.resources.get(api_version=doc['apiVersion'], kind=doc['kind'])
            if 'namespace' not in doc['metadata'] and namespace:
                doc['metadata']['namespace'] = namespace
            await api.apply(body=doc, field_manager="kustomize-controller")
            print(f"Applied {doc['kind']} {doc['metadata']['name']}")

async def apply_sops_manifest(dyn: DynamicClient, file_path: str, namespace: str):
    with open(file_path, "r") as f:
        decrypted_str = sops.decrypt(f.read())

    for doc in yaml.safe_load_all(decrypted_str):
        if not doc:
            continue

        api = dyn.resources.get(api_version=doc['apiVersion'], kind=doc['kind'])
        if 'namespace' not in doc.get('metadata', {}):
            doc.setdefault('metadata', {})['namespace'] = namespace

        await api.apply(body=doc, field_manager="kustomize-controller")
        print(f"Applied {doc['kind']} {doc['metadata']['name']} (SOPS)")

async def wait_for_crds(dyn, crd_names):
    api = dyn.resources.get(api_version="apiextensions.k8s.io/v1", kind="CustomResourceDefinition")
    remaining = set(crd_names)
    w = watch.Watch()
    async for event in w.stream(api.get):
        name = event['object'].metadata.name
        if name in remaining:
            remaining.remove(name)
            print(f"CRD {name} ready")
        if not remaining:
            w.stop()
            break
    if remaining:
        raise TimeoutError(f"Timeout waiting for CRDs: {remaining}")

async def wait_for_deployments(dyn, namespace, deployments, timeout=600):
    api = dyn.resources.get(api_version="apps/v1", kind="Deployment")
    end_time = asyncio.get_event_loop().time() + timeout
    for name in deployments:
        while True:
            try:
                dep = await api.get(name=name, namespace=namespace)
                ready = dep.status.ready_replicas or 0
                desired = dep.spec.replicas or 0
                if ready >= desired:
                    print(f"Deployment {name} ready")
                    break
            except ApiException:
                pass
            if asyncio.get_event_loop().time() > end_time:
                raise TimeoutError(f"Deployment {name} in {namespace} did not become ready")
            await asyncio.sleep(5)

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
    with open(crd_yaml_path) as f:
        urls = [url for url in yaml.safe_load(f).get("crds", []) if url.startswith("https")]
    for url in urls:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                text = await resp.text()
                for doc in yaml.safe_load_all(text):
                    if doc:
                        api = dyn.resources.get(api_version=doc['apiVersion'], kind=doc['kind'])
                        await api.apply(body=doc, field_manager="kustomize-controller")
                        print(f"Applied CRD {doc['metadata']['name']} from {url}")

# -------------------------------
# Main entrypoint
# -------------------------------
async def main():
    release = os.environ.get("RELEASE_NAME")
    namespace = os.environ.get("RELEASE_NAMESPACE")
    dyn = await load_k8s_client()

    # Namespace creation (prepare hooks)
    if namespace:
        await ensure_namespace(namespace)

    # CRDs (prepare hooks)
    crd_yaml = os.environ.get("CRD_FILE")
    if crd_yaml:
        await fetch_and_apply_crds(dyn, crd_yaml)

    # Wait for CRDs (postsync hooks)
    crds_to_wait = os.environ.get("CRDS_TO_WAIT")
    if crds_to_wait:
        await wait_for_crds(dyn, crds_to_wait.split(","))

    # Apply manifests (postsync hooks)
    manifests = os.environ.get("MANIFESTS")
    if manifests:
        for m in manifests.split(","):
            await apply_manifest_file(dyn, m, namespace)

    # SOPS secrets (postsync hooks)
    sops_file = os.environ.get("SOPS_FILE")
    if sops_file:
        await apply_sops_manifest(dyn, sops_file, namespace)

    # Deployments/Daemonsets wait (postsync hooks)
    deployments = os.environ.get("DEPLOYMENTS")
    daemonsets = os.environ.get("DAEMONSETS")
    if deployments:
        await wait_for_deployments(dyn, namespace, deployments.split(","))
    if daemonsets:
        await wait_for_daemonsets(dyn, namespace, daemonsets.split(","))

    # Vault init/unseal/restore
    vault_addr = os.environ.get("VAULT_ADDR")
    vault_backup = os.environ.get("VAULT_BACKUP_FILE", "/project/.vault/vault-backup.yaml")
    if vault_addr:
        await vault_init_unseal_restore(vault_addr, vault_backup)

asyncio.run(main())

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

    # Wait for CRDs
    crd_parser = subparsers.add_parser("crds", help="Wait for CRDs")
    crd_parser.add_argument("--names", required=True, help="Comma-separated CRD names")

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
        dyn = await load_k8s_client()

        if args.command == "namespace":
            await ensure_namespace(args.name)
        elif args.command == "manifest":
            await apply_manifest_file(dyn, args.file, args.namespace)
        elif args.command == "sops":
            await apply_sops_manifest(dyn, args.file, args.namespace)
        elif args.command == "crds":
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
