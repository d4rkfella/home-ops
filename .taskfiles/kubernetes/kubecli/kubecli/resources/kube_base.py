#!/usr/bin/env python3
import subprocess
import sys
from typing import List, Optional, Tuple, Union

FZF_COLORS = {
    "fg": "#d0d0d0",
    "bg": "#1b1b1b",
    "hl": "#00afff",
    "fg+": "#ffffff",
    "bg+": "#005f87",
    "hl+": "#00afff",
    "info": "#87ffaf",
    "prompt": "#ff5f00",
    "pointer": "#af00ff"
}

class KubeBase:
    resource_type = ""
    resource_name = ""

    def __init__(self):
        self.current_namespace = None

    def get_fzf_style(self) -> List[str]:
        style = [
            "--history-size=1000",
            "--layout=reverse",
            "--border=rounded",
            "--margin=1,2"
        ]
        for k, v in FZF_COLORS.items():
            style += ["--color", f"{k}:{v}"]
        return style

    def get_common_bindings(self) -> Tuple[List[str], str]:
        bindings = [
            "--bind", "ctrl-s:toggle-sort",
            "--bind", f"alt-d:change-preview(kubectl describe {self.resource_type}/{{1}} -n {self.current_namespace})+change-preview-window(hidden|right:60%:wrap)",
            "--bind", f"alt-w:change-preview(kubectl get {self.resource_type}/{{1}} -n {self.current_namespace} -o wide)+change-preview-window(hidden|right:90%:wrap)",
            "--bind", f"alt-v:change-preview(kubectl get {self.resource_type}/{{1}} -n {self.current_namespace})+change-preview-window(hidden|right:60%:wrap)",
            "--bind", f"alt-x:execute(kubectl delete {self.resource_type} {{1}} -n {self.current_namespace} --grace-period=30)+reload(kubectl get {self.resource_type} -n {self.current_namespace} --no-headers -o custom-columns=:metadata.name)+refresh-preview",
            "--bind", f"alt-e:execute(kubectl edit {self.resource_type} {{1}} -n {self.current_namespace})+reload(kubectl get {self.resource_type} -n {self.current_namespace} --no-headers -o custom-columns=:metadata.name)+refresh-preview",
        ]
        base_header = (
            "Alt-D:Describe | Alt-W:Wide | Alt-V:Default | "
            "Alt-X:Delete | Alt-E:Edit | Esc:Back | Ctrl-C:Exit"
        )
        return bindings, base_header

    def run_fzf(
        self,
        items: Union[List[str], str],
        prompt: str,
        preview_cmd: Optional[str] = None,
        extra_bindings: List[str] = [],
        header: Optional[str] = None,
        expect: Optional[str] = None,
        use_common_bindings: bool = True
    ) -> Union[str, Tuple[Optional[str], Optional[str]], None]:

        if isinstance(items, list):
            items_str = "\n".join(items)
        else:
            items_str = items

        all_bindings = []
        base_header = ""

        if use_common_bindings:
            bindings, base_header = self.get_common_bindings()
            all_bindings.extend(bindings)

        all_bindings.extend(extra_bindings)

        header_lines = []
        if base_header:
            header_lines.append(base_header)
            header_lines.append("─" * 110)
        if header:
            header_lines.append(header)
            header_lines.append("─" * 110)
        header_option = "\n".join(header_lines)

        cmd = ["fzf"] + self.get_fzf_style() + [
            "--prompt", f"{prompt}> ",
            "--header", header_option,
        ]

        if preview_cmd:
            cmd += ["--preview", preview_cmd]

        cmd += all_bindings

        if expect:
            cmd.append(f"--expect={expect}")

        try:
            result = subprocess.run(
                cmd,
                input=items_str,
                capture_output=True,
                text=True,
                check=True
            )
            lines = result.stdout.strip().split("\n")

            if expect:
                if lines and lines[0] in expect.split(","):
                    if len(lines) == 1:
                        return lines[0], None
                    if len(lines) > 1:
                        return lines[0], lines[1]
                if lines:
                    return "enter", lines[0]
                return None, None
            else:
                return lines[0] if lines else None

        except subprocess.CalledProcessError as e:
            if e.returncode == 130:
                return None
            print(f"fzf error: {e.stderr}", file=sys.stderr)
            return None

    def get_namespaces(self) -> List[str]:
        try:
            result = subprocess.run(
                ["kubectl", "get", "namespaces", "--no-headers", "-o", "custom-columns=:metadata.name"],
                capture_output=True, text=True, check=True
            )
            namespaces = result.stdout.strip().splitlines()
            return namespaces
        except subprocess.CalledProcessError as e:
            print(f"Error fetching namespaces: {e.stderr}", file=sys.stderr)
            return []

    def select_namespace(self) -> Tuple[Optional[str], Optional[str]]:
        namespaces = self.get_namespaces()
        if not namespaces:
            print("No namespaces found.", file=sys.stderr)
            return "esc", None

        preview_cmd = f"kubectl get {self.resource_type} -n {{}} --no-headers"
        extra_bindings = [
            "--bind", "alt-x:execute(sh -c 'read -p \"Delete namespace {}? [y/N]: \" ans && [ \"$ans\" = y ] && kubectl delete namespace {}')+reload(kubectl get namespaces --no-headers -o custom-columns=:metadata.name)+refresh-preview",
            "--bind", "alt-e:execute(kubectl edit namespace {})",
            "--preview-window", "right:80%:wrap"
        ]
        header = "Alt-E:Edit | Alt-X:Delete | Esc:Back | Ctrl-C:Exit"

        result = self.run_fzf(
            namespaces,
            "Namespace",
            preview_cmd=preview_cmd,
            extra_bindings=extra_bindings,
            header=header,
            expect="esc",
            use_common_bindings=False
        )

        if isinstance(result, tuple):
            key, selected_ns = result
        elif isinstance(result, str):
            key, selected_ns = "enter", result
        else:
            return "esc", None

        return key, selected_ns

    def refresh_resources(self, namespace: str) -> List[str]:
        try:
            result = subprocess.run(
                ["kubectl", "get", self.resource_type, "-n", namespace, "--no-headers", "-o", "custom-columns=:metadata.name"],
                capture_output=True, text=True, check=True
            )
            return result.stdout.strip().splitlines()
        except subprocess.CalledProcessError as e:
            print(f"Error fetching {self.resource_type}: {e.stderr}", file=sys.stderr)
            return []

    def select_resource(self) -> Tuple[Optional[str], Optional[str]]:
        # This is intended to be overridden by subclasses.
        return "esc", None

    def handle_resource_action(self, resource_name: str):
        print(f"{self.resource_name} selected: {resource_name}")

    def navigate(self):
        while True:
            if not self.current_namespace:
                key, ns = self.select_namespace()
                if key == "esc" or ns is None:
                    print("Exiting.")
                    return
                self.current_namespace = ns

            key, resource = self.select_resource()
            if key == "esc" or resource is None:
                self.current_namespace = None
                continue

            if key == "enter":
                self.handle_resource_action(resource)
            else:
                # Other keys can be handled in subclasses.
                pass
