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


def run_cmd(cmd) -> str:
    try:
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        print(f"❌ Command failed: {' '.join(cmd)}")
        sys.exit(1)


def load_tasks() -> list[tuple[str, str]]:
    raw = run_cmd(["task", "--list", "--json"])
    data = json.loads(raw)
    return [(t["name"], t["desc"]) for t in data.get("tasks", [])]


def get_required_vars(task_name) -> list[str] | None:
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

    required_vars = (
        included_taskfile.get("tasks", {})
        .get(key, {})
        .get("requires", {})
        .get("vars", [])
        or None
    )

    return required_vars


class TaskItem(ListItem):
    def __init__(self, name: str, desc: str) -> None:
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

    def __init__(self, var_names: list[str]) -> None:
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

            for var_name in self.var_names:
                input_widget = self.query_one(f"#input-{var_name}", Input)
                value = input_widget.value.strip()
                values[var_name] = value
            self.dismiss(values)
        elif event.button.id == "cancel-button":
            self.dismiss(None)

    def on_input_changed(self) -> None:
        all_filled = all(
            self.query_one(f"#input-{var_name}", Input).value.strip()
            for var_name in self.var_names
        )
        self.query_one("#ok-button", Button).disabled = not all_filled

    def on_input_submitted(self, event: Input.Submitted) -> None:
        input_widget = event.input
        if not input_widget.id or not input_widget.value.strip():
            return

        var_name = input_widget.id.replace("input-", "")
        var_index = self.var_names.index(var_name)

        if var_index < len(self.var_names) - 1:
            next_var = self.var_names[var_index + 1]
            self.query_one(f"#input-{next_var}", Input).focus()
        else:
            self.query_one("#ok-button", Button).press()


class TaskSelectionApp(App[tuple[str, dict[str, str] | None] | None]):
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

        if required_vars := get_required_vars(item.task_name):
            if result := await self.push_screen_wait(VarInputScreen(required_vars)):
                self.exit((item.task_name, result))
        else:
            self.exit((item.task_name, None))

def main():
    tasks = load_tasks()
    if not tasks:
        print("❌ No tasks found.")
        sys.exit(0)

    app = TaskSelectionApp(tasks)
    result = app.run()
    if result is None:
        sys.exit(0)

    task_name, var_values = result

    cmd = ["task", task_name]
    if var_values:
        for k, v in var_values.items():
            cmd.append(f"{k}={v}")

    print(f"Running {' '.join(cmd)}")
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
