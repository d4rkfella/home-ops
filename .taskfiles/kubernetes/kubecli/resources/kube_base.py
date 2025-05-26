#!/usr/bin/env python3
import subprocess
import sys
from typing import List, Optional, Tuple

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
            f"--layout=reverse",
            "--border=rounded",
            "--margin=1,2",
            "--preview-window=right:60%:wrap",
            "--bind", "ctrl-s:toggle-sort",
            "--bind", "ctrl-c:abort",
            "--bind", "alt-b:abort",  # back
            "--bind", "esc:abort"
        ]
        # Add colors
        for k, v in FZF_COLORS.items():
            style += ["--color", f"{k}:{v}"]
        return style

    def get_common_bindings(self) -> Tuple[List[str], str]:
        bindings = [
            "--bind", f"alt-d:preview(kubectl describe {self.resource_type}/{{}} -n {self.current_namespace})+change-preview-window(right:60%:wrap|hidden)",
            "--bind", f"alt-x:execute(kubectl delete {self.resource_type} {{}} -n {self.current_namespace} --grace-period=30)+reload(kubectl get {self.resource_type} -n {self.current_namespace} --no-headers -o custom-columns=:metadata.name)+refresh-preview",
            "--bind", f"alt-e:execute(kubectl edit {self.resource_type} {{}} -n {self.current_namespace})+reload(kubectl get {self.resource_type} -n {self.current_namespace} --no-headers -o custom-columns=:metadata.name)+refresh-preview",
            "--bind", "alt-b:abort",
            "--bind", "ctrl-c:abort",
        ]
        label = "Alt-D:Describe | Alt-X:Delete | Alt-E:Edit | Alt-B:Back | Ctrl-C:Exit"
        return bindings, label

    def run_fzf(
        self,
        items: str,
        prompt: str,
        preview_cmd: Optional[str] = None,
        extra_bindings: List[str] = [],
        header: Optional[str] = None
    ):
        bindings, label = self.get_common_bindings()
        all_bindings = bindings + extra_bindings

        # Combine the default label with the custom header if provided
        if header:
            header_option = f"{label}\n{header}"
        else:
            header_option = label

        cmd = ["fzf"] + self.get_fzf_style() + [
            "--prompt", f"{prompt}> ",
            "--header", header_option,
            "--preview", preview_cmd or f"kubectl get {self.resource_type}/{{}} -n {self.current_namespace} -o wide 2>/dev/null || echo 'No info'",
            *all_bindings
        ]

        try:
            result = subprocess.run(
                cmd,
                input=items,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if e.returncode == 130:  # user aborted
                return None
            print(f"fzf error: {e.stderr}", file=sys.stderr)
            return None

    def get_namespaces(self) -> str:
        try:
            result = subprocess.run(
                ["kubectl", "get", "namespaces", "--no-headers", "-o", "custom-columns=:metadata.name"],
                capture_output=True, text=True, check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Error fetching namespaces: {e.stderr}", file=sys.stderr)
            return ""

    def select_namespace(self) -> Optional[str]:
        return self.run_fzf(self.get_namespaces(), "Namespace")

    def refresh_resources(self, namespace: str) -> str:
        try:
            result = subprocess.run(
                ["kubectl", "get", self.resource_type, "-n", namespace, "--no-headers", "-o", "custom-columns=:metadata.name"],
                capture_output=True, text=True, check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Error fetching {self.resource_type}: {e.stderr}", file=sys.stderr)
            return ""
