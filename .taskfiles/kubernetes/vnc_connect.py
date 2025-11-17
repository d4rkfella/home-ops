#!/usr/bin/env python3
import sys
import kubevirt
from kubevirt.rest import ApiException
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, ListView, ListItem, Label


def list_running_vms():
    """Return a list of (namespace, name) tuples of running VMs using kubevirt API."""
    api_instance = kubevirt.DefaultApi()

    try:
        # List VMs across all namespaces
        all_vms = api_instance.list_virtual_machine_for_all_namespaces()
    except ApiException as e:
        print(f"❌ Failed to fetch VMs: {e}", file=sys.stderr)
        sys.exit(1)

    vms = []
    for item in all_vms.items:
        status = getattr(item.status, "printableStatus", None)
        if status == "Running":
            ns = item.metadata.namespace
            name = item.metadata.name
            vms.append((ns, name))
    return vms


class VMListItem(ListItem):
    """ListItem storing VM metadata."""

    def __init__(self, namespace: str, name: str):
        super().__init__(Label(f"{namespace:20} {name}"))
        self.namespace = namespace
        self.vm_name = name


class VMSelectorApp(App):
    TITLE = "VM Selector"
    CSS = """
    ListView {
        width: 100%;
        height: 1fr;
    }
    """

    def __init__(self, vms):
        super().__init__()
        self.vms = vms
        self.selected_vm = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Select a running VM (Enter to connect)", classes="title")
        yield ListView(*[VMListItem(ns, name) for ns, name in self.vms], id="vm-list")
        yield Footer()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        self.selected_vm = (item.namespace, item.vm_name)
        await self.action_quit()


def connect_vnc(vm_name: str, namespace: str, preserve_session: bool = True):
    """Open a VNC connection to a VMI using kubevirt Python client."""
    api_instance = kubevirt.DefaultApi()

    try:
        api_instance.v1_vnc(name=vm_name, namespace=namespace, preserve_session=preserve_session)
        print(f"🔌 Connected to VMI {vm_name} in namespace {namespace} (VNC)")
    except ApiException as e:
        print(f"❌ Failed to connect to VNC: {e}")
        sys.exit(1)


def main():
    vms = list_running_vms()
    if not vms:
        print("❌ No running VMs found.")
        sys.exit(0)

    app = VMSelectorApp(vms)
    app.run()  # blocks until TUI exits

    if app.selected_vm:
        namespace, vm_name = app.selected_vm
        connect_vnc(vm_name, namespace)
        sys.exit(0)

    print("❌ Selection cancelled.")
    sys.exit(1)


if __name__ == "__main__":
    main()
