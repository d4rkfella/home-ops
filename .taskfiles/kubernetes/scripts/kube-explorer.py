#!/usr/bin/env python3
import subprocess
import sys
from enum import Enum
from typing import List, Optional, Tuple

class MenuLevel(Enum):
    NAMESPACE = 1
    RESOURCE_TYPE = 2
    RESOURCE = 3
    ACTION = 4

class KubeExplorer:
    def __init__(self):
        self.nav_stack = []
        self.current_namespace = ""
        self.current_resource_type = ""
        self.current_resource = ""

    def run_fzf(self, prompt: str, items: List[str], preview_cmd: str = "") -> Optional[str]:
        """Run fzf with proper key bindings and preview handling"""
        fzf_cmd = [
            "fzf",
            "--prompt", f"{prompt} > ",
            "--header", "[Enter] select | [ESC] exit | [Ctrl+B] back",
            "--layout=reverse",
            "--border",
            "--preview-window=right:50%:wrap",
            "--color=fg:#d0d0d0,bg:#1b1b1b,hl:#00afff",
            "--color=fg+:#ffffff,bg+:#005f87,hl+:#00afff",
            "--color=info:#87ffaf,prompt:#ff5f00,pointer:#af00ff",
            "--bind", "ctrl-b:abort"
        ]

        if preview_cmd:
            fzf_cmd += ["--preview", preview_cmd]
            fzf_cmd += ["--bind", "ctrl-d:preview({})".format(preview_cmd.replace("{}", "{2}"))]

        try:
            proc = subprocess.run(
                fzf_cmd,
                input="\n".join(items).encode(),
                check=True,
                stdout=subprocess.PIPE
            )
            return proc.stdout.decode().strip()
        except subprocess.CalledProcessError as e:
            if e.returncode == 130:  # Ctrl+B or ESC
                return None
            raise

    def get_namespaces(self) -> List[str]:
        result = subprocess.run(
            ["kubectl", "get", "ns", "-o", "jsonpath='{.items[*].metadata.name}'"],
            stdout=subprocess.PIPE,
            check=True
        )
        return ["all"] + result.stdout.decode().strip().split()

    def get_resources(self, resource_type: str, namespace: str) -> List[str]:
        args = ["kubectl", "get", resource_type]
        if namespace != "all":
            args += ["-n", namespace]
        else:
            args += ["-A"]

        result = subprocess.run(
            args + ["-o", "name"],
            stdout=subprocess.PIPE,
            check=True
        )
        return result.stdout.decode().splitlines()

    def handle_namespace_selection(self) -> bool:
        namespaces = self.get_namespaces()
        preview = "kubectl get pods -n {} -o wide 2>/dev/null || echo 'No pods in namespace'"
        selected = self.run_fzf("Namespace", namespaces, preview)

        if selected is None:
            return False

        self.current_namespace = selected
        self.nav_stack.append(MenuLevel.NAMESPACE)
        return True

    def handle_resource_type_selection(self) -> bool:
        types = ["pod", "deployment", "service", "helmrelease", "statefulset", "daemonset"]
        selected = self.run_fzf("Resource Type", types)

        if selected is None:
            return False

        self.current_resource_type = selected
        self.nav_stack.append(MenuLevel.RESOURCE_TYPE)
        return True

    def handle_resource_selection(self) -> bool:
        resources = self.get_resources(self.current_resource_type, self.current_namespace)
        preview = f"kubectl describe {self.current_resource_type} {{}} -n {self.current_namespace}"
        selected = self.run_fzf(self.current_resource_type, resources, preview)

        if selected is None:
            return False

        self.current_resource = selected
        self.nav_stack.append(MenuLevel.RESOURCE)
        return True

    def handle_action_selection(self) -> bool:
        actions = ["describe", "edit", "delete"]
        if self.current_resource_type == "pod":
            actions.append("exec")
        elif self.current_resource_type == "service":
            actions.append("port-forward")

        preview = f"kubectl get {self.current_resource_type} {self.current_resource} -n {self.current_namespace} -o yaml"
        selected = self.run_fzf("Action", actions, preview)

        if selected is None:
            return False

        self.execute_action(selected)
        return True

    def execute_action(self, action: str):
        resource = self.current_resource.split("/")[-1]
        cmd = ["kubectl", action, self.current_resource_type, resource, "-n", self.current_namespace]

        if action == "port-forward":
            lport = input("Local port: ")
            tport = input("Target port: ")
            cmd += [f"{lport}:{tport}"]

        subprocess.run(cmd, check=True)

    def run(self):
        while True:
            if not self.nav_stack:
                if not self.handle_namespace_selection():
                    break
                continue

            current_level = self.nav_stack[-1]

            try:
                if current_level == MenuLevel.NAMESPACE:
                    if not self.handle_resource_type_selection():
                        self.nav_stack.pop()
                elif current_level == MenuLevel.RESOURCE_TYPE:
                    if not self.handle_resource_selection():
                        self.nav_stack.pop()
                elif current_level == MenuLevel.RESOURCE:
                    if not self.handle_action_selection():
                        self.nav_stack.pop()
                else:
                    break
            except KeyboardInterrupt:
                print("\nOperation cancelled")
                break

if __name__ == "__main__":
    KubeExplorer().run()
