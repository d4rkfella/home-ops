#!/usr/bin/env python3
import os
import sys
import asyncio
import aiohttp
import subprocess
from ruamel.yaml import YAML, YAMLError
from collections.abc import Callable
import hvac
from kubernetes_asyncio import client, config, dynamic, watch # type: ignore
from kubernetes_asyncio.dynamic import DynamicClient # type: ignore
from kubernetes_asyncio.client.exceptions import ApiException # type: ignore

yaml = YAML(typ="safe")
yaml.constructor.add_constructor('tag:yaml.org,2002:value', lambda loader, node: loader.construct_scalar(node))

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

async def apply_yaml_manifest(
    dyn,
    file_path: str,
    namespace: str = "default",
    *,
    decrypt: bool = False,
):
    if decrypt:
        if not os.environ.get("SOPS_AGE_KEY_FILE"):
            raise RuntimeError("SOPS_AGE_KEY_FILE not set; cannot decrypt")

        try:
            decrypted = subprocess.check_output(
                ["sops", "-d", file_path],
                env=os.environ,
                text=True,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"SOPS decryption failed: {e.stderr}") from e

        docs = yaml.load_all(decrypted)

    else:
        with open(file_path, "r", encoding="utf-8") as f:
            docs = yaml.load_all(f)

    for doc in docs:
        if not doc:
            continue

        if not isinstance(doc, dict):
            print(f"Skipping non-dict YAML doc: {type(doc)}")
            continue

        api = await dyn.resources.get(
            api_version=doc["apiVersion"],
            kind=doc["kind"],
        )

        meta = doc.setdefault("metadata", {})
        if "namespace" not in meta and namespace:
            meta["namespace"] = namespace

        name = meta["name"]

        await api.server_side_apply(
            body=doc,
            field_manager="flux-client-side-apply",
            name=name
        )

        print(f"Applied {doc['kind']} {name}")

async def wait_for_resources(
    dyn,
    kind: str,
    names: list[str],
    api_version: str,
    namespace: str | None,
    readiness_checker: Callable[[object], bool],
    timeout: int,
):
    """
    Generic async function to wait for Kubernetes resources.

    Parameters:
    - dyn: DynamicClient
    - kind: resource kind (Deployment, DaemonSet, StatefulSet, CustomResourceDefinition, etc.)
    - names: list of resource names to watch
    - api_version: e.g., 'apps/v1' or 'apiextensions.k8s.io/v1'
    - namespace: namespace if applicable (None for cluster-scoped resources)
    - readiness_checker: callable(obj) -> bool, determines if resource is ready
    - timeout: max wait in seconds
    """
    api = await dyn.resources.get(api_version=api_version, kind=kind)
    remaining = set(names)
    watcher = watch.Watch()

    async def _watch_loop():
        async for event in api.watch(namespace=namespace, watcher=watcher):
            obj = event['object']
            name = obj.metadata.name

            if name not in remaining:
                continue

            if readiness_checker(obj):
                print(f"{kind} {name} is ready")
                remaining.remove(name)
            else:
                print(f"Event {event['type']} for {kind} {name}: not ready yet")

            if not remaining:
                print(f"All {kind.lower()}s ready")
                break

    try:
        await asyncio.wait_for(_watch_loop(), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"Timeout waiting for {kind.lower()}s: {remaining}")
        sys.exit(1)
    except asyncio.CancelledError:
        print(f"{kind} watch cancelled by user")
        return
    finally:
        await watcher.close()

async def wait_for_crds(dyn, crd_names: list[str], timeout: int):
    await wait_for_resources(
        dyn=dyn,
        kind="CustomResourceDefinition",
        names=crd_names,
        api_version="apiextensions.k8s.io/v1",
        namespace=None,
        readiness_checker=lambda _: True,
        timeout=timeout,
    )

async def wait_for_deployments(dyn, namespace: str, deployment_names: list[str], timeout: int):
    await wait_for_resources(
        dyn=dyn,
        kind="Deployment",
        names=deployment_names,
        api_version="apps/v1",
        namespace=namespace,
        readiness_checker=lambda obj: (getattr(obj.status, "readyReplicas", 0) or 0) >= (getattr(obj.spec, "replicas", 0) or 0), # type: ignore
        timeout=timeout,
    )

async def wait_for_daemonsets(dyn, namespace: str, daemonset_names: list[str], timeout: int):
    await wait_for_resources(
        dyn=dyn,
        kind="DaemonSet",
        names=daemonset_names,
        api_version="apps/v1",
        namespace=namespace,
        readiness_checker=lambda obj: (getattr(obj.status, "numberReady", 0) or 0) >= (getattr(obj.status, "desiredNumberScheduled", 0) or 0), # type: ignore
        timeout=timeout,
    )

async def wait_for_statefulsets(dyn, namespace: str, statefulset_names: list[str], timeout: int):
    await wait_for_resources(
        dyn=dyn,
        kind="StatefulSet",
        names=statefulset_names,
        api_version="apps/v1",
        namespace=namespace,
        readiness_checker=lambda obj: (getattr(obj.status, "readyReplicas", 0) or 0) >= (getattr(obj.spec, "replicas", 0) or 0), # type: ignore
        timeout=timeout,
    )

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
    try:
        with open(crd_yaml_path) as f:
            data = yaml.load(f)
    except FileNotFoundError:
        print(f"Error: CRD list file not found at {crd_yaml_path}")
        return
    except YAMLError as e:
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

                for doc in yaml.load_all(yaml_text):
                    if not doc:
                        continue

                    if 'apiVersion' not in doc or 'kind' not in doc or 'metadata' not in doc or 'name' not in doc['metadata']:
                        print(f"Skipping malformed document (missing required fields) in {url}")
                        continue

                    api = await dyn.resources.get(api_version=doc['apiVersion'], kind=doc['kind'])

                    await api.server_side_apply(body=doc, field_manager="flux-client-side-apply", name=doc['metadata']['name'])

                    print(f"Applied {doc['kind']} {doc['metadata']['name']} from {url}")
                    docs_applied += 1

                if docs_applied == 0:
                    print(f"No documents applied from {url}")

            except ApiException as e:
                print(f"Failed to apply CRDs from {url}: Kubernetes API Error {e.status}")
                print(f"  Reason: {e.reason}")

            except YAMLError as e:
                print(f"YAML parsing error when applying CRDs from {url}: {e}")

            except Exception as e:
                print(f"Unexpected error while applying CRDs from {url}: {e}")


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

    wait_crd_parser = subparsers.add_parser("wait-crds", help="Watch and wait for the provided CRDs existance on the cluster")
    wait_crd_parser.add_argument("--names", nargs='+', help="CRD names (one or more, separated by spaces)")
    wait_crd_parser.add_argument("--timeout", default=120)

    dep_parser = subparsers.add_parser("wait-deployments", help="Watch and wait for the provided Deployments to become ready")
    dep_parser.add_argument("--namespace", required=True)
    dep_parser.add_argument("--names", nargs='+', help="Deployment names (one or more, separated by spaces)")
    dep_parser.add_argument("--timeout", default=240)

    ds_parser = subparsers.add_parser("wait-daemonsets", help="Watch and wait for the provided DaemonSets to become ready")
    ds_parser.add_argument("--namespace", required=True)
    ds_parser.add_argument("--names", nargs='+', help="DaemonSet names (one or more, separated by spaces)")
    ds_parser.add_argument("--timeout", default=240)

    ss_parser = subparsers.add_parser("wait-statefulsets", help="Watch and wait for the provided StatefulSets to become ready")
    ss_parser.add_argument("--namespace", required=True)
    ss_parser.add_argument("--names", nargs='+', help="StatefulSets names (one or more, separated by spaces)")
    ss_parser.add_argument("--timeout", default=240)

    vault_parser = subparsers.add_parser("init-vault", help="Init/unseal/restore a Vault cluster")
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
                await apply_yaml_manifest(dyn, args.file, args.namespace)
            elif args.command == "apply-sops-encrypted-manifest":
                await apply_yaml_manifest(dyn, args.file, args.namespace, decrypt=True)
            elif args.command == "apply-crds":
                await fetch_and_apply_crds(dyn, args.file)
            elif args.command == "wait-crds":
                await wait_for_crds(dyn, args.names, args.timeout)
            elif args.command == "wait-deployments":
                await wait_for_deployments(dyn, args.namespace, args.names, args.timeout)
            elif args.command == "wait-daemonsets":
                await wait_for_daemonsets(dyn, args.namespace, args.names, args.timeout)
            elif args.command == "wait-statefulsets":
                await wait_for_statefulsets(dyn, args.namespace, args.names, args.timeout)
            elif args.command == "init-vault":
                await vault_init_unseal_restore(args.addr, args.config)
            else:
                parser.print_help()

    asyncio.run(cli_run())
