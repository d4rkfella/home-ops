#!/usr/bin/env python3
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from enum import Enum, auto
import subprocess
import os

import usb.core
import usb.util
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from kubernetes_asyncio import client, config, watch
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.config import ConfigException
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
    TextArea,
)


class VMStatus(Enum):
    RUNNING = auto()
    PAUSED = auto()
    STOPPED = auto()
    UNKNOWN = auto()

    @staticmethod
    def from_string(value: str) -> "VMStatus":
        if not value:
            return VMStatus.UNKNOWN
        value = str(value).lower()
        for status in VMStatus:
            if status.name.lower() == value:
                return status
        return VMStatus.UNKNOWN

    @property
    def display(self) -> str:
        return self.name.capitalize()


class VMAction(Enum):
    START_VM = auto()
    STOP_VM = auto()
    PAUSE_VM = auto()
    UNPAUSE_VM = auto()
    RESTART_VM = auto()
    VNC_CONNECT = auto()
    GENERATE_KEYS = auto()
    USB_REDIRECT = auto()


class USBDevice(ListItem):
    def __init__(self, device_id: str, description: str):
        super().__init__(Label(f"🔌 {description}"))
        self.device_id = device_id
        self.description = description


@dataclass(frozen=True)
class VMData:
    namespace: str
    name: str
    status: VMStatus
    uid: str
    ready: bool | None

    creation_timestamp: str
    resource_version: str
    run_strategy: str
    cpu_info: str
    memory_info: str
    disks: list[str]
    interfaces: list[str]
    conditions: list[dict[str, Any]]

    @classmethod
    def from_raw_object(cls, obj: dict[str, Any]) -> "VMData":
        metadata = obj.get("metadata", {})
        spec = obj.get("spec", {})
        status_dict = obj.get("status", {})

        ns = metadata.get("namespace", "Unknown")
        name = metadata.get("name", "Unknown")
        uid = metadata.get("uid", "Unknown")
        status = VMStatus.from_string(status_dict.get("printableStatus", "Unknown"))
        ready = next(
            (
                c.get("status") == "True"
                for c in status_dict.get("conditions", [])
                if c.get("type") == "Ready"
            ),
            None,
        )

        creation_ts = metadata.get("creationTimestamp", "")
        resource_version = metadata.get("resourceVersion", "")
        run_strategy = spec.get("runStrategy", "")

        template_spec = spec.get("template", {}).get("spec", {})
        domain = template_spec.get("domain", {})
        domain_cpu = domain.get("cpu", {})
        resources = domain.get("resources", {})
        limits = resources.get("limits", {})
        requests = resources.get("requests", {})

        if domain_cpu:
            cpu_info = f"{requests.get('cpu', 'Unknown')} CPUs (dedicated: {domain_cpu.get('dedicatedCpuPlacement', False)}, isolateEmulatorThread: {domain_cpu.get('isolateEmulatorThread', False)})"
        else:
            cpu_info = f"{requests.get('cpu', 'Unknown')} CPUs"

        memory_info = limits.get("memory", requests.get("memory", "Unknown"))

        disks = [
            d.get("name", "Unknown") for d in domain.get("devices", {}).get("disks", [])
        ]
        interfaces = [
            i.get("name", "Unknown")
            for i in domain.get("devices", {}).get("interfaces", [])
        ]

        conditions = status_dict.get("conditions", [])

        return cls(
            namespace=ns,
            name=name,
            status=status,
            uid=uid,
            ready=ready,
            creation_timestamp=creation_ts,
            resource_version=resource_version,
            run_strategy=run_strategy,
            cpu_info=cpu_info,
            memory_info=memory_info,
            disks=disks,
            interfaces=interfaces,
            conditions=conditions,
        )


class USBRedirectSelection(ModalScreen[str]):
    BINDINGS = [
        Binding("escape", "dismiss_screen", "Cancel", priority=True),
    ]

    CSS = """
    USBRedirScreen {
        align: center middle;
        background: rgba(0,0,0,0.8);
    }
    #usb-dialog {
        height: 60%;
        width: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    #usb-title {
        text-style: bold;
        margin-bottom: 1;
        color: $accent;
    }
    ListView {
        border: solid $panel;
        height: 1fr;
    }
    """

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical(id="usb-dialog"):
            yield ListView(id="usb-list")
            yield Static("Use the arrow keys to select, then press ENTER to redirect.")

    async def on_mount(self) -> None:
        await self.load_usb_devices()

    async def load_usb_devices(self) -> None:
        list_view = self.query_one("#usb-list", ListView)

        def find_usb_devices() -> list["USBDevice"] | None:
            if not (usb_devices := usb.core.find(find_all=True)):
                return

            items: list["USBDevice"] = []

            for device in usb_devices:
                vendor_id_hex = f"{device.idVendor:04x}"
                product_id_hex = f"{device.idProduct:04x}"
                device_id = f"{vendor_id_hex}:{product_id_hex}"

                try:
                    description = usb.util.get_string(device, device.iProduct)
                except Exception:
                    description = (
                        f"unknown device (VID:{vendor_id_hex} PID:{product_id_hex})"
                    )

                # 1d6b is Linux Foundation root hub (filter this out)
                if vendor_id_hex not in ("1d6b", "0000"):
                    item = USBDevice(device_id, f"{description} ({device_id})")
                    items.append(item)

            return items

        try:
            if not (list_items := await asyncio.to_thread(find_usb_devices)):
                self.app.notify("no usb devices found.", timeout=6)
                return

            await list_view.extend(list_items)

        except Exception as e:
            self.app.notify(
                f"error loading usb devices: {type(e).__name__} {e}", severity="error"
            )
            self.dismiss(None)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        selected_item = cast(USBDevice, event.item)
        self.dismiss(selected_item.device_id)


class SSHKeyDisplay(ModalScreen):
    CSS = """
    SSHKeyDisplay {
        align: center middle;
        background: rgba(0,0,0,0.7);
    }

    #dialog {
        padding: 1 2;
        background: $surface;
        border: thick $primary;
        width: 80;
        height: auto;
    }

    #key-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #pub-key-area {
        height: 8;
        margin-bottom: 1;
        background: $boost;
    }

    #key-path {
        color: $text-muted;
        margin-bottom: 1;
    }

    Horizontal {
        align: center middle;
        height: auto;
    }
    """

    def __init__(self, vm_name: str, pub_key: str, key_path: str):
        super().__init__()
        self.vm_name = vm_name
        self.pub_key = pub_key
        self.key_path = key_path

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"🔑 SSH Key for {self.vm_name}", id="key-title")
            yield Label(f"Private key saved to: {self.key_path}", id="key-path")
            yield TextArea(
                self.pub_key, id="pub-key-area", read_only=True, compact=True
            )
            with Horizontal():
                yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss()


class VMInfoDock(VerticalScroll):
    """A static widget to display detailed information about the selected VM."""

    DEFAULT_CSS = """
    VMInfoDock {
        width: 45%;
        min-width: 30;
        height: 100%;
        background: $panel;
        border-left: wide $primary;
        padding: 1;
    }
    .info-header {
        text-style: bold italic;
        color: $accent;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("VM Details", classes="info-header")
        yield Markdown("Select a VM to view details...", id="info-content")

    async def update_vm_info(self, vm: VMData) -> None:
        name = vm.name
        namespace = vm.namespace
        uid = vm.uid
        resource_version = vm.resource_version
        creation_ts = vm.creation_timestamp

        printable_status = vm.status.display
        ready = vm.ready
        conditions = vm.conditions

        run_strategy = vm.run_strategy
        cpu_info = vm.cpu_info
        memory_info = vm.memory_info
        disk_names = ", ".join(vm.disks)
        iface_names = ", ".join(vm.interfaces)

        markdown = (
            f"**VM:** {name}  \n"
            + f"**Namespace:** {namespace}  \n"
            + f"**UID:** {uid}  \n"
            + f"**Resource Version:** {resource_version}  \n"
            + f"**Created At:** {creation_ts}  \n"
            + f"**Status:** {printable_status}  \n"
            + f"**Ready:** {ready}  \n"
            + f"**Run Strategy:** {run_strategy}  \n"
            + f"**CPU:** {cpu_info}  \n"
            + f"**Memory:** {memory_info}  \n"
            + f"**Disks:** {disk_names}  \n"
            + f"**Interfaces:** {iface_names}  \n"
            + "\n"
            + "---  \n"
            + "**Conditions:**  \n"
        )

        for cond in conditions:
            cond_type = cond.get("type", "Unknown")
            cond_status = cond.get("status", "Unknown")
            cond_msg = cond.get("message", "")
            cond_reason = cond.get("reason", "")
            markdown += (
                f"- **{cond_type}**: {cond_status}"
                + (f" ({cond_reason})" if cond_reason else "")
                + (f" - {cond_msg}" if cond_msg else "")
                + "  \n"
            )

        await self.query_one("#info-content", Markdown).update(markdown)


class KubevirtManager(App):
    TITLE = "KubeVirt VM Manager"
    CSS = """
    ListView {
        width: 1fr;
        height: 1fr;
    }

    .header-row {
        background: $surface;
        color: $text;
        padding: 0 2;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("s", "start_vm", "Start", priority=True),
        Binding("x", "stop_vm", "Stop", priority=True),
        Binding("p", "pause_vm", "Pause", priority=True),
        Binding("u", "unpause_vm", "Unpause", priority=True),
        Binding("r", "restart_vm", "Restart", priority=True),
        Binding("v", "vnc_connect", "VNC", priority=True),
        Binding("k", "generate_keys", "Gen SSH key pair", priority=True),
        Binding("o", "usb_redirect", "Redirect USB", priority=True),
        Binding("c", "serial_console", "Open Console", priority=True),
        Binding("l", "open_ssh", "SSH", priority=True),
        Binding("q", "cleanup_and_quit", "Quit", priority=True),
    ]

    ACTIONS = {
        VMAction.START_VM: {VMStatus.STOPPED, VMStatus.UNKNOWN},
        VMAction.STOP_VM: {VMStatus.RUNNING, VMStatus.PAUSED},
        VMAction.PAUSE_VM: {VMStatus.RUNNING},
        VMAction.UNPAUSE_VM: {VMStatus.PAUSED},
        VMAction.RESTART_VM: {VMStatus.RUNNING},
        VMAction.VNC_CONNECT: {VMStatus.RUNNING},
        VMAction.GENERATE_KEYS: None,
        VMAction.USB_REDIRECT: {VMStatus.RUNNING},
    }

    COLUMN_MAP = {
        "name": {
            "label": "Name",
            "display": lambda vm: vm.name,
        },
        "namespace": {
            "label": "Namespace",
            "display": lambda vm: vm.namespace,
        },
        "status": {
            "label": "Status",
            "display": lambda vm: vm.status.display,
        },
        "ready": {
            "label": "Ready",
            "display": lambda vm: vm.ready,
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self.vms: dict[str, VMData] = {}
        self.data_table: DataTable | None = None
        self.active_vnc: dict[str, asyncio.Task] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            with Vertical(id="vm-list-container"):
                yield DataTable(cursor_type="row", id="vm-list")
            yield VMInfoDock(id="info-dock")
        yield Footer()

    async def on_mount(self) -> None:
        self.data_table = self.query_one("#vm-list", DataTable)

        for col_key, spec in self.COLUMN_MAP.items():
            self.data_table.add_column(spec["label"], key=col_key)

        try:
            await config.load_kube_config()
        except ConfigException:
            try:
                config.load_incluster_config()
                print("configuration loaded from in-cluster service account.")
            except ConfigException as e:
                raise RuntimeError(f"could not load Kubernetes configuration: {e}")

        asyncio.create_task(self.watch_vms())

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        try:
            action_enum = VMAction[action.upper()]
        except KeyError:
            return True

        if not (vm := self.get_selected_vm()):
            return None

        if action_enum == VMAction.VNC_CONNECT and vm.uid in self.active_vnc:
            return None

        if not (valid_statuses := self.ACTIONS.get(action_enum)):
            return True

        return True if vm.status in valid_statuses else None

    async def watch_vms(self) -> None:
        assert self.data_table is not None

        def compute_row(vm: VMData):
            return [spec["display"](vm) for spec in self.COLUMN_MAP.values()]

        try:
            async with ApiClient() as api:
                v1_custom = client.CustomObjectsApi(api)
                w = watch.Watch()

                async with w.stream(
                    v1_custom.list_cluster_custom_object,
                    group="kubevirt.io",
                    version="v1",
                    plural="virtualmachines",
                    allow_watch_bookmarks=True,
                    timeout_seconds=0,
                ) as stream:
                    async for event in stream:
                        etype = event["type"]
                        if etype == "BOOKMARK":
                            continue

                        raw = cast(dict[str, Any], event["raw_object"])
                        uid = raw["metadata"]["uid"]

                        if etype == "DELETED":
                            if uid in self.vms:
                                del self.vms[uid]
                                self.data_table.remove_row(uid)
                            continue

                        new_vm = VMData.from_raw_object(raw)
                        existing_vm = self.vms.get(uid)
                        self.vms[uid] = new_vm

                        if existing_vm is None:
                            self.data_table.add_row(*compute_row(new_vm), key=uid)
                            continue

                        if existing_vm != new_vm:
                            for col_key, spec in self.COLUMN_MAP.items():
                                if getattr(existing_vm, col_key) != getattr(
                                    new_vm, col_key
                                ):
                                    self.data_table.update_cell(
                                        uid, col_key, spec["display"](new_vm)
                                    )
                            await self.query_one(
                                "#info-dock", VMInfoDock
                            ).update_vm_info(new_vm)

                        self.refresh_bindings()

        except Exception as e:
            self.notify(
                f"Error: Kubernetes watcher failed: {type(e).__name__}: {e}",
                severity="error",
                timeout=10,
            )

    async def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        self.refresh_bindings()

        info_dock = self.query_one("#info-dock", VMInfoDock)

        if not (selected_vm := self.vms.get(event.row_key.value)):
            return

        await info_dock.update_vm_info(selected_vm)

    def get_selected_vm(self) -> VMData | None:
        if not self.data_table:
            return None

        row_key, _ = self.data_table.coordinate_to_cell_key(
            self.data_table.cursor_coordinate
        )
        return self.vms[row_key.value]

    async def spawn_virtctl(self, *args) -> asyncio.subprocess.Process | None:
        try:
            return await asyncio.create_subprocess_exec(
                "virtctl",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            self.notify(
                "Error: The **virtctl** binary is not found in your system's PATH. Make sure it's installed and accessible.",
                severity="error",
            )
            return None
        except Exception as e:
            self.notify(
                f"Error: Failed to execute **virtctl** command due to an unexpected system error: {type(e).__name__} {e}",
                severity="error",
            )
            return None

    async def execute_virtctl(self, *args) -> None:
        if not (proc := await self.spawn_virtctl(*args)):
            return

        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = (
                stderr.decode().strip()
                or stdout.decode().strip()
                or f"Return code {proc.returncode}"
            )
            self.notify(
                f"Error: **virtctl** command failed (non-zero status): {msg}",
                severity="error",
            )

    async def action_start_vm(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return
        await self.execute_virtctl(
            "start", selected_vm.name, "-n", selected_vm.namespace
        )

    async def action_stop_vm(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return
        await self.execute_virtctl(
            "stop", selected_vm.name, "-n", selected_vm.namespace
        )

    async def action_pause_vm(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return
        await self.execute_virtctl(
            "pause", "vm", selected_vm.name, "-n", selected_vm.namespace
        )

    async def action_unpause_vm(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return
        await self.execute_virtctl(
            "unpause", "vm", selected_vm.name, "-n", selected_vm.namespace
        )

    async def action_restart_vm(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return
        await self.execute_virtctl(
            "restart", selected_vm.name, "-n", selected_vm.namespace
        )

    async def action_vnc_connect(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return

        self.notify(f"🔌 Opening a new VNC connection to VM '{selected_vm.name}'...")

        async def run_vnc():
            proc = None
            try:
                if not (
                    proc := await self.spawn_virtctl(
                        "vnc", selected_vm.name, "-n", selected_vm.namespace
                    )
                ):
                    return

                await proc.wait()
                self.notify(f"➜] VNC connection to '{selected_vm.name}' was closed")
            except asyncio.CancelledError:
                if proc and proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        proc.kill()
                raise
            finally:
                self.active_vnc.pop(selected_vm.uid, None)
                self.refresh_bindings()

        task = asyncio.create_task(run_vnc())
        self.active_vnc[selected_vm.uid] = task
        self.refresh_bindings()

    async def action_generate_keys(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return

        home_dir = Path.home()
        ssh_dir = home_dir / ".ssh"
        ssh_dir.mkdir(parents=True, exist_ok=True)

        key_name = f"kubevirt_{selected_vm.namespace}_{selected_vm.name}"
        key_path = ssh_dir / key_name
        pub_key_path = ssh_dir / f"{key_name}.pub"

        if not key_path.exists():
            try:
                private_key = ed25519.Ed25519PrivateKey.generate()

                private_bytes = private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.OpenSSH,
                    encryption_algorithm=serialization.NoEncryption(),
                )

                public_key = private_key.public_key()
                public_bytes = public_key.public_bytes(
                    encoding=serialization.Encoding.OpenSSH,
                    format=serialization.PublicFormat.OpenSSH,
                )

                key_path.write_bytes(private_bytes)
                key_path.chmod(0o600)

                pub_key_path.write_bytes(public_bytes)

            except Exception as e:
                self.notify(
                    f"Error: Failed to generate key pair: {e}", severity="error"
                )
                return
        else:
            self.notify(
                f"Private key **{key_name}** already exists for VM '{selected_vm.name}'. Attempting to find associated public key and display it"
            )

        try:
            if pub_key_path.exists():
                pub_key_content = pub_key_path.read_text().strip()
                self.push_screen(
                    SSHKeyDisplay(selected_vm.name, pub_key_content, str(key_path))
                )
            else:
                self.notify("Warning: Public key file not found!", severity="warning")
        except Exception as e:
            self.notify(f"Error: Failed reading public key: {e}", severity="error")

    @work
    async def action_usb_redirect(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return

        if not (device_id := await self.push_screen_wait(USBRedirectSelection())):
            self.notify("✘ USB redirection cancelled.")
            return

        self.notify(
            f"↪ Redirecting USB device '{device_id}' to VM '{selected_vm.name}'..."
        )
        await self.execute_virtctl(
            "usbredir",
            device_id,
            f"vm/{selected_vm.name}",
            "-n",
            selected_vm.namespace,
        )

    def action_serial_console(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return

        with self.suspend():
            try:
                cmd = [
                    "virtctl",
                    "console",
                    selected_vm.name,
                    "-n",
                    selected_vm.namespace,
                ]
                subprocess.run(cmd)
            except Exception as e:
                print(f"Error launching serial console: {e}")
                input("Press Enter to return to KubevirtManager...")

    def action_open_ssh(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return

        home_dir = Path.home()
        key_name = f"kubevirt_{selected_vm.namespace}_{selected_vm.name}"
        key_path = home_dir / ".ssh" / key_name

        ssh_user = os.environ.get("KUBEVIRT_SSH_USER", "vscode")

        cmd = [
            "virtctl",
            "ssh",
            "-n",
            selected_vm.namespace,
            f"{ssh_user}@vm/{selected_vm.name}",
        ]

        if key_path.exists():
            cmd.extend(["-i", str(key_path)])

        self.notify(
            f"🔌 Connecting via SSH to {selected_vm.name} as user '{ssh_user}'..."
        )

        with self.suspend():
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, check=False
                )

                if result.returncode == 0:
                    print(
                        f"✓ SSH session with {selected_vm.name} terminated successfully."
                    )

                elif result.returncode == 255:
                    print("❌ SSH Connection Refused or Failed (Exit 255)")
                    print("--- Error Details ---")
                    print(result.stderr)

                elif result.returncode != 0:
                    print(f"❌ SSH Command Failed (Exit {result.returncode})")
                    print("--- Error Details ---")
                    print(result.stderr)

                input("\nPress Enter to return to Manager...")

            except FileNotFoundError:
                print(
                    "\n❌ Error: 'virtctl' binary not found. Press Enter to continue..."
                )
                input()
            except Exception as e:
                print(f"\n❌ Unexpected System Error: {e}. Press Enter to continue...")
                input()

        self.notify(f"✓ SSH session with {selected_vm.name} terminated.")

    async def action_cleanup_and_quit(self) -> None:
        for task in self.active_vnc.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.active_vnc.values(), return_exceptions=True)
        self.exit()


if __name__ == "__main__":
    app = KubevirtManager()
    app.run()
