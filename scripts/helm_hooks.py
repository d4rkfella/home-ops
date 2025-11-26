#!/usr/bin/env python3

import asyncio
import os
import random
import subprocess
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path
from collections.abc import Callable

import aiohttp
import hvac
import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from ruamel.yaml import YAML, YAMLError
from typing_extensions import Annotated

from kubernetes_asyncio import client, config, dynamic, watch  # type: ignore
from kubernetes_asyncio.client.exceptions import ApiException  # type: ignore
from kubernetes_asyncio.dynamic import DynamicClient  # type: ignore
from kubernetes_asyncio.dynamic.exceptions import ResourceNotFoundError  # type: ignore


yaml = YAML(typ="safe")
yaml.constructor.add_constructor(
    "tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node)
)

app = typer.Typer(name="home-ops-cli")


@asynccontextmanager
async def k8s_client():
    await config.load_kube_config()
    async with client.ApiClient() as api_client:
        dyn = await DynamicClient(api_client)
        yield dyn


def async_command(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))

    return wrapper


class RetryLimitExceeded(Exception):
    def __init__(self, last_exception: Exception, retries: int):
        self.last_exception = last_exception
        self.retries = retries
        super().__init__(f"Function failed after {retries} retries: {last_exception!r}")


async def retry_with_backoff(
    fn, *args, retries=5, base_delay=2, console=None, **kwargs
):
    attempt = 0
    while True:
        try:
            return await fn(*args, **kwargs)

        except (ConnectionError, OSError) as e:
            if attempt >= retries:
                raise RetryLimitExceeded(e, retries)

            delay = base_delay * (2**attempt) + random.uniform(0, 0.3)
            attempt += 1

            msg = f"retrying in {delay:.1f}s... ({attempt}/{retries})"

            if console:
                console.print(f"[bold red]{e}[/bold red]")
                console.print(f"[yellow]{msg}[/yellow]")
            else:
                print(f"{e}")
                print(msg)

            await asyncio.sleep(delay)


def load_manifest(file: Path, decrypt: bool = False) -> list[dict]:
    if decrypt:
        sops_cmd = ["sops", "-d", str(file)]
        try:
            decrypted = subprocess.check_output(
                sops_cmd,
                env=os.environ,
                text=True,
                stderr=subprocess.PIPE,
            )
            docs = yaml.load_all(decrypted)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"SOPS decryption failed: {e.stderr}") from e
    else:
        with open(file, "r", encoding="utf-8") as f:
            docs = list(yaml.load_all(f))
    return docs


async def ensure_namespace(dyn: dynamic.DynamicClient, namespace: str):
    api = await dyn.resources.get(api_version="v1", kind="Namespace")
    try:
        await api.get(name=namespace)
        print(f"Namespace '{namespace}' already exists")
    except ApiException as e:
        if e.status == 404:
            body = {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": namespace},
            }
            await api.server_side_apply(
                body=body, field_manager="flux-client-side-apply"
            )
            print(f"Created namespace '{namespace}'")
        else:
            raise


async def apply_manifests(dyn: DynamicClient, docs: list[dict], namespace: str) -> None:
    total_docs = len(docs)

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        transient=False,
    ) as main_progress:

        overall_task = main_progress.add_task(
            "Processing manifests...", total=total_docs
        )

        for index, doc in enumerate(docs, start=1):
            if not isinstance(doc, dict):
                main_progress.console.print(
                    f"[yellow]Skipping non-dict YAML doc: {type(doc)}[/yellow]"
                )
                main_progress.update(overall_task, advance=1)
                continue

            with Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                transient=False,
            ) as doc_progress:
                doc_task = doc_progress.add_task(
                    f"Applying {doc.get('kind', '<unknown>')} {doc.get('metadata', {}).get('name', '<unknown>')}...",
                    total=None,
                )

                try:
                    api = await dyn.resources.get(
                        api_version=doc["apiVersion"],
                        kind=doc["kind"],
                    )

                    await retry_with_backoff(
                        api.server_side_apply,
                        namespace=namespace,
                        body=doc,
                        field_manager="flux-client-side-apply",
                        console=doc_progress.console,
                    )

                    name = doc["metadata"]["name"]
                    doc_progress.update(
                        doc_task,
                        description=f"[green]✔ Applied {doc['kind']} {name}[/green]",
                    )

                except ApiException as e:
                    doc_progress.console.print(
                        f"[bold red]❌ Failed to apply {doc.get('kind', 'Resource')}: API Error {e.status}[/bold red]"
                    )
                    doc_progress.console.print(f"  [red]Reason:[/red] {e.reason}")

                except ValueError as e:
                    doc_progress.console.print(
                        f"[bold red]❌ Failed to apply document: {e}[/bold red]"
                    )
                    raise typer.Exit(code=1)

                except ResourceNotFoundError as e:
                    doc_progress.console.print(
                        f"[bold red]❌ Failed to apply {doc.get('kind', 'Resource')} "
                        f"{doc.get('metadata', {}).get('name', '<unknown>')}: Reason: {e}[/bold red]"
                    )
                    raise typer.Exit(code=1)

                except Exception as e:
                    doc_progress.console.print(
                        f"[bold red]❌ Unexpected error while applying manifest: {e}[/bold red]"
                    )
                    raise typer.Exit(code=1)

            main_progress.update(
                overall_task,
                advance=1,
                description=f"Processed {index}/{total_docs} manifests",
            )

        main_progress.console.print(
            "[bold green]All manifests applied successfully.[/bold green]"
        )


async def wait_for_resources(
    dyn,
    kind: str,
    names: list[str],
    api_version: str,
    namespace: str | None,
    readiness_checker: Callable[[object], bool],
    timeout: int,
):
    api = await dyn.resources.get(api_version=api_version, kind=kind)
    remaining = set(names)
    watcher = watch.Watch()

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        transient=False,
    ) as main_progress, Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        transient=False,
    ) as resource_progress:

        overall_task = main_progress.add_task(
            f"Waiting for {kind}s...", total=len(names)
        )

        resource_tasks = {
            name: resource_progress.add_task(
                f"Waiting for {kind} {name}...", total=None
            )
            for name in names
        }

        async def _watch_loop():
            async for event in api.watch(namespace=namespace, watcher=watcher):
                obj = event["object"]
                name = obj.metadata.name
                if name not in remaining:
                    continue

                if readiness_checker(obj):
                    remaining.remove(name)
                    resource_progress.console.print(
                        f"[green]✔ {kind} {name} is ready[/green]"
                    )
                    resource_progress.remove_task(resource_tasks[name])
                    del resource_tasks[name]
                    main_progress.update(overall_task, advance=1)

                    if remaining:
                        main_progress.update(
                            overall_task,
                            description=f"Waiting for {kind}s: {', '.join(remaining)}",
                        )
                    else:
                        main_progress.update(
                            overall_task,
                            description=f"[bold green]All {kind.lower()}s ready[/bold green]",
                        )
                        break
                else:
                    resource_progress.update(
                        resource_tasks[name],
                        description=f"Waiting for {kind} {name}...",
                    )

        try:
            await asyncio.wait_for(_watch_loop(), timeout=timeout)
        except asyncio.TimeoutError:
            main_progress.console.print(
                f"[bold red]Timeout waiting for {kind.lower()}s: {', '.join(remaining)}[/bold red]"
            )
            raise typer.Exit(code=1)
        except asyncio.CancelledError:
            main_progress.console.print(
                f"[yellow]{kind} watch cancelled by user[/yellow]"
            )
            return
        finally:
            await watcher.close()


async def vault_init_unseal_restore(vault_addr: str, config_file: str):
    client = hvac.Client(url=vault_addr)

    if not client.sys.is_initialized():
        print("Vault not initialized. Initializing now...")
        try:
            result = client.sys.initialize()
            root_token = result["root_token"]
            keys = result["keys"]
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
            f"--vault-address={vault_addr}",
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
            raise RuntimeError(
                f"Vault restore failed with exit code {process.returncode}"
            )
        else:
            print("Vault restore completed successfully.")
            print("STDOUT:\n", stdout.decode().strip())

    except FileNotFoundError:
        print(
            "Vault restore FAILED: 'vault-backup' command not found. Ensure it's in the PATH."
        )
    except Exception as e:
        print(f"An unexpected error occurred during vault restore: {e}")


async def fetch_and_apply_crds(dyn, crd_yaml_path: str):
    try:
        with open(crd_yaml_path, "r") as f:
            data = yaml.load(f)
    except YAMLError as e:
        print(f"Error: Could not parse CRD list file at {crd_yaml_path}: {e}")
        return

    urls = data.get("crds", [])
    if not urls:
        print(f"No CRD URLs found in {crd_yaml_path}")
        return

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        transient=False,
    ) as main_progress:

        main_task = main_progress.add_task("Processing URLs...", total=len(urls))

        async with aiohttp.ClientSession() as session:

            for url in urls:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("{task.description}"),
                    transient=False,
                ) as spinner_progress:

                    fetch_task = spinner_progress.add_task(
                        f"Fetching {url}", total=None
                    )

                    try:

                        async def fetch():
                            async with session.get(url) as resp:
                                resp.raise_for_status()
                                return await resp.text()

                        yaml_text = await retry_with_backoff(
                            fetch,
                            retries=5,
                            base_delay=1,
                            console=spinner_progress.console,
                        )

                        spinner_progress.update(
                            fetch_task, description=f"[green]✔ Fetched {url}[/green]"
                        )

                    except RetryLimitExceeded as e:
                        spinner_progress.update(
                            fetch_task, description="[red]Failed[/red]"
                        )
                        spinner_progress.console.print(
                            f"[bold red]Failed to fetch {url} after {e.retries} attempts: {e.last_exception}[/bold red]"
                        )
                        raise typer.Exit(code=1)

                docs_applied = 0
                for doc in yaml.load_all(yaml_text):
                    if not doc:
                        continue

                    with Progress(
                        SpinnerColumn(),
                        TextColumn("{task.description}"),
                        transient=False,
                    ) as doc_progress:

                        doc_task = doc_progress.add_task(
                            f"Applying {doc.get('kind', '<unknown>')} {doc.get('metadata', {}).get('name', '<unknown>')}...",
                            total=None,
                        )

                        api = await dyn.resources.get(
                            api_version=doc["apiVersion"], kind=doc["kind"]
                        )

                        try:
                            await retry_with_backoff(
                                api.server_side_apply,
                                body=doc,
                                field_manager="flux-client-side-apply",
                                name=doc["metadata"]["name"],
                                retries=5,
                                base_delay=1,
                                console=doc_progress.console,
                            )
                            doc_progress.update(
                                doc_task,
                                description=f"[cyan]✔ Applied {doc['kind']} {doc['metadata']['name']}[/cyan]",
                            )
                            docs_applied += 1

                        except RetryLimitExceeded as e:
                            doc_progress.update(
                                doc_task, description="[red]Failed[/red]"
                            )
                            doc_progress.console.print(
                                f"[bold red]Failed to apply {doc['kind']} {doc['metadata']['name']} after {e.retries} attempts: {e.last_exception}[/bold red]"
                            )
                            raise typer.Exit(code=1)

                if docs_applied == 0:
                    main_progress.console.print(
                        f"[yellow]No documents applied from {url}[/yellow]"
                    )

                main_progress.update(main_task, advance=1)

        main_progress.update(main_task, description="[green]All URLs processed[/green]")


@app.command()
@async_command
async def ensure_namespace_exists(
    name: Annotated[str, typer.Option(help="Namespace to create/check")],
):
    async with k8s_client() as dyn:
        await ensure_namespace(dyn, name)


@app.command(help="Apply Kubernetes YAML manifest file")
@async_command
async def apply_manifest(
    file: Annotated[
        Path,
        typer.Argument(
            help="YAML manifest file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    namespace: Annotated[str, typer.Option(help="Namespace to apply in")],
):
    docs = load_manifest(file, decrypt=False)
    async with k8s_client() as dyn:
        await apply_manifests(dyn, docs, namespace)


@app.command()
@async_command
async def apply_sops_encrypted_manifest(
    ctx: typer.Context,
    file: Annotated[
        Path,
        typer.Argument(
            help="SOPS encrypted YAML file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    namespace: Annotated[str, typer.Option(help="Namespace to apply in")],
    sops_age_key: Annotated[
        Path,
        typer.Option(
            help="Path to SOPS age key file (reads from SOPS_AGE_KEY_FILE env var)",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            envvar="SOPS_AGE_KEY_FILE",
        ),
    ],
):
    source = ctx.get_parameter_source("sops_age_key")
    assert source is not None
    if source.name == "COMMANDLINE":
        os.environ["SOPS_AGE_KEY_FILE"] = str(sops_age_key)
        typer.echo(f"Using CLI-provided SOPS key: {sops_age_key}")
    else:
        typer.echo(f"Using SOPS key from environment variable: {sops_age_key}")

    docs = load_manifest(file, decrypt=True)
    async with k8s_client() as dyn:
        await apply_manifests(dyn, docs, namespace)


@app.command()
@async_command
async def apply_crds(
    file: Annotated[str, typer.Option(help="YAML file listing CRD URLs")],
):
    async with k8s_client() as dyn:
        await fetch_and_apply_crds(dyn, file)


@app.command()
@async_command
async def wait_crds(
    names: Annotated[list[str], typer.Option(help="CRD names")],
    timeout: Annotated[int, typer.Option(help="Timeout in seconds")] = 120,
):
    async with k8s_client() as dyn:
        await wait_for_resources(
            dyn=dyn,
            kind="CustomResourceDefinition",
            names=names,
            api_version="apiextensions.k8s.io/v1",
            namespace=None,
            readiness_checker=lambda _: True,
            timeout=timeout,
        )


@app.command()
@async_command
async def wait_deployments(
    namespace: Annotated[str, typer.Option(help="Kubernetes namespace")],
    names: Annotated[list[str], typer.Argument(help="Deployment names")],
    timeout: Annotated[int, typer.Option(help="Timeout in seconds")] = 240,
):
    async with k8s_client() as dyn:
        await wait_for_resources(
            dyn=dyn,
            kind="Deployment",
            names=names,
            api_version="apps/v1",
            namespace=namespace,
            readiness_checker=lambda obj: (getattr(obj.status, "readyReplicas", 0) or 0) >= (getattr(obj.spec, "replicas", 0) or 0),  # type: ignore
            timeout=timeout,
        )


@app.command()
@async_command
async def wait_daemonsets(
    namespace: Annotated[str, typer.Option(help="Kubernetes namespace")],
    names: Annotated[list[str], typer.Option(help="DaemonSet names")],
    timeout: Annotated[int, typer.Option(help="Timeout in seconds")] = 240,
):
    async with k8s_client() as dyn:
        await wait_for_resources(
            dyn=dyn,
            kind="DaemonSet",
            names=names,
            api_version="apps/v1",
            namespace=namespace,
            readiness_checker=lambda obj: (getattr(obj.status, "numberReady", 0) or 0) >= (getattr(obj.status, "desiredNumberScheduled", 0) or 0),  # type: ignore
            timeout=timeout,
        )


@app.command()
@async_command
async def wait_statefulsets(
    namespace: Annotated[str, typer.Option(help="Kubernetes namespace")],
    names: Annotated[list[str], typer.Option(help="StatefulSet names")],
    timeout: Annotated[int, typer.Option(help="Timeout in seconds")] = 240,
):
    async with k8s_client() as dyn:
        await wait_for_resources(
            dyn=dyn,
            kind="StatefulSet",
            names=names,
            api_version="apps/v1",
            namespace=namespace,
            readiness_checker=lambda obj: (getattr(obj.status, "readyReplicas", 0) or 0) >= (getattr(obj.spec, "replicas", 0) or 0),  # type: ignore
            timeout=timeout,
        )


@app.command(help="Init, unseal and restore a Vault cluster")
@async_command
async def init_vault(
    addr: Annotated[str, typer.Option(help="Vault address")],
    config: Annotated[
        str, typer.Option(help="vault-backup cli config file")
    ] = "/project/.vault/vault-backup.yaml",
):
    await vault_init_unseal_restore(addr, config)


if __name__ == "__main__":
    app()
