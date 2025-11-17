#!/usr/bin/env python3
import json
import yaml
import subprocess
import sys
import os

from textual.app import App, ComposeResult
from textual.widgets import (
    Header,
    Footer,
    ListView,
    ListItem,
    Label,
    Static,
    Input,
    Button,
)
from textual.containers import Vertical, Horizontal


def run_cmd(cmd):
    try:
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        print(f"❌ Command failed: {' '.join(cmd)}")
        sys.exit(1)


def load_tasks():
    """Returns a list of (task_name, description)."""
    raw = run_cmd(["task", "--list", "--json"])
    data = json.loads(raw)
    return [(t["name"], t["desc"]) for t in data.get("tasks", [])]


def load_taskfile_and_vars(task_name):
    """Return (list_of_required_vars, canonical_taskfile_path)."""
    parts = task_name.split(":")

    # Base Taskfile.yaml
    if len(parts) == 1:
        included_file = "Taskfile.yaml"
        key = parts[0]
    else:
        namespace, key = parts
        with open("Taskfile.yaml") as f:
            root = yaml.safe_load(f)
        included_dir = root["includes"].get(namespace)
        included_file = os.path.join(included_dir, "Taskfile.yaml")

    with open(included_file) as f:
        included_taskfile = yaml.safe_load(f)

    vars_list = (
        included_taskfile.get("tasks", {})
        .get(key, {})
        .get("requires", {})
        .get("vars", [])
        or []
    )

    return vars_list, included_file, key


class TaskItem(ListItem):
    def __init__(self, name, desc):
        super().__init__(Label(f"{name:30} {desc}"))
        self.task_name = name
        self.description = desc


class TaskRunnerApp(App):
    TITLE = "Task Runner"

    CSS = """
    ListView {
        height: 1fr;
        width: 100%;
    }

    #prompt-box {
        border: solid green;
        padding: 2;
        width: 50%;
        height: auto;
    }
    """

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks
        self.selected_task_name = None
        self.required_vars = []
        self.var_values = {}
        self.var_index = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Select a task (Enter to run)", classes="title")
        yield ListView(
            *[TaskItem(name, desc) for name, desc in self.tasks],
            id="task-list",
        )
        yield Footer()

    async def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        self.selected_task_name = item.task_name

        # Load required vars
        self.required_vars, _, _ = load_taskfile_and_vars(
            self.selected_task_name
        )

        # If variables required → prompt user
        if self.required_vars:
            await self.ask_next_var()
        else:
            await self.action_quit()

    async def ask_next_var(self):
        """Show a modal input box for the next var."""
        if self.var_index >= len(self.required_vars):
            await self.action_quit()
            return

        var_name = self.required_vars[self.var_index]

        self.query_one("#task-list").display = False

        # Build popup
        box = Vertical(
            Static(f"Enter value for: [b]{var_name}[/b]"),
            Input(id="var-input"),
            Button("OK", id="ok-button"),
            id="prompt-box",
        )
        self.mount(box)

        self.set_focus("#var-input")

    async def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "ok-button":
            inputbox = self.query_one("#var-input", Input)
            value = inputbox.value.strip()
            if value:
                var_name = self.required_vars[self.var_index]
                self.var_values[var_name] = value
                self.var_index += 1

                # Remove popup
                prompt = self.query_one("#prompt-box")
                prompt.remove()

                # Restore list (if more vars left)
                if self.var_index < len(self.required_vars):
                    self.query_one("#task-list").display = True
                    await self.ask_next_var()
                else:
                    await self.action_quit()
            else:
                # re-focus input if empty
                self.set_focus("#var-input")


def main():
    tasks = load_tasks()
    if not tasks:
        print("❌ No tasks found.")
        sys.exit(0)

    app = TaskRunnerApp(tasks)
    app.run()

    # After Textual exits:
    if not app.selected_task_name:
        print("❌ No task selected.")
        sys.exit(1)

    # Build command
    cmd = ["task", app.selected_task_name]
    for k, v in app.var_values.items():
        cmd.append(f"{k}={v}")

    print(f"➡️ Running: {' '.join(cmd)}")
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
