#!/usr/bin/env python3
import subprocess
import sys
import signal
from enum import Enum
from typing import List, Optional

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
        self.is_all_namespaces = False
        signal.signal(signal.SIGINT, self.handle_sigint)
        self.should_exit = False

    def handle_sigint(self, signum, frame):
        """Handle Ctrl+C by setting exit flag"""
        self.should_exit = True
        print("\nExiting...")
        sys.exit(0)

    def run_fzf(self, prompt: str, items: List[str], preview_cmd: str = "") -> Optional[str]:
        """Run fzf with proper key bindings and preview handling"""
        if self.should_exit:
            sys.exit(0)

        fzf_cmd = [
            "fzf",
            "--prompt", f"{prompt} > ",
            "--header", "[Enter] select | [ESC] back | [Ctrl+C] exit",
            "--layout=reverse",
            "--border",
            "--preview-window=right:70%:wrap",
            "--color=fg:#d0d0d0,bg:#1b1b1b,hl:#00afff",
            "--color=fg+:#ffffff,bg+:#005f87,hl+:#00afff",
            "--color=info:#87ffaf,prompt:#ff5f00,pointer:#af00ff",
            "--expect", "ctrl-c"
        ]

        if preview_cmd:
            fzf_cmd += ["--preview", preview_cmd]
            preview_bindings = [
                "--bind", f"ctrl-d:preview({preview_cmd})"
            ]

            # Add YAML preview
            if self.is_all_namespaces:
                preview_bindings.extend([
                    "--bind", "ctrl-y:preview(echo {} | awk -F/ '{print \"kubectl get pod/\" $2 \" -n \" $1 \" -o yaml\"}' | sh 2>/dev/null || echo 'No YAML available')"
                ])
            else:
                preview_bindings.extend([
                    "--bind", f"ctrl-y:preview(kubectl get {self.current_resource_type}/{{}} -n {self.current_namespace} -o yaml 2>/dev/null || echo 'No YAML available')"
                ])

            # Add logs preview for pods
            if self.current_resource_type == "pod":
                if self.is_all_namespaces:
                    preview_bindings.extend([
                        "--bind", "ctrl-l:preview(echo {} | awk -F/ '{print \"kubectl logs pod/\" $2 \" -n \" $1 \" --tail=50\"}' | sh 2>/dev/null || echo 'No logs available')"
                    ])
                else:
                    preview_bindings.extend([
                        "--bind", f"ctrl-l:preview(kubectl logs {self.current_resource_type}/{{}} -n {self.current_namespace} --tail=50 2>/dev/null || echo 'No logs available')"
                    ])
                fzf_cmd += ["--preview-label", "[Ctrl-D] describe | [Ctrl-L] logs | [Ctrl-Y] yaml"]
            else:
                fzf_cmd += ["--preview-label", "[Ctrl-D] describe | [Ctrl-Y] yaml"]

            fzf_cmd.extend(preview_bindings)

        try:
            proc = subprocess.run(
                fzf_cmd,
                input="\n".join(items).encode(),
                check=True,
                stdout=subprocess.PIPE
            )
            output = proc.stdout.decode().strip().split('\n')

            if output and output[0] == 'ctrl-c':
                print("\nExiting...")
                sys.exit(0)

            selected = output[-1] if output else None
            if selected and self.is_all_namespaces and "/" in selected:
                namespace, name = selected.split("/")

            return selected

        except subprocess.CalledProcessError as e:
            if e.returncode == 130:
                return None
            raise

    def get_namespaces(self) -> List[str]:
        result = subprocess.run(
            ["kubectl", "get", "ns", "-o", "jsonpath={.items[*].metadata.name}"],
            stdout=subprocess.PIPE,
            check=True
        )
        return ["all"] + result.stdout.decode().strip().split()

    def get_resources(self, resource_type: str, namespace: str) -> List[str]:
        """Get resources in type/name format"""
        args = ["kubectl", "get", resource_type]
        if namespace != "all":
            args += ["-n", namespace]
        else:
            args += ["-A"]

        if namespace == "all":
            # For all namespaces, get namespace and name separately
            result = subprocess.run(
                args + ["-o", "custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name", "--no-headers"],
                stdout=subprocess.PIPE,
                check=True
            )
            resources = []
            for line in result.stdout.splitlines():
                parts = line.decode().strip().split()
                if len(parts) == 2:  # namespace and name
                    resources.append(f"{parts[0]}/{parts[1]}")
            return resources
        else:
            # For single namespace, just get the name
            result = subprocess.run(
                args + ["-o", "name"],
                stdout=subprocess.PIPE,
                check=True
            )
            return [line.decode().strip().split("/")[-1] for line in result.stdout.splitlines()]

    def handle_namespace_selection(self) -> bool:
        """Namespace selection with proper preview"""
        namespaces = self.get_namespaces()
        preview = "kubectl get pods -n {} 2>/dev/null || echo 'No pods in namespace'"
        selected = self.run_fzf("Namespace", namespaces, preview)

        if selected is None:
            return False

        self.current_namespace = selected
        self.is_all_namespaces = (selected == "all")
        self.nav_stack.append(MenuLevel.NAMESPACE)
        return True

    def handle_resource_type_selection(self) -> bool:
        """Resource type selection menu"""
        types = ["pod", "deployment", "service", "helmrelease", "statefulset", "daemonset"]
        selected = self.run_fzf("Resource Type", types)

        if selected is None:
            return False

        self.current_resource_type = selected
        self.nav_stack.append(MenuLevel.RESOURCE_TYPE)
        return True

    def handle_resource_selection(self) -> bool:
        """Resource selection with fixed describe command"""
        resources = self.get_resources(self.current_resource_type, self.current_namespace)
        if self.is_all_namespaces:
            # Use a shell command to split the namespace/name and construct the kubectl command
            preview = "echo {} | awk -F/ '{print \"kubectl describe pod/\" $2 \" -n \" $1}' | sh 2>/dev/null || echo 'No description available'"
        else:
            preview = f"kubectl describe {self.current_resource_type}/{{}} -n {self.current_namespace} 2>/dev/null || echo 'No description available'"
        selected = self.run_fzf(self.current_resource_type, resources, preview)

        if selected is None:
            return False

        if self.is_all_namespaces:
            # For all namespaces, selected is in format "namespace/name"
            namespace, name = selected.split("/")
            self.current_namespace = namespace  # Update current namespace for actions
            self.current_resource = f"{self.current_resource_type}/{name}"
        else:
            self.current_resource = f"{self.current_resource_type}/{selected}"
        self.nav_stack.append(MenuLevel.RESOURCE)
        return True

    def handle_action_selection(self) -> bool:
        """Action selection with context-aware options"""
        actions = ["edit", "delete"]
        if self.current_resource_type == "pod":
            actions.append("exec")
        elif self.current_resource_type == "service":
            actions.append("port-forward")

        selected = self.run_fzf("Action", actions)

        if selected is None:
            return False

        self.execute_action(selected)
        return True

    def execute_action(self, action: str):
        """Execute action with proper resource formatting"""
        try:
            if action == "edit":
                subprocess.run(
                    ["kubectl", "edit", self.current_resource, "-n", self.current_namespace],
                    check=True
                )
            elif action == "delete":
                subprocess.run(
                    ["kubectl", "delete", self.current_resource, "-n", self.current_namespace],
                    check=True
                )
            elif action == "exec":
                resource_name = self.current_resource.split("/")[-1]
                subprocess.run(
                    ["kubectl", "exec", "-it", resource_name, "-n", self.current_namespace, "--", "/bin/sh"],
                    check=True
                )
            elif action == "port-forward":
                lport = input("Local port: ")
                tport = input("Target port: ")
                subprocess.run(
                    ["kubectl", "port-forward", "-n", self.current_namespace,
                     self.current_resource, f"{lport}:{tport}"],
                    check=True
                )
        except subprocess.CalledProcessError as e:
            print(f"\n⚠️ Command failed with error: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)

    def run(self):
        """Main navigation loop"""
        while True:
            try:
                if not self.nav_stack:
                    if not self.handle_namespace_selection():
                        break
                    continue

                current_level = self.nav_stack[-1]

                if current_level == MenuLevel.NAMESPACE:
                    if not self.handle_resource_type_selection():
                        self.nav_stack.pop()
                        continue
                    # If we're in all namespaces, immediately show resource list
                    if self.is_all_namespaces:
                        if not self.handle_resource_selection():
                            self.nav_stack.pop()
                elif current_level == MenuLevel.RESOURCE_TYPE:
                    if not self.handle_resource_selection():
                        self.nav_stack.pop()
                elif current_level == MenuLevel.RESOURCE:
                    if not self.handle_action_selection():
                        self.nav_stack.pop()
                        # Restore all-namespaces context if needed
                        if self.is_all_namespaces:
                            self.current_namespace = "all"
                else:
                    break
            except KeyboardInterrupt:
                print("\nOperation cancelled")
                break

if __name__ == "__main__":
    KubeExplorer().run()
