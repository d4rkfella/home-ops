#!/usr/bin/env python3
import asyncio
import json
import os
import signal
import subprocess
from datetime import datetime
from typing import cast

import yaml
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
)

# ===================== THEME =====================

task_theme = Theme(
    name="task-theme",
    primary="#FF8065",
    secondary="#54C5CD",
    dark=True,
)

# ===================== WIDGETS =====================

class SearchInput(Input):
    app: "TaskSelection"
    BINDINGS = [
        Binding("ctrl+n", "next_match", "Next", show=True),
        Binding("ctrl+p", "prev_match", "Previous", show=True),
    ]

    def action_next_match(self) -> None:
        self.app.action_next_search()

    def action_prev_match(self) -> None:
        self.app.action_prev_search()



class TaskItem(ListItem):
    def __init__(
        self,
        name: str,
        desc: str,
        interactive: bool = False,
        taskfile: str = "",
        required_vars: list[str] | None = None,
        prompt: str | None = None,
        commands: list[str] | None = None,
        vars: list[str] | None = None,
        env: list[str] | None = None,
    ) -> None:
        display_text = f"{name}"
        if interactive:
            display_text += " ⚡"
        if prompt:
            display_text += " 💬"
        super().__init__(Label(display_text))

        self.task_name = name
        self.description = desc
        self.interactive = interactive
        self.taskfile = taskfile
        self.required_vars = required_vars
        self.prompt = prompt
        self.commands = commands or []
        self.vars = vars or []
        self.env = env or []


class TaskInfoPanel(VerticalScroll):
    DEFAULT_CSS = """
    TaskInfoPanel {
        width: 35%;
        height: 100%;
        border: $primary;
        background: $surface;
        border-title-align: center;
    }
    .info-grid {
        layout: grid;
        grid-size: 2;
        grid-columns: auto 1fr;
        grid-rows: auto;
        grid-gutter: 1 3;
        height: auto;
        margin-bottom: 1;
        padding-left: 1;
        padding-right: 1;
    }
    .info-section {
        height: auto;
        margin-bottom: 1;
    }
    .info-section .info-label {
        margin-bottom: 1;
        padding-left: 1;
    }
    .info-label {
        color: $primary;
        text-style: italic;
        height: auto;
        width: auto;
    }
    .info-value {
        color: $foreground;
        height: auto;
    }
    .info-value-secondary {
        color: $secondary;
        height: auto;
    }
    .info-list-row {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
        padding-left: 3;
    }
    .info-list-row:last-child {
        margin-bottom: 0;
    }
    .info-bullet {
        color: $foreground;
        width: auto;
        margin-right: 1;
    }
    .info-list-item {
        color: $foreground;
        height: auto;
        width: 1fr;
        text-wrap: wrap;
    }
    .info-empty {
        color: $foreground 50%;
        text-style: italic;
        height: auto;
        width: auto;
    }
    #info-content {
        height: auto;
        margin: 1;
    }
    .var-label {
        color: $secondary;
        padding-left: 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Container(id="info-content")

    def on_mount(self) -> None:
        self.border_title = "Task Information"

    def update_info(self, task: TaskItem | None):
        content = self.query_one("#info-content", Container)
        content.remove_children()
        if not task:
            content.mount(Static("Select a task to view details", classes="info-empty"))
            return
        grid_widgets = [
            Static("Name:", classes="info-label"),
            Static(task.task_name, classes="info-value-secondary"),
            Static("Description:", classes="info-label"),
            Static(task.description or "No description", classes="info-value"),
            Static("Interactive:", classes="info-label"),
            Static("Yes ⚡" if task.interactive else "No", classes="info-value"),
        ]
        if task.prompt:
            grid_widgets.extend(
                [
                    Static("Prompt:", classes="info-label"),
                    Static(task.prompt, classes="info-value"),
                ]
            )
        if task.taskfile:
            grid_widgets.extend(
                [
                    Static("Taskfile:", classes="info-label"),
                    Static(task.taskfile, classes="info-value"),
                ]
            )
        content.mount(Container(*grid_widgets, classes="info-grid"))
        if task.required_vars:
            widgets: list = [Static("Required Variables:", classes="info-label")]
            for var in task.required_vars:
                widgets.append(
                    Container(
                        Static("•", classes="info-bullet"),
                        Static(var, classes="info-list-item"),
                        classes="info-list-row",
                    )
                )
            content.mount(Container(*widgets, classes="info-section"))
        if task.vars:
            section = Container(classes="info-section")
            content.mount(section)
            section.mount(Static("Variables:", classes="info-label"))

            var_widgets: list = []
            for var in task.vars:
                parts = var.split(":", 1)
                key = parts[0].strip()
                value = parts[1].strip() if len(parts) > 1 else ""
                var_widgets.append(Static(f"• {key}:", classes="var-label"))
                var_widgets.append(Static(value, classes="info-list-item"))

            section.mount(Container(*var_widgets, classes="info-grid"))
        if task.env:
            widgets: list = [Static("Environment:", classes="info-label")]
            for env in task.env:
                widgets.append(
                    Container(
                        Static("•", classes="info-bullet"),
                        Static(env, classes="info-list-item"),
                        classes="info-list-row",
                    )
                )
            content.mount(Container(*widgets, classes="info-section"))
        if task.commands:
            widgets: list = [Static("Commands:", classes="info-label")]
            for cmd in task.commands:
                widgets.append(
                    Container(
                        Static("•", classes="info-bullet"),
                        Static(cmd, classes="info-list-item"),
                        classes="info-list-row",
                    )
                )
            content.mount(Container(*widgets, classes="info-section"))


# ===================== PROMPT INPUT SCREEN =====================
class PromptInputScreen(ModalScreen[bool | None]):
    CSS = """
    PromptInputScreen {
        align: left top;
        background: transparent;
        width: 70;
    }

    #dialog {
        width: auto;
        height: auto;
        border: $primary;
        background: $surface;
        padding: 2;
    }

    #title {
        text-align: left;
        text-style: bold;
        margin-bottom: 2;
        margin-left: 1;
        width: auto;
    }

    #prompt-text {
        margin-bottom: 3;
        margin-left: 1;
        padding: 1;
        text-align: left;
        text-style: bold;
    }

    #buttons {
        layout: horizontal;
        height: auto;
        align: left middle;
        width: auto;
        margin-left: 1;
    }

    Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def __init__(self, prompt_message: str) -> None:
        super().__init__()
        self.prompt_message = prompt_message

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static("⚠ Task Requires Confirmation", id="title")
            yield Static(self.prompt_message, id="prompt-text")
            with Container(id="buttons"):
                yield Button("Yes (Y)", variant="primary", id="yes-button")
                yield Button("No (N)", variant="default", id="no-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes-button":
            self.dismiss(True)
        elif event.button.id == "no-button":
            self.dismiss(False)

    def action_close(self) -> None:
        self.dismiss(None)


# ===================== VAR INPUT SCREEN =====================
class VarInputScreen(ModalScreen[dict[str, str] | None]):
    CSS = """
    VarInputScreen {
        align: left top;
        background: transparent;
        width: 70;
    }

    #dialog {
        width: auto;
        height: auto;
        border: $primary;
        background: $surface;
        padding: 2;
    }

    #title {
        text-align: left;
        text-style: bold;
        margin-bottom: 3;
        margin-left: 1;
        width: auto;
    }

    .var-row {
        height: auto;
        width: 100%;
        margin: 2 0;
    }

    .var-label {
        margin-bottom: 1;
        margin-left: 1;
        text-style: italic;
    }

    #buttons {
        layout: horizontal;
        height: auto;
        margin-top: 3;
        align: left middle;
        width: auto;
    }

    Button {
        margin: 0 1;
    }
    Input {
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def __init__(self, task_name: str, required_vars: list[str]) -> None:
        super().__init__()
        self.task_name = task_name
        self.required_vars = required_vars

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static(f"Submit Required Variables", id="title")

            for var_name in self.required_vars:
                with Container(classes="var-row"):
                    yield Static(f"[b]{var_name}[/b]:", classes="var-label")
                    yield Input(placeholder="Enter value", id=f"input-{var_name}")

            with Container(id="buttons"):
                yield Button("Submit", variant="primary", id="ok-button", disabled=True)
                yield Button("Cancel", variant="default", id="cancel-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok-button":
            values = {}
            for var_name in self.required_vars:
                input_widget = self.query_one(f"#input-{var_name}", Input)
                value = input_widget.value.strip()
                values[var_name] = value
            self.dismiss(values)
        elif event.button.id == "cancel-button":
            self.dismiss(None)

    def on_input_changed(self) -> None:
        all_filled = all(
            self.query_one(f"#input-{var_name}", Input).value.strip()
            for var_name in self.required_vars
        )
        self.query_one("#ok-button", Button).disabled = not all_filled

    def on_input_submitted(self, event: Input.Submitted) -> None:
        input_widget = event.input
        if not input_widget.id or not input_widget.value.strip():
            return

        var_name = input_widget.id.replace("input-", "")
        var_index = self.required_vars.index(var_name)

        if var_index < len(self.required_vars) - 1:
            next_var = self.required_vars[var_index + 1]
            self.query_one(f"#input-{next_var}", Input).focus()
        else:
            self.query_one("#ok-button", Button).press()

    def action_close(self) -> None:
        self.dismiss(None)


# ===================== MAIN APP =====================


class TaskSelection(App):
    CSS = """
    Screen {
        layers: below above;
        border-left: inner $primary;
        border-right: inner $primary;
        border-bottom: inner $primary;
        background: $surface;
    }
    #main-container {
        height: 100%;
        layout: horizontal;
        border-top: panel $primary;
    }
    #left-panel {
        width: 65%;
        height: 100%;
    }

    #task-list {
        border: $primary;
    }

    #log-container {
        height: 50%;
        border: $primary;
        background: black;

    }

    #log-container.maximized {
        height: 100%;
        width: 100%;
        layer: above;
    }

    #log-viewer {
        height: 1fr;
        background: black;
        margin-left: 1;
        margin-right: 1;
        border-top: $primary;
        &:focus {
            background-tint: black;
        }
    }

    #search-input {
        height: auto;
        background: $surface;
        width: 30%;
    }

    Footer {
        background: $secondary;
    }
    """
    BINDINGS = [
        Binding("m", "toggle_log_maximize", "Maximize Log Viewer"),
        Binding("n", "next_search", "Next Match", show=False),
        Binding("shift+n", "prev_search", "Prev Match", show=False),
        Binding("escape", "close_search", "Close Search", show=False),
        Binding("q", "quit", "Quit", priority=True),
    ]

    def __init__(self):
        super().__init__()
        self.task_running = False
        self.maximized_log = False
        self.search_matches = []
        self.current_match_index = -1
        self._log_content = []
        self._current_search_term = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-container"):
            with Vertical(id="left-panel"):
                yield ListView(id="task-list")
                with Vertical(id="log-container"):
                    yield SearchInput(placeholder="Search in logs", id="search-input")
                    yield RichLog(id="log-viewer", auto_scroll=False)
            yield TaskInfoPanel(id="info-panel")
        yield Footer()

    async def on_mount(self):
        self.register_theme(task_theme)
        self.theme = "task-theme"
        self.query_one(
            "#main-container", Horizontal
        ).border_title = "Task Management Terminal"
        self.query_one("#log-container", Vertical).border_title = "Logs"
        self.query_one("#log-container", Vertical).border_subtitle = "No task executed yet"
        self.query_one("#log-container", Vertical).styles.border_title_align = "center"
        self.query_one("#log-container", Vertical).styles.border_subtitle_align = "center"
        self.query_one("#task-list", ListView).border_title = "Available Tasks"
        self.query_one("#task-list", ListView).styles.border_title_align = "center"
        if tasks := self.load_tasks():
            self.query_one("#task-list", ListView).extend(tasks)
        self.query_one("#info-panel", TaskInfoPanel).update_info(task=None)

    def action_toggle_log_maximize(self):
        self.maximized_log = not self.maximized_log
        log_container = self.query_one("#log-container", Vertical)
        if self.maximized_log:
            log_container.add_class("maximized")
        else:
            log_container.remove_class("maximized")

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item:
            item = cast(TaskItem, event.item)
            panel = self.query_one("#info-panel", TaskInfoPanel)
            panel.update_info(item)

    def load_tasks(self) -> list[TaskItem] | None:
        try:
            raw = subprocess.run(
                ["task", "--list", "--json"], check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError:
            self.notify("Listing tasks failed!", severity="error")
            return None
        data = json.loads(raw.stdout)

        tasks = []
        for t in data.get("tasks", []):
            name = t["name"]
            desc = t["desc"]
            taskfile_path = t.get("location", {}).get("taskfile", "")
            interactive = False
            required_vars: list[str] | None = None
            prompt: str | None = None

            if taskfile_path and os.path.exists(taskfile_path):
                with open(taskfile_path) as f:
                    taskfile_data = yaml.safe_load(f)
                    task_key = t["task"].split(":")[-1]
                    task_def = taskfile_data.get("tasks", {}).get(task_key, {})
                    interactive = bool(task_def.get("interactive", False))
                    required_vars = task_def.get("requires", {}).get("vars", []) or None
                    prompt = task_def.get("prompt")

            summary = self.get_task_summary(name)

            tasks.append(
                TaskItem(
                    name,
                    desc,
                    interactive,
                    taskfile_path,
                    required_vars,
                    prompt,
                    summary["commands"],
                    summary["vars"],
                    summary["env"],
                )
            )

        return tasks

    def get_task_summary(self, task_name: str) -> dict:
        try:
            result = subprocess.run(
                ["task", task_name, "--summary"],
                check=True,
                capture_output=True,
                text=True,
            )

            summary = {"commands": [], "vars": [], "env": []}
            lines = result.stdout.strip().split("\n")
            current_section = None

            for line in lines:
                line = line.rstrip()
                if line.startswith("commands:"):
                    current_section = "commands"
                elif line.startswith("vars:"):
                    current_section = "vars"
                elif line.startswith("env:"):
                    current_section = "env"
                elif current_section == "commands":
                    if line.startswith(" - "):
                        summary["commands"].append(line[3:])
                    elif line.strip() and summary["commands"]:
                        summary["commands"][-1] += "\n" + line.strip()
                elif line.startswith("  ") and current_section in ["vars", "env"]:
                    summary[current_section].append(line.strip())

            return summary
        except subprocess.CalledProcessError:
            return {"commands": [], "vars": [], "env": []}

    @work
    async def on_list_view_selected(self, event: ListView.Selected):
        item = cast(TaskItem, event.item)
        cmd = ["task", item.task_name]

        var_values = None
        if item.required_vars:
            if not (
                var_values := await self.push_screen_wait(
                    VarInputScreen(item.task_name, item.required_vars)
                )
            ):
                return
            for k, v in var_values.items():
                cmd.append(f"{k}={v}")

        if item.prompt:
            prompt_response = await self.push_screen_wait(
                PromptInputScreen(item.prompt)
            )
            if prompt_response is None:
                return
            elif prompt_response is False:
                self.notify(
                    f'Task "{item.task_name}" cancelled by user', severity="warning"
                )
                return
            cmd.append("--yes")

        if not item.interactive and not item.prompt and "--yes" not in cmd:
            cmd.append("--yes")

        if item.interactive:
            with self.suspend():
                subprocess.run(cmd)
                input("Press Enter to continue...")
        else:
            try:
                self.run_task_in_background(cmd, item.task_name)
            except subprocess.CalledProcessError as e:
                self.notify(
                    e.stderr,
                    severity="error",
                )

    @work(exclusive=True, group="tasks")
    async def run_task_in_background(self, cmd: list[str], task_name: str):
        self.task_running = True

        log_viewer = self.query_one("#log-viewer", RichLog)
        start_time = datetime.now()

        log_viewer.border_subtitle = (
            f"{task_name} - Running... (Started: {start_time.strftime('%H:%M:%S')})"
        )

        self.smart_log_write(Text(f">>> Executing task: {task_name}", style="bold secondary"))

        proc = None
        read_task = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )

            async def read_stream(stream, color=""):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode().strip()
                    self.smart_log_write(Text(text, style=color) if color else text)

            read_task = asyncio.gather(
                read_stream(proc.stdout), read_stream(proc.stderr, "red")
            )
            exit_code = await proc.wait()
            await read_task

            end_time = datetime.now()
            success = exit_code == 0
            status = "✔ Success" if success else "✘ Failed"
            log_viewer.border_subtitle = f"{task_name} - {status} (Started: {start_time.strftime('%H:%M:%S')}, Finished: {end_time.strftime('%H:%M:%S')})"

        except asyncio.CancelledError:
            if proc:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                if read_task:
                    await read_task
                await proc.wait()
            log_viewer.border_subtitle = f"{task_name} - ✘ Cancelled"
            raise

        except Exception as e:
            self.smart_log_write(f"[bold red]Error executing task: {str(e)}[/]")
            log_viewer.border_subtitle = f"{task_name} - ✘ Error"

        finally:
            self.task_running = False

    def smart_log_write(self, content):
        log = self.query_one("#log-viewer", RichLog)
        was_at_bottom = log.scroll_y >= log.max_scroll_y

        self._log_content.append(content)

        if self._current_search_term:
            content = self._apply_search_highlighting(content, len(self._log_content) - 1)

        log.write(content)
        if was_at_bottom:
            log.scroll_end(animate=False)

    def _apply_search_highlighting(self, content, line_index):
        if not self._current_search_term:
            return content

        if isinstance(content, str):
            text = Text(content)
        elif isinstance(content, Text):
            text = content.copy()
        else:
            text = Text(str(content))

        search_lower = self._current_search_term.lower()
        plain_lower = text.plain.lower()

        if search_lower not in plain_lower:
            return text

        is_current = (self.search_matches and
                     line_index in self.search_matches and
                     self.search_matches[self.current_match_index] == line_index)

        start = 0
        while True:
            pos = plain_lower.find(search_lower, start)
            if pos == -1:
                break

            if is_current:
                text.stylize("black on yellow bold", pos, pos + len(self._current_search_term))
            else:
                text.stylize("black on cyan", pos, pos + len(self._current_search_term))

            start = pos + len(self._current_search_term)

        return text

    def _rewrite_log_with_search(self):
        log = self.query_one("#log-viewer", RichLog)
        current_scroll = log.scroll_y

        log.clear()
        for index, content in enumerate(self._log_content):
            highlighted = self._apply_search_highlighting(content, index)
            log.write(highlighted)

        log.scroll_to(y=current_scroll, animate=False)

    def action_next_search(self):
        if not self.search_matches:
            return

        self.current_match_index = (self.current_match_index + 1) % len(self.search_matches)
        self._rewrite_log_with_search()
        self.scroll_to_current_match()
        self.update_search_status()

    def action_prev_search(self):
        if not self.search_matches:
            return

        self.current_match_index = (self.current_match_index - 1) % len(self.search_matches)
        self._rewrite_log_with_search()
        self.scroll_to_current_match()
        self.update_search_status()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "search-input":
            self.perform_search(event.value)

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "search-input":
            self.action_next_search()

    def perform_search(self, query: str):
        self.search_matches = []
        self._current_search_term = query

        if not query:
            self.current_match_index = -1
            self._rewrite_log_with_search()
            self.update_search_status()
            return

        query_lower = query.lower()

        for line_index, content in enumerate(self._log_content):
            line_text = str(content).lower()
            if query_lower in line_text:
                self.search_matches.append(line_index)

        self.current_match_index = 0 if self.search_matches else -1

        self._rewrite_log_with_search()

        if self.search_matches:
            self.scroll_to_current_match()

        self.update_search_status()

    def scroll_to_current_match(self):
        if not self.search_matches or self.current_match_index == -1:
            return

        log = self.query_one("#log-viewer", RichLog)
        line_index = self.search_matches[self.current_match_index]

        total_lines = len(self._log_content)
        if total_lines > 0 and log.max_scroll_y > 0:
            scroll_fraction = line_index / max(total_lines - 1, 1)
            target_scroll = int(scroll_fraction * log.max_scroll_y)
            log.scroll_to(y=target_scroll, animate=True)

    def update_search_status(self):
        log = self.query_one("#log-viewer", RichLog)

        if not self.query_one("#search-input", SearchInput).value:
            if self.task_running:
                pass
            else:
                log.border_subtitle = "No task executed yet"
        elif self.search_matches:
            match_count = len(self.search_matches)
            current = self.current_match_index + 1
            log.border_subtitle = f"Match {current}/{match_count}"
        else:
            log.border_subtitle = "No matches found"

    def on_unmount(self) -> None:
        self.console.clear()
        self.console.show_cursor()

if __name__ == "__main__":
    TaskSelection().run()
