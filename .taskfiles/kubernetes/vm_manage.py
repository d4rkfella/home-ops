#!/usr/bin/env python3
import asyncio
from typing import cast

from kubernetes_asyncio import client, config, watch
from kubernetes_asyncio.client.api_client import ApiClient
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

STATUS_EMOJI: dict[str, str] = {
    "running": "🟢",
    "stopped": "🔴",
    "paused": "🟡",
    "stopping": "🟠",
    "starting": "🔵",
    "unknown": "⚪",
}


class VMListItem(ListItem):
    def __init__(self, namespace: str, name: str, status: str):
        emoji = STATUS_EMOJI.get(status.lower(), "⚪")
        super().__init__(Label(f"{emoji} {name:25} {namespace:20} {status}"))
        self.namespace = namespace
        self.vm_name = name
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
        Binding("q", "cleanup_and_quit", "Quit", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.vms: dict[tuple[str, str], str] = {}
        self.list_view: ListView | None = None
        self.actions_display: Static | None = None
        self.active_vnc: dict[tuple[str, str], asyncio.Task] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" {'Name':25} {'Namespace':20} Status", classes="header-row")
        yield ListView(id="vm-list")
        yield Footer()

    async def on_mount(self) -> None:
        self.list_view = self.query_one("#vm-list", ListView)

        try:
            await config.load_kube_config()
        except:
            config.load_incluster_config()

        asyncio.create_task(self.watch_vms())

    def get_available_actions(self, status: str) -> dict[str, bool]:
        status = status.lower()

        base = {
            "start": status in ["stopped", "unknown"],
            "stop": status in ["running", "paused"],
            "pause": status == "running",
            "unpause": status == "paused",
            "restart": status == "running",
            "vnc": status == "running",
        }

        vm_info = self.get_selected_vm()
        if vm_info:
            namespace, name, _ = vm_info
            if (namespace, name) in self.active_vnc:
                base["vnc"] = False

        return base

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Check if an action may run based on the selected VM's status."""
        if action == "cleanup_and_quit":
            return True

        vm_info = self.get_selected_vm()
        if not vm_info:
            return None

        _, _, status = vm_info
        actions = self.get_available_actions(status)

        action_map = {
            "start_vm": "start",
            "stop_vm": "stop",
            "pause_vm": "pause",
            "unpause_vm": "unpause",
            "restart_vm": "restart",
            "vnc_connect": "vnc",
        }

        if action in action_map:
            is_available = actions.get(action_map[action], False)
            return None if not is_available else True

        return True

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
                                        and vm_item.vm_name == name
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
                                if vm_item.namespace == ns and vm_item.vm_name == name:
                                    await self.list_view.pop(i)
                                    break

        except Exception as e:
            self.notify(
                f"💥 Watcher crashed: {type(e).__name__}: {e} ", severity="error"
            )

    async def on_list_view_highlighted(self) -> None:
        self.refresh_bindings()

    def get_selected_vm(self) -> tuple[str, str, str] | None:
        if not self.list_view or self.list_view.index is None:
            return None
        try:
            item = cast(VMListItem, self.list_view.highlighted_child)
            return (item.namespace, item.vm_name, item.status)
        except:
            return None

    async def execute_virtctl(self, command: list[str], success_msg: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                msg = (
                    stderr.decode().strip()
                    or stdout.decode().strip()
                    or f"Return code {proc.returncode}"
                )
                self.notify(f"❌ Command failed: {msg}", severity="error")
            else:
                self.notify(success_msg)
        except FileNotFoundError:
            self.notify("❌ virtctl not found in PATH.", severity="error")
        except Exception as e:
            self.notify(f"❌ Error: {e}", severity="error")

    async def action_start_vm(self) -> None:
        vm_info = self.get_selected_vm()
        if not vm_info:
            return

        namespace, name, _ = vm_info
        self.notify(f"🚀 Starting VM {name}...")
        await self.execute_virtctl(
            ["virtctl", "start", name, "-n", namespace],
            f"✅ VM {name} start command sent",
        )

    async def action_stop_vm(self) -> None:
        vm_info = self.get_selected_vm()
        if not vm_info:
            return

        namespace, name, _ = vm_info
        self.notify(f"🛑 Stopping VM {name}...")
        await self.execute_virtctl(
            ["virtctl", "stop", name, "-n", namespace],
            f"✅ VM {name} stop command sent",
        )

    async def action_pause_vm(self) -> None:
        vm_info = self.get_selected_vm()
        if not vm_info:
            return

        namespace, name, _ = vm_info
        self.notify(f"⏸️ Pausing VM {name}...")
        await self.execute_virtctl(
            ["virtctl", "pause", "vm", name, "-n", namespace], f"✅ VM {name} paused"
        )

    async def action_unpause_vm(self) -> None:
        vm_info = self.get_selected_vm()
        if not vm_info:
            return

        namespace, name, _ = vm_info
        self.notify(f"▶️ Unpausing VM {name}...")
        await self.execute_virtctl(
            ["virtctl", "unpause", "vm", name, "-n", namespace],
            f"✅ VM {name} unpaused",
        )

    async def action_restart_vm(self) -> None:
        vm_info = self.get_selected_vm()
        if not vm_info:
            return

        namespace, name, _ = vm_info
        self.notify(f"🔄 Restarting VM {name}...")
        await self.execute_virtctl(
            ["virtctl", "restart", name, "-n", namespace],
            f"✅ VM {name} restart command sent",
        )

    async def action_vnc_connect(self) -> None:
        vm_info = self.get_selected_vm()
        if not vm_info:
            return

        namespace, name, _ = vm_info
        key = (namespace, name)

        if key in self.active_vnc:
            self.notify(f"⚠️ VNC for {name} is already running.")
            return

        self.notify(f"🔌 Connecting to VNC for {name}...")

        async def run_vnc() -> None:
            proc: asyncio.subprocess.Process | None = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    "virtctl",
                    "vnc",
                    name,
                    "-n",
                    namespace,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                self.notify(f"✅ VNC session for {name} closed")
            except asyncio.CancelledError:
                if proc and proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                raise
            finally:
                del self.active_vnc[key]
                if self.screen_stack:
                    self.refresh_bindings()

        task = asyncio.create_task(run_vnc())
        self.active_vnc[key] = task

        self.refresh_bindings()

    async def action_cleanup_and_quit(self) -> None:
        for task in self.active_vnc.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.active_vnc.values(), return_exceptions=True)
        self.exit()


if __name__ == "__main__":
    app = VMManagerApp()
    app.run()
