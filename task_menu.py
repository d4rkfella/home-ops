#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from typing import cast

import yaml
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)


class TaskItem(ListItem):
    def __init__(
        self,
        name: str,
        desc: str,
        interactive: bool = False,
        taskfile: str = "",
        required_vars: list[str] | None = None,
    ) -> None:
        display_text = f"{name:40} {desc}"
        if interactive:
            display_text += " ⚡"
        super().__init__(Label(display_text))

        self.task_name = name
        self.description = desc
        self.interactive = interactive
        self.taskfile = taskfile
        self.required_vars = required_vars


def run_cmd(cmd) -> str:
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        print(f"❌ Command failed: {' '.join(cmd)}")
        sys.exit(1)


def load_tasks() -> list[TaskItem]:
    raw = run_cmd(["task", "--list", "--json"])
    data = json.loads(raw)

    tasks = []
    for t in data.get("tasks", []):
        name = t["name"]
        desc = t["desc"]
        taskfile_path = t.get("location", {}).get("taskfile", "")
        interactive = False
        required_vars: list[str] | None = None

        if taskfile_path and os.path.exists(taskfile_path):
            with open(taskfile_path) as f:
                taskfile_data = yaml.safe_load(f)
                task_key = t["task"].split(":")[-1]
                task_def = taskfile_data.get("tasks", {}).get(task_key, {})
                interactive = bool(task_def.get("interactive", False))
                required_vars = task_def.get("requires", {}).get("vars", []) or None

        tasks.append(TaskItem(name, desc, interactive, taskfile_path, required_vars))

    return tasks


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
                    yield Input(
                        placeholder=f"Value for {var_name}", id=f"input-{var_name}"
                    )

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


class TaskSelection(App):
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

    def __init__(self):
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header()
        yield ListView(id="task-list")
        yield Footer()

    @work
    async def on_mount(self):
        list_view = self.query_one("#task-list", ListView)

        if tasks := load_tasks():
            for item in tasks:
                list_view.append(item)

    @work
    async def on_list_view_selected(self, event: ListView.Selected):
        item = cast(TaskItem, event.item)
        cmd = ["task", item.task_name]

        var_values = None
        if item.required_vars:
            if not (
                var_values := await self.push_screen_wait(
                    VarInputScreen(item.required_vars)
                )
            ):
                return
            for k, v in var_values.items():
                cmd.append(f"{k}={v}")

        with self.suspend():
            print(f"Running: {' '.join(cmd)}")
            subprocess.run(cmd)


def main():
    app = TaskSelection()
    app.run()


if __name__ == "__main__":
    main()
