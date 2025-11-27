#!/usr/bin/env python3

import asyncio
import base64
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Literal, overload

import aiohttp
import hvac
import inquirer
import typer
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from hvac.exceptions import InvalidPath, InvalidRequest, VaultError
from inquirer.themes import RedSolace
from kubernetes_asyncio import client, config, dynamic, watch  # type: ignore
from kubernetes_asyncio.client.exceptions import ApiException  # type: ignore
from kubernetes_asyncio.dynamic import DynamicClient  # type: ignore
from kubernetes_asyncio.dynamic.exceptions import ResourceNotFoundError  # type: ignore
from requests import Response
from rich.console import Console
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

yaml = YAML()
yaml.preserve_quotes = True
yaml.constructor.add_constructor(
    "tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node)
)

app = typer.Typer(name="home-ops-cli")


class WorkflowStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    QUEUED = "queued"


@asynccontextmanager
async def k8s_client():
    await config.load_kube_config()
    async with client.ApiClient() as api_client:
        dyn = await DynamicClient(api_client)
        yield dyn


def with_debug(func):
    @wraps(func)
    def wrapper(
        *args,
        debug: bool = typer.Option(False, "--debug", help="Enable debug"),
        **kwargs,
    ):
        if debug:
            typer.echo("Debug mode enabled")
        return func(*args, **kwargs)

    return wrapper


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
                    f"Applying {doc.get('kind', '<unknown>')} {
                        doc.get('metadata', {}).get('name', '<unknown>')
                    }...",
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
                        f"[bold red]❌ Failed to apply {
                            doc.get('kind', 'Resource')
                        }: API Error {e.status}[/bold red]"
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
                        f"{doc.get('metadata', {}).get('name', '<unknown>')}: Reason: {
                            e
                        }[/bold red]"
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

    with (
        Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            transient=False,
        ) as main_progress,
        Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            transient=False,
        ) as resource_progress,
    ):
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
                            description=f"[bold green]All {
                                kind.lower()
                            }s ready[/bold green]",
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
                f"[bold red]Timeout waiting for {kind.lower()}s: {
                    ', '.join(remaining)
                }[/bold red]"
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
        SpinnerColumn(),
        TextColumn("{task.description}"),
        transient=True,
    ) as spinner_progress:
        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            transient=True,
        ) as main_progress:
            main_task = main_progress.add_task("Processing URLs...", total=len(urls))

            async with aiohttp.ClientSession() as session:

                async def worker(url: str):
                    spinner_id = spinner_progress.add_task(
                        f"Fetching {url}", total=None
                    )

                    async def fetch():
                        async with session.get(url) as resp:
                            resp.raise_for_status()
                            return await resp.text()

                    try:
                        yaml_text = await retry_with_backoff(
                            fetch,
                            retries=5,
                            base_delay=1,
                            console=spinner_progress.console,
                        )
                        spinner_progress.console.print(
                            f"[green]✔ Fetched {url}[/green]"
                        )
                    except RetryLimitExceeded as e:
                        spinner_progress.console.print(
                            f"[bold red]Failed to fetch {url} after {
                                e.retries
                            } attempts: {e.last_exception}[/bold red]"
                        )
                        spinner_progress.remove_task(spinner_id)
                        raise typer.Exit(code=1)

                    yaml_parser = YAML()
                    try:
                        docs = yaml_parser.load_all(yaml_text)
                    except Exception as e:
                        spinner_progress.console.print(
                            f"[bold red]YAML parse error in {url}: {e}[/bold red]"
                        )
                        spinner_progress.remove_task(spinner_id)
                        raise typer.Exit(code=1)

                    docs_applied = 0

                    for doc in docs:
                        if not doc:
                            continue

                        kind = doc.get("kind", "<unknown>")
                        name = doc.get("metadata", {}).get("name", "<unknown>")

                        spinner_progress.update(
                            spinner_id, description=f"Applying {kind} {name}..."
                        )

                        api = await dyn.resources.get(
                            api_version=doc["apiVersion"], kind=doc["kind"]
                        )

                        try:
                            await retry_with_backoff(
                                api.server_side_apply,
                                body=doc,
                                field_manager="flux-client-side-apply",
                                name=name,
                                retries=5,
                                base_delay=1,
                                console=spinner_progress.console,
                            )
                            spinner_progress.console.print(
                                f"[cyan]✔ Applied {kind} {name}[/cyan]"
                            )
                            docs_applied += 1
                        except RetryLimitExceeded as e:
                            spinner_progress.console.print(
                                f"[bold red]Failed to apply {kind} {name} after {
                                    e.retries
                                } attempts: {e.last_exception}[/bold red]"
                            )
                            spinner_progress.remove_task(spinner_id)
                            raise typer.Exit(code=1)

                    if docs_applied == 0:
                        main_progress.console.print(
                            f"[yellow]No documents applied from {url}[/yellow]"
                        )

                    spinner_progress.remove_task(spinner_id)
                    main_progress.update(main_task, advance=1)

                await asyncio.gather(*(worker(url) for url in urls))


def validate_kube_rfc1123_label(value: str | list[str]) -> str | list[str]:
    def validate_item(item: str) -> str:
        normalized = item.lower()

        if len(normalized) > 63:
            raise typer.BadParameter(
                f"Name '{normalized}' cannot be longer than 63 characters. "
                f"Found {len(normalized)}."
            )

        if not re.fullmatch(r"[a-z0-9-]+", normalized):
            raise typer.BadParameter(
                f"Name '{normalized}' must contain only lowercase alphanumeric "
                f"characters or hyphen ('-')."
            )

        if not normalized[0].isalpha():
            raise typer.BadParameter(
                f"Name '{normalized}' must start with an alphabetic character (a-z)."
            )

        if not normalized[-1].isalnum():
            raise typer.BadParameter(
                f"Name '{normalized}' must end with an alphanumeric character "
                f"(a-z or 0-9)."
            )

        return normalized

    if isinstance(value, str):
        return validate_item(value)

    return [validate_item(v) for v in value]


@app.command()
@async_command
async def ensure_namespace_exists(
    name: Annotated[
        str,
        typer.Argument(
            help="Namespace to create/check", callback=validate_kube_rfc1123_label
        ),
    ],
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
    namespace: Annotated[
        str,
        typer.Option(
            help="Namespace to apply in", callback=validate_kube_rfc1123_label
        ),
    ],
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
    namespace: Annotated[
        str,
        typer.Option(
            help="Namespace to apply in", callback=validate_kube_rfc1123_label
        ),
    ],
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
    file: Annotated[
        str,
        typer.Argument(
            help="YAML file listing CRD URLs",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
):
    async with k8s_client() as dyn:
        await fetch_and_apply_crds(dyn, file)


@app.command()
@async_command
async def wait_crds(
    names: Annotated[
        list[str],
        typer.Argument(help="CRD names", callback=validate_kube_rfc1123_label),
    ],
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
    names: Annotated[
        list[str],
        typer.Argument(help="Deployment names", callback=validate_kube_rfc1123_label),
    ],
    namespace: Annotated[
        str,
        typer.Option(help="Kubernetes namespace", callback=validate_kube_rfc1123_label),
    ],
    timeout: Annotated[int, typer.Option(help="Timeout in seconds")] = 240,
):
    async with k8s_client() as dyn:
        await wait_for_resources(
            dyn=dyn,
            kind="Deployment",
            names=names,
            api_version="apps/v1",
            namespace=namespace,
            readiness_checker=lambda obj: (getattr(obj.status, "readyReplicas", 0) or 0)
            >= (getattr(obj.spec, "replicas", 0) or 0),  # type: ignore
            timeout=timeout,
        )


@app.command()
@async_command
async def wait_daemonsets(
    names: Annotated[
        list[str],
        typer.Argument(help="DaemonSet names", callback=validate_kube_rfc1123_label),
    ],
    namespace: Annotated[
        str,
        typer.Option(help="Kubernetes namespace", callback=validate_kube_rfc1123_label),
    ],
    timeout: Annotated[int, typer.Option(help="Timeout in seconds")] = 240,
):
    async with k8s_client() as dyn:
        await wait_for_resources(
            dyn=dyn,
            kind="DaemonSet",
            names=names,
            api_version="apps/v1",
            namespace=namespace,
            readiness_checker=lambda obj: (getattr(obj.status, "numberReady", 0) or 0)
            >= (
                # type: ignore
                getattr(obj.status, "desiredNumberScheduled", 0) or 0
            ),
            timeout=timeout,
        )


@app.command()
@async_command
async def wait_statefulsets(
    names: Annotated[
        list[str],
        typer.Argument(help="StatefulSet names", callback=validate_kube_rfc1123_label),
    ],
    namespace: Annotated[
        str,
        typer.Option(help="Kubernetes namespace", callback=validate_kube_rfc1123_label),
    ],
    timeout: Annotated[int, typer.Option(help="Timeout in seconds")] = 240,
):
    async with k8s_client() as dyn:
        await wait_for_resources(
            dyn=dyn,
            kind="StatefulSet",
            names=names,
            api_version="apps/v1",
            namespace=namespace,
            readiness_checker=lambda obj: (getattr(obj.status, "readyReplicas", 0) or 0)
            >= (getattr(obj.spec, "replicas", 0) or 0),  # type: ignore
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


@app.command(
    help="Creates new talosconfig with key pair using the root Talos API CA from the control plane machine configuration."
)
def regen_talosconfig(
    controlplane: Annotated[
        Path,
        typer.Argument(
            help="Path to control plane machine configuration",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    endpoints: Annotated[
        list[str] | None,
        typer.Option("--endpoints", "-e", help="control plane endpoints"),
    ] = None,
    nodes: Annotated[
        list[str] | None, typer.Option("--nodes", "-n", help="nodes endpoints")
    ] = None,
    context: Annotated[
        str, typer.Option(help="context name to use for the new talosconfig")
    ] = "default",
    debug: Annotated[bool, typer.Option(help="enable debugging", is_flag=True)] = False,
    decrypt: Annotated[
        bool,
        typer.Option(help="decrypt the machine configuration with SOPS", is_flag=True),
    ] = True,
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            file_okay=True,
            dir_okay=False,
            writable=True,
            resolve_path=True,
            help="output path for the new talosconfig",
        ),
    ] = Path("talosconfig"),
):
    work_dir = Path(tempfile.mkdtemp(prefix="talos-regen-"))
    typer.echo(f"🔧 Working directory: {work_dir}")

    try:
        if not decrypt:
            content = controlplane.read_text()
        else:
            content = subprocess.run(
                ["sops", "-d", str(controlplane)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout

        ca_crt_b64 = None
        ca_key_b64 = None
        for doc in yaml.load_all(content):
            if doc and "machine" in doc and "ca" in doc.get("machine", {}):
                ca_crt_b64 = doc["machine"]["ca"]["crt"]
                ca_key_b64 = doc["machine"]["ca"]["key"]
                break

        if not ca_crt_b64 or not ca_key_b64:
            typer.echo(
                "Could not find machine.ca.crt or machine.ca.key in controlplane machine configuration",
                err=True,
            )
            raise typer.Exit(code=1)

        ca_crt_path = work_dir / "ca.crt"
        ca_key_path = work_dir / "ca.key"
        ca_crt_path.write_bytes(base64.b64decode(ca_crt_b64))
        ca_key_path.write_bytes(base64.b64decode(ca_key_b64))
        typer.echo("✅ Extracted CA certificate and key")

        subprocess.run(
            ["talosctl", "gen", "key", "--name", "admin"], cwd=work_dir, check=True
        )
        subprocess.run(
            ["talosctl", "gen", "csr", "--key", "admin.key", "--ip", "127.0.0.1"],
            cwd=work_dir,
            check=True,
        )
        subprocess.run(
            [
                "talosctl",
                "gen",
                "crt",
                "--ca",
                "ca",
                "--csr",
                "admin.csr",
                "--name",
                "admin",
                "--hours",
                "8760",
            ],
            cwd=work_dir,
            check=True,
        )
        typer.echo("✅ Generated admin key, CSR, and certificate")

        admin_crt_path = work_dir / "admin.crt"
        admin_key_path = work_dir / "admin.key"

        config = {
            "context": context,
            "contexts": {
                context: {
                    "endpoints": endpoints or [],
                    "nodes": nodes or [],
                    "ca": base64.b64encode(ca_crt_path.read_bytes()).decode("utf-8"),
                    "crt": base64.b64encode(admin_crt_path.read_bytes()).decode(
                        "utf-8"
                    ),
                    "key": base64.b64encode(admin_key_path.read_bytes()).decode(
                        "utf-8"
                    ),
                }
            },
        }

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as f:
            yaml.dump(config, f)
        typer.echo(f"✅ Created talosconfig: {output}")

    finally:
        if not debug:
            shutil.rmtree(work_dir)
            typer.echo("🧹 Cleaned up temporary files")
        else:
            typer.echo(f"📁 Temporary files kept in: {work_dir}")


HVACResp = dict[str, Any] | Response | None


def to_dict(resp: HVACResp) -> dict[str, Any]:
    if isinstance(resp, Response):
        return resp.json()
    if resp is None:
        return {}
    return resp


@app.command()
def rotate_issuing_ca(
    vault_addr: Annotated[
        str | None,
        typer.Option(
            "--vault-addr",
            "-a",
            envvar="VAULT_ADDR",
            help="Vault URL (e.g., https://vault.example.com:8200)",
            prompt=True,
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-t",
            envvar="VAULT_TOKEN",
            help="Vault token. If omitted, username/password login will be used.",
            prompt=True,
            prompt_required=False,
        ),
    ] = None,
):
    ISS_MOUNT = "pki_iss"
    INT_MOUNT = "pki_int"
    COMMON_NAME = "DarkfellaNET Issuing CA v1.1.1"
    TTL = "8760h"

    client = hvac.Client(url=vault_addr)

    if token:
        client.token = token
    else:
        typer.echo("Vault token not found, logging in with username/password.")
        username = typer.prompt("Vault username")
        password = typer.prompt("Vault password", hide_input=True)
        try:
            login_resp = client.auth.userpass.login(
                username=username, password=password
            )
            client.token = login_resp["auth"]["client_token"]
            typer.echo("Logged in successfully.")
        except InvalidRequest as e:
            typer.echo(f"Vault login failed: {e}")
            raise typer.Exit(1)

    if not client.is_authenticated():
        typer.echo("Authentication to Vault failed.")
        raise typer.Exit(1)

    typer.echo(f"Connected to Vault at {vault_addr}")

    try:
        typer.echo("Generating CSR using existing key material...")
        generate_resp = to_dict(
            client.write(
                f"{ISS_MOUNT}/issuers/generate/intermediate/existing",
                common_name=COMMON_NAME,
                country="Bulgaria",
                locality="Sofia",
                organization="DarkfellaNET",
                ttl=TTL,
                format="pem_bundle",
                wrap_ttl=None,
            )
        )
        csr = generate_resp["data"]["csr"]
    except (VaultError, InvalidRequest) as e:
        typer.echo(f"Failed to generate CSR: {e}")
        raise typer.Exit(1)

    try:
        typer.echo("Signing CSR with intermediate CA...")
        sign_resp = to_dict(
            client.write(
                f"{INT_MOUNT}/root/sign-intermediate",
                csr=csr,
                country="Bulgaria",
                locality="Sofia",
                organization="DarkfellaNET",
                format="pem_bundle",
                ttl=TTL,
                common_name=COMMON_NAME,
                wrap_ttl=None,
            )
        )
        signed_cert = sign_resp["data"]["certificate"]
    except (VaultError, InvalidRequest) as e:
        typer.echo(f"Failed to sign CSR: {e}")
        raise typer.Exit(1)

    try:
        typer.echo(f"Importing signed certificate back into {ISS_MOUNT}...")
        import_resp = to_dict(
            client.write(
                f"{ISS_MOUNT}/intermediate/set-signed",
                certificate=signed_cert,
                wrap_ttl=None,
            )
        )
        imported_issuers = import_resp.get("data", {}).get("imported_issuers", [])
        if not imported_issuers:
            raise RuntimeError("Vault did not return an imported issuer ID!")
        new_issuer_id = imported_issuers[0]

        client.write(
            f"{ISS_MOUNT}/config/issuers", default=new_issuer_id, wrap_ttl=None
        )
        typer.echo(f"New issuer {new_issuer_id} set as default")
    except (VaultError, InvalidRequest, InvalidPath) as e:
        typer.echo(f"Failed to import signed certificate: {e}")
        raise typer.Exit(1)

    cert = x509.load_pem_x509_certificate(signed_cert.encode(), default_backend())
    typer.echo("\nNew Issuing CA info:")
    typer.echo(f"  Subject: {cert.subject.rfc4514_string()}")
    typer.echo(f"  Serial: {cert.serial_number}")
    typer.echo(f"  Expires: {cert.not_valid_after.isoformat()} UTC")

    typer.echo("Done! Issuing CA successfully reissued and set as default.")


@app.command(help="Fetch AWS IP ranges and optionally update a network policy YAML")
@async_command
async def fetch_aws_ips(
    region: Annotated[str, typer.Option(help="AWS region to filter")] = "us-east-1",
    service: Annotated[str, typer.Option(help="AWS service to filter")] = "AMAZON",
    output_file: Annotated[
        Path, typer.Option(help="File to write filtered CIDRs")
    ] = Path("aws-ip-ranges.txt"),
    policy_file: Annotated[
        Path | None,
        typer.Option(
            help="Path to cilium network policy YAML to update",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            writable=True,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    typer.echo(f"Fetching IP ranges for region='{region}' and service='{service}'...")

    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://ip-ranges.amazonaws.com/ip-ranges.json"
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

    cidrs = sorted(
        {
            prefix["ip_prefix"]
            for prefix in data["prefixes"]
            if prefix["region"] == region and prefix["service"] == service
        }
    )

    if not cidrs:
        typer.echo("No CIDRs found for the specified region and service.")
        raise typer.Exit()

    typer.echo(f"Found {len(cidrs)} unique CIDR blocks.")

    if policy_file:
        try:
            with open(policy_file, "r") as f:
                policy = yaml.load(f)

            target_port = "443"
            rule_to_update = None
            egress_rules = policy.get("spec", {}).get("egress")

            if isinstance(egress_rules, list):
                for rule in egress_rules:
                    if isinstance(rule.get("toPorts"), list):
                        for port_config in rule["toPorts"]:
                            if isinstance(port_config.get("ports"), list):
                                for port_entry in port_config["ports"]:
                                    if (
                                        isinstance(port_entry.get("port"), str)
                                        and port_entry["port"] == target_port
                                    ):
                                        rule_to_update = rule
                                        break
                                if rule_to_update:
                                    break
                        if rule_to_update:
                            break

            if rule_to_update is None:
                typer.echo(
                    f"[bold red]Error: Could not find an egress rule in {policy_file} targeting port '{target_port}'. Aborting policy update.[/bold red]",
                    err=True,
                )
                raise typer.Exit(code=1)

            egress_cidrs_list = rule_to_update.get("toCIDRSet", [])
            existing_cidrs = {
                entry["cidr"]
                for entry in egress_cidrs_list
                if isinstance(entry, dict) and "cidr" in entry
            }

            all_cidrs = sorted(existing_cidrs | set(cidrs))

            rule_to_update["toCIDRSet"] = [{"cidr": c} for c in all_cidrs]

            with open(policy_file, "w") as f:
                yaml.dump(policy, f)

            typer.echo(
                f"Updated {policy_file} with {
                    len(all_cidrs)
                } unique CIDRs in the egress rule targeting port {target_port}."
            )

        except Exception as e:
            typer.echo(
                f"[bold red]An error occurred during policy file processing: {e}[/bold red]",
                err=True,
            )
            raise typer.Exit(code=1)

    else:
        with open(output_file, "w") as f:
            for c in cidrs:
                f.write(f"- cidr: {c}\n")

        typer.echo(f"Wrote {len(cidrs)} CIDRs to {output_file}.")


@overload
async def make_request_and_handle_ratelimit(
    session: aiohttp.ClientSession,
    method: Literal["GET"],
    url: str,
    console: Console,
    **kwargs: Any,
) -> dict[str, Any]: ...


@overload
async def make_request_and_handle_ratelimit(
    session: aiohttp.ClientSession,
    method: Literal["DELETE", "POST", "PATCH", "PUT", "HEAD", "OPTIONS"],
    url: str,
    console: Console,
    **kwargs: Any,
) -> int: ...


async def make_request_and_handle_ratelimit(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    console: Console,
    **kwargs: Any,
) -> dict[str, Any] | int:
    sem = asyncio.Semaphore(20)
    max_retries = 3
    attempt = 0
    while True:
        attempt += 1

        async with sem:
            async with session.request(method, url, **kwargs) as resp:
                if resp.status in (403, 429):
                    reset_time = int(resp.headers.get("x-ratelimit-reset", 0))
                    current_time = int(time.time())
                    sleep_time = max(reset_time - current_time, 0) + 120

                    if sleep_time < 5 and resp.status == 429:
                        sleep_time = int(resp.headers.get("Retry-After", 120))

                    msg = f"[yellow]Rate limit hit ({resp.status}). Waiting {
                        sleep_time:.0f}s until reset...[/yellow]"
                    console.print(msg)
                    await asyncio.sleep(sleep_time)
                    continue

                if resp.status >= 400:
                    if attempt >= max_retries:
                        console.print(
                            f"[bold red]Permanent failure after {
                                max_retries
                            } attempts. Raising error for {resp.status}.[/bold red]"
                        )
                        resp.raise_for_status()

                    console.print(
                        f"[red]Error {resp.status} encountered (Attempt {attempt}/{
                            max_retries
                        }). Retrying in 5s.[/red]"
                    )
                    await asyncio.sleep(5)
                    continue

                if method == "GET":
                    resp.raise_for_status()
                    return await resp.json()
                else:
                    return resp.status


def validate_repo_format(value: str) -> str:
    error_msg = f"Invalid repository format: '{value}'. Must be in 'owner/repo' format (e.g., 'google/typer')."

    if value.count("/") != 1:
        raise typer.BadParameter(error_msg)

    owner, repo_name = value.split("/", 1)
    if not owner or not repo_name:
        raise typer.BadParameter(error_msg)

    if not re.match(r"^[\w-]+/[\w.-]+$", value):
        raise typer.BadParameter(error_msg)

    return value


def validate_github_token(value: str) -> str:
    min_len = 5
    max_len = 255
    if not (min_len <= len(value) <= max_len):
        raise typer.BadParameter(
            f"Token length must be between {min_len} and {max_len} characters. Found {
                len(value)
            } characters."
        )

    token_pattern = re.compile(r"^(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]+$")
    if not token_pattern.match(value):
        error_msg = (
            "Invalid token format. It must start with one of the required prefixes "
            "(ghp_, github_pat_, gho_, ghu_, ghs_, or ghr_) "
            "and contain only alphanumeric characters or underscores ([A-Za-z0-9_]) for the remainder of the token."
        )
        raise typer.BadParameter(error_msg)

    return value


@app.command(help="Delete GitHub Actions workflow runs")
@async_command
async def dwr(
    token: Annotated[
        str,
        typer.Option(
            help="GitHub personal access token", callback=validate_github_token
        ),
    ],
    repo: Annotated[
        str,
        typer.Argument(
            help="GitHub repo in owner/repo format", callback=validate_repo_format
        ),
    ],
    status: Annotated[
        WorkflowStatus | None,
        typer.Option(help="Filter runs by status (e.g., 'success', 'failure')"),
    ] = None,
    limit: Annotated[
        int, typer.Option(help="Max number of workflow runs to fetch", min=1, max=1000)
    ] = 100,
    delete_all: Annotated[
        bool,
        typer.Option(
            help="Delete all workflow runs fetched (up to the --limit specified)"
        ),
    ] = False,
):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_base_url = f"https://api.github.com/repos/{repo}/actions/runs"
    per_page = 100

    async with aiohttp.ClientSession(headers=headers) as session:
        fetch_tasks: list[Awaitable[Any]] = []
        all_runs: list[dict[str, Any]] = []

        initial_params: dict[str, str | int] = {"per_page": 1, "page": 1}
        if status:
            initial_params["status"] = status.value

        console = Console()

        initial_data = await make_request_and_handle_ratelimit(
            session, "GET", api_base_url, console=console, params=initial_params
        )

        total_count = initial_data.get("total_count", 0)
        runs_to_fetch = min(total_count, limit)

        if runs_to_fetch == 0:
            typer.echo("No workflow runs found.")
            raise typer.Exit()

        pages_needed = (runs_to_fetch + per_page - 1) // per_page

        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            transient=False,
        ) as progress:
            fetch_task_id = progress.add_task(
                f"Fetching workflow runs for {repo}", total=runs_to_fetch
            )

            for page in range(1, pages_needed + 1):
                params: dict[str, str | int] = {"per_page": per_page, "page": page}
                if status:
                    params["status"] = status.value

                fetch_tasks.append(
                    make_request_and_handle_ratelimit(
                        session,
                        "GET",
                        api_base_url,
                        console=progress.console,
                        params=params,
                    )
                )

            for coro in asyncio.as_completed(fetch_tasks):
                try:
                    data = await coro
                    runs = data.get("workflow_runs", [])

                    for run in runs:
                        if len(all_runs) >= limit:
                            break
                        all_runs.append(run)
                        progress.update(fetch_task_id, advance=1)

                    if len(all_runs) >= limit:
                        break
                except Exception as e:
                    progress.console.print(f"[red]Error fetching page: {e}[/red]")

            progress.update(fetch_task_id, completed=len(all_runs))

    all_runs.sort(key=lambda x: x["id"], reverse=True)

    CONCLUSION_MAP = {
        WorkflowStatus.SUCCESS.value: "GOOD",
        WorkflowStatus.FAILURE.value: "FAIL",
        WorkflowStatus.NEUTRAL.value: "NEUTR",
        WorkflowStatus.CANCELLED.value: "CANC",
        WorkflowStatus.SKIPPED.value: "SKIP",
        WorkflowStatus.TIMED_OUT.value: "TIMEOUT",
        WorkflowStatus.ACTION_REQUIRED.value: "ACT_REQ",
    }

    ids_to_delete: list[int] = []

    if not delete_all:
        choices_list: list[tuple[str, int]] = []

        for run in all_runs:
            s_date = datetime.fromisoformat(
                run["created_at"].replace("Z", "+00:00")
            ).strftime("%b %d %Y %H:%M")

            if run["status"] in ("queued", "in_progress"):
                conclusion = run["status"].upper()
            else:
                conclusion = CONCLUSION_MAP.get(
                    run["conclusion"], str(run["conclusion"]).upper()
                )

            display_str = (
                f"{conclusion:<8}"
                f"{s_date:<22}"
                f"{run['id']:<14}"
                f"{run['event']:<20}"
                f"{run['name']}"
            )

            choices_list.append((display_str, run["id"]))

        def autocomplete_runs(text: str, state: Any) -> list[tuple[str, int]]:
            if not text:
                return choices_list

            return [
                choice_tuple
                for choice_tuple in choices_list
                if text.lower() in choice_tuple[0].lower()
            ]

        questions = [
            inquirer.Checkbox(
                "selected_runs",
                message=f"Select workflows to delete (Total: {len(choices_list)})",
                choices=choices_list,
                carousel=True,
                autocomplete=autocomplete_runs,
            )
        ]
        answers = inquirer.prompt(questions, theme=RedSolace())

        if not answers:
            raise typer.Exit()

        ids_to_delete = answers["selected_runs"]

    else:
        ids_to_delete = [run["id"] for run in all_runs]

    async with aiohttp.ClientSession(headers=headers) as session:
        with Progress(
            TextColumn("[bold red]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            transient=False,
        ) as progress:
            delete_task_id = progress.add_task(
                "Deleting workflow runs", total=len(ids_to_delete)
            )

            async def delete_run_task(run_id: int):
                del_url = f"{api_base_url}/{run_id}"
                line_str = f"Run ID: {run_id}"

                try:
                    status_code = await make_request_and_handle_ratelimit(
                        session, "DELETE", del_url, console=progress.console
                    )

                    if status_code == 204:
                        progress.console.print(f"Deleted: {line_str}")
                        progress.update(delete_task_id, advance=1)
                    else:
                        progress.console.print(
                            f"[red]Failed ({status_code}): {line_str}[/red]"
                        )
                except Exception as e:
                    progress.console.print(f"[red]Error deleting {run_id}: {e}[/red]")

            await asyncio.gather(*(delete_run_task(run_id) for run_id in ids_to_delete))


if __name__ == "__main__":
    app()
