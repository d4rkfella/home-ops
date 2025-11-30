#!/usr/bin/env python3
import asyncio
from typing import cast
from pathlib import Path
from collections.abc import Iterable
import pyudev
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from kubernetes_asyncio import client, config, watch
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.config import ConfigException
from textual.app import App, ComposeResult
from textual import work
from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.binding import Binding
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static, Button, TextArea

STATUS_EMOJI: dict[str, str] = {
    "running": "🟢",
    "stopped": "🔴",
    "paused": "🟡",
    "stopping": "🟠",
    "starting": "🔵",
    "unknown": "⚪",
}


class USBDeviceItem(ListItem):
    """List item for a selectable USB device."""
    def __init__(self, device_id: str, description: str):
        super().__init__(Label(f"🔌 {description}"))
        self.device_id = device_id
        self.description = description


class USBRedirScreen(ModalScreen[str]): # Screen returns the device_id string
    """Modal screen to select an attached USB device for redirection."""

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
        """Dismisses the screen, returning None to the parent app."""
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical(id="usb-dialog"):
            yield ListView(id="usb-list")
            yield Static("Use the arrow keys to select, then press ENTER to redirect.")

    async def on_mount(self) -> None:
        await self.load_usb_devices()

    def get_udev_devices(self) -> Iterable[pyudev.Device]:
        """Synchronous function to query pyudev for USB devices."""
        context = pyudev.Context()
        for device in context.list_devices(subsystem='usb'):
            if device.device_type == 'usb_device':
                yield device

    async def load_usb_devices(self) -> None:
        """Loads USB devices using pyudev and populates the list view."""
        list_view = self.query_one("#usb-list", ListView)

        try:
            # Accessing self.app for notification, as it is automatically available
            usb_devices = await asyncio.to_thread(self.get_udev_devices)

            items = []

            for device in usb_devices:
                vendor_id = device.get('ID_VENDOR_ID')
                product_id = device.get('ID_MODEL_ID')
                description = device.get('ID_MODEL', 'Unknown Device')

                if vendor_id and product_id:
                    device_id = f"{vendor_id}:{product_id}"
                    item = USBDeviceItem(device_id, f"{description} ({device_id})")
                    items.append(item)

            if not items:
                self.app.notify("No USB devices found.", severity="warning")

            await list_view.extend(items)

        except ImportError:
            self.app.notify("pyudev not found. Run 'pip install pyudev'.", severity="error")
            self.dismiss(None)
        except Exception as e:
            self.app.notify(f"Error loading USB devices: {type(e).__name__} {e}", severity="error")
            self.dismiss(None)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handles selection of a USB device and dismisses, returning the ID."""
        selected_item = cast(USBDeviceItem, event.item)
        self.dismiss(selected_item.device_id)

class SSHKeyDisplay(ModalScreen):
    """A modal screen to display the generated SSH public key."""

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

            text_area = TextArea(self.pub_key, id="pub-key-area", read_only=True)
            text_area.show_line_numbers = False
            yield text_area

            with Horizontal():
                yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss()


class VMListItem(ListItem):
    def __init__(self, namespace: str, name: str, status: str):
        emoji = STATUS_EMOJI.get(status.lower(), "⚪")
        super().__init__(Label(f"{emoji} {name:25} {namespace:20} {status}"))
        self.namespace = namespace
        self.rname = name
        self.status = status.lower()


class VMManagerApp(App):
    TITLE = "KubeVirt VM Manager"
    CSS = """
    ListView {
        width: 100%;
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
        Binding("k", "generate_keys", "Gen SSH Key", priority=True),
        Binding("o", "usb_redirect", "Redirect USB", priority=True),
        Binding("q", "cleanup_and_quit", "Quit", priority=True),
    ]

    ACTIONS = {
        "start_vm": {"stopped", "unknown"},
        "stop_vm": {"running", "paused"},
        "pause_vm": {"running"},
        "unpause_vm": {"paused"},
        "restart_vm": {"running"},
        "vnc_connect": {"running"},
        "generate_keys": None,
        "usb_redirect": {"running"},
    }

    def __init__(self) -> None:
        super().__init__()
        self.vms: dict[tuple[str, str], str] = {}
        self.list_view: ListView | None = None
        self.active_vnc: dict[VMListItem, asyncio.Task] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" {'Name':25} {'Namespace':20} Status", classes="header-row")
        yield ListView(id="vm-list")
        yield Footer()

    async def on_mount(self) -> None:
        self.list_view = self.query_one("#vm-list", ListView)

        try:
            await config.load_kube_config()
            print("configuration loaded from kubeconfig.")
        except ConfigException:
            try:
                config.load_incluster_config()
                print("configuration loaded from in-cluster service account.")
            except ConfigException as e:
                raise RuntimeError(f"could not load Kubernetes configuration: {e}")

        asyncio.create_task(self.watch_vms())

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if not (valid_statuses := self.ACTIONS.get(action)):
            return True

        if not (selected_vm := self.get_selected_vm()):
            return None

        if action == "vnc_connect" and selected_vm in self.active_vnc:
            return None

        return True if selected_vm.status.lower() in valid_statuses else None

    async def watch_vms(self) -> None:
        assert self.list_view is not None
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
                        obj: dict = event["raw_object"]

                        if event["type"] == "BOOKMARK":
                            continue
                        ns = obj["metadata"]["namespace"]
                        name = obj["metadata"]["name"]
                        status = obj.get("status", {}).get("printableStatus", "Unknown")

                        key = (ns, name)

                        if event["type"] in ["ADDED", "MODIFIED"]:
                            if key not in self.vms:
                                self.vms[key] = status
                                await self.list_view.append(
                                    VMListItem(ns, name, status)
                                )
                            elif self.vms[key] != status:
                                self.vms[key] = status

                                for item in self.list_view.children:
                                    vm_item = cast(VMListItem, item)
                                    if (
                                        vm_item.namespace == ns
                                        and vm_item.rname == name
                                    ):
                                        emoji = STATUS_EMOJI.get(status.lower(), "⚪")
                                        label = cast(Label, vm_item.children[0])
                                        label.update(
                                            f"{emoji} {name:25} {ns:20} {status}"
                                        )
                                        vm_item.status = status.lower()
                                        self.refresh_bindings()
                                        break

                        elif event["type"] == "DELETED" and key in self.vms:
                            del self.vms[key]
                            for i, item in enumerate(self.list_view.children):
                                vm_item = cast(VMListItem, item)
                                if vm_item.namespace == ns and vm_item.rname == name:
                                    await self.list_view.pop(i)
                                    break

        except Exception as e:
            self.notify(
                f"💥 Watcher crashed: {type(e).__name__}: {e} ",
                severity="error",
                timeout=10,
            )

    def on_list_view_highlighted(self) -> None:
        self.refresh_bindings()

    def get_selected_vm(self) -> VMListItem | None:
        if not self.list_view or not (
            item := cast(VMListItem, self.list_view.highlighted_child)
        ):
            return None
        return item

    async def spawn_virtctl(self, *args) -> asyncio.subprocess.Process | None:
        try:
            return await asyncio.create_subprocess_exec(
                "virtctl",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            self.notify("virtctl not found in PATH.", severity="error")
            return None
        except Exception as e:
            self.notify(f"error running virtctl: {e}", severity="error")
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
            self.notify(f"command failed: {msg}", severity="error")
        else:
            self.notify("command sent successfully")

    async def action_start_vm(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return
        await self.execute_virtctl("start", selected_vm.rname, "-n", selected_vm.namespace)

    async def action_stop_vm(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return
        await self.execute_virtctl("stop", selected_vm.rname, "-n", selected_vm.namespace)

    async def action_pause_vm(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return
        await self.execute_virtctl(
            "pause", "vm", selected_vm.rname, "-n", selected_vm.namespace
        )

    async def action_unpause_vm(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return
        await self.execute_virtctl(
            "unpause", "vm", selected_vm.rname, "-n", selected_vm.namespace
        )

    async def action_restart_vm(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return
        await self.execute_virtctl("restart", selected_vm.rname, "-n", selected_vm.namespace)

    async def action_vnc_connect(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return

        self.notify(f"🔌 Connecting to VNC for {selected_vm.rname}...")

        async def run_vnc():
            proc = None
            try:
                if not (proc := await self.spawn_virtctl(
                    "vnc", selected_vm.rname, "-n", selected_vm.namespace
                )):
                    return

                await proc.wait()
                self.notify(f"✅ VNC session for {selected_vm.rname} closed")
            except asyncio.CancelledError:
                if proc and proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        proc.kill()
                raise
            finally:
                self.active_vnc.pop(selected_vm, None)
                self.refresh_bindings()

        task = asyncio.create_task(run_vnc())
        self.active_vnc[selected_vm] = task
        self.refresh_bindings()

    async def action_generate_keys(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return

        home_dir = Path.home()
        ssh_dir = home_dir / ".ssh"
        ssh_dir.mkdir(parents=True, exist_ok=True)

        key_name = f"kubevirt_{selected_vm.namespace}_{selected_vm.rname}"
        key_path = ssh_dir / key_name
        pub_key_path = ssh_dir / f"{key_name}.pub"

        if not key_path.exists():
            self.notify(f"Generating SSH key for {selected_vm.rname}...")

            try:
                private_key = ed25519.Ed25519PrivateKey.generate()

                private_bytes = private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.OpenSSH,
                    encryption_algorithm=serialization.NoEncryption()
                )

                public_key = private_key.public_key()
                public_bytes = public_key.public_bytes(
                    encoding=serialization.Encoding.OpenSSH,
                    format=serialization.PublicFormat.OpenSSH
                )

                key_path.write_bytes(private_bytes)
                key_path.chmod(0o600)

                pub_key_path.write_bytes(public_bytes)

            except Exception as e:
                self.notify(f"Crypto Error: {e}", severity="error")
                return
        else:
            self.notify(f"SSH key already exists for {selected_vm.rname}")

        try:
            if pub_key_path.exists():
                pub_key_content = pub_key_path.read_text().strip()
                self.push_screen(SSHKeyDisplay(selected_vm.rname, pub_key_content, str(key_path)))
            else:
                self.notify("Public key file not found!", severity="error")
        except Exception as e:
            self.notify(f"Error reading public key: {e}", severity="error")

    @work
    async def action_usb_redirect(self) -> None:
        if not (selected_vm := self.get_selected_vm()):
            return

        if not (device_id := await self.push_screen_wait(USBRedirScreen())):
            self.notify("USB redirection cancelled.")
            return

        self.notify(f"Redirecting device {device_id} to {selected_vm.rname}...")
        await self.execute_virtctl(
            "usbredir",
            device_id,
            f"vm/{selected_vm.rname}",
            "-n", selected_vm.namespace
        )

    async def action_cleanup_and_quit(self) -> None:
        for task in self.active_vnc.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.active_vnc.values(), return_exceptions=True)
        self.exit()


if __name__ == "__main__":
    app = VMManagerApp()
    app.run()
