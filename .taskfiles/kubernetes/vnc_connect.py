#!/usr/bin/env python3
import json
import subprocess
import sys

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, ListView, ListItem, Label
from textual.containers import Vertical


def run_cmd(cmd):
    """Run a shell command and return stdout, raise on error."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {' '.join(cmd)}")
        print(e.stderr)
        sys.exit(1)


def list_running_vms():
    raw = run_cmd(["kubectl", "get", "vms", "--all-namespaces", "-o", "json"])
    data = json.loads(raw)

    vms = []
    for item in data.get("items", []):
        status = item.get("status", {}).get("printableStatus")
        if status == "Running":
            ns = item["metadata"]["namespace"]
            name = item["metadata"]["name"]
            vms.append((ns, name))

    return vms


class VMListItem(ListItem):
    def __init__(self, namespace: str, name: str):
        super().__init__(Label(f"{namespace:20} {name}"))
        self.namespace = namespace
        self.name = name


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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Select a running VM (Enter to connect)", classes="title")
        yield ListView(
            *[VMListItem(ns, name) for ns, name in self.vms],
            id="vm-list"
        )
        yield Footer()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Triggered when user presses Enter on a list item."""
        item = event.item
        namespace = item.namespace
        name = item.name

        await self.action_quit()

        print(f"🔌 Connecting to VMI {name} in namespace {namespace}...")

        try:
            exit_code = subprocess.call(["virtctl", "vnc", name, "-n", namespace])
        except FileNotFoundError:
            print("❌ virtctl not found in PATH.")
            sys.exit(1)

        if exit_code != 0:
            print(f"❌ virtctl command failed with exit code {exit_code}")

        sys.exit(exit_code)


def main():
    vms = list_running_vms()
    if not vms:
        print("❌ No running VMs found.")
        sys.exit(0)

    app = VMSelectorApp(vms)
    app.run()


if __name__ == "__main__":
    main()
