#!/usr/bin/env python3
import json
from typing import cast
import yaml
import subprocess
import sys
import os

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
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
from textual.containers import Container
from textual.screen import ModalScreen


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
    raw = run_cmd(["task", "--list", "--json"])
    data = json.loads(raw)
    return [(t["name"], t["desc"]) for t in data.get("tasks", [])]


def load_taskfile_and_vars(task_name):
    parts = task_name.split(":")

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


class VarInputScreen(ModalScreen[dict[str, str] | None]):

    CSS = """
    VarInputScreen {
        align: center middle;
    }

    #dialog {
        width: 60;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }

    #title {
        text-align: center;
        padding: 1;
        text-style: bold;
    }

    .var-row {
        height: auto;
        margin: 1 0;
    }

    .var-label {
        padding: 0 0 0 1;
        width: 100%;
    }

    Input {
        margin: 0 0 1 0;
    }

    #buttons {
        layout: horizontal;
        align: center middle;
        height: auto;
        margin-top: 1;
    }

    Button {
        margin: 0 1;
    }
    """

    def __init__(self, var_names: list[str]):
        super().__init__()
        self.var_names = var_names

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static("Enter values for required variables:", id="title")

            for var_name in self.var_names:
                with Container(classes="var-row"):
                    yield Static(f"[b]{var_name}[/b]:", classes="var-label")
                    yield Input(placeholder=f"Value for {var_name}", id=f"input-{var_name}")

            with Container(id="buttons"):
                yield Button("OK", variant="primary", id="ok-button", disabled=True)
                yield Button("Cancel", variant="default", id="cancel-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok-button":
            values = {}
            all_filled = True

            for var_name in self.var_names:
                input_widget = self.query_one(f"#input-{var_name}", Input)
                value = input_widget.value.strip()
                if not value:
                    all_filled = False
                    input_widget.focus()
                    break
                values[var_name] = value

            if all_filled:
                self.dismiss(values)
        elif event.button.id == "cancel-button":
            self.dismiss(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        all_filled = all(
            self.query_one(f"#input-{var_name}", Input).value.strip()
            for var_name in self.var_names
        )
        self.query_one("#ok-button", Button).disabled = not all_filled

    def on_input_submitted(self, event: Input.Submitted) -> None:
        current_id = event.input.id
        if not current_id:
            return

        current_var = current_id.replace("input-", "")
        current_index = self.var_names.index(current_var)

        if current_index < len(self.var_names) - 1:
            next_var = self.var_names[current_index + 1]
            self.query_one(f"#input-{next_var}", Input).focus()
        else:
            self.query_one("#ok-button", Button).press()


class TaskSelectionApp(App):
    TITLE = "Task Selection Menu"

    CSS = """
    ListView {
        height: 1fr;
        width: 100%;
    }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
    ]

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks
        self.selected_task_name = None
        self.required_vars = []
        self.var_values = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield ListView(
            *[TaskItem(name, desc) for name, desc in self.tasks],
            id="task-list",
        )
        yield Footer()

    @work
    async def on_list_view_selected(self, event: ListView.Selected):
        item = cast(TaskItem, event.item)
        self.selected_task_name = item.task_name

        self.required_vars, _, _ = load_taskfile_and_vars(
            self.selected_task_name
        )

        if self.required_vars:
            if result := await self.push_screen_wait(VarInputScreen(self.required_vars)):
                self.var_values = result
                await self.action_quit()
            else:
                self.selected_task_name = None
        else:
            await self.action_quit()

def main():
    tasks = load_tasks()
    if not tasks:
        print("❌ No tasks found.")
        sys.exit(0)

    app = TaskSelectionApp(tasks)
    app.run()

    if not app.selected_task_name:
        print("❌ Task selection cancelled.")
        sys.exit(0)

    cmd = ["task", app.selected_task_name]
    for k, v in app.var_values.items():
        cmd.append(f"{k}={v}")

    print(f"Running {' '.join(cmd)}")
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
