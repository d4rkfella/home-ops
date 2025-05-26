#!/usr/bin/env python3
import subprocess
import sys
import signal
from enum import Enum
from typing import List, Optional, Dict, Tuple

class MenuLevel(Enum):
    NAMESPACE = 1
    RESOURCE_TYPE = 2
    RESOURCE = 3
    ACTION = 4

# Constants for better maintainability
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

STANDARD_RESOURCE_TYPES = [
    "pod",
    "deployment",
    "service",
    "helmrelease",
    "statefulset",
    "daemonset"
]

class KubeExplorer:
    def __init__(self):
        self.nav_stack: List[MenuLevel] = []
        self.current_namespace: str = ""
        self.current_resource_type: str = ""
        self.current_resource: str = ""
        self.is_all_namespaces: bool = False
        self.cached_crds: Optional[List[str]] = None
        self.is_crd_mode: bool = False
        self.nav_history: List[Tuple[MenuLevel, str]] = []  # Track navigation history with context
        self.selection_memory: Dict[MenuLevel, str] = {}  # Remember last selection at each level
        signal.signal(signal.SIGINT, self.handle_sigint)
        self.should_exit: bool = False

    def handle_sigint(self, signum, frame):
        """Handle Ctrl+C by setting exit flag"""
        self.should_exit = True
        print("\nExiting...")
        sys.exit(0)

    def get_resource_bindings(self) -> Tuple[List[str], str]:
        """Get resource-specific bindings and preview label based on resource type"""
        preview_bindings = []
        preview_label = "[Ctrl-D] describe | [Ctrl-Y] yaml | [Ctrl-R] reload"

        # Common bindings for all resources
        preview_bindings.extend([
            "--bind", f"ctrl-d:preview(kubectl describe {self.current_resource_type}/{{}} -n {self.current_namespace} 2>/dev/null || echo 'No description available')",
            "--bind", f"ctrl-y:preview(kubectl get {self.current_resource_type}/{{}} -n {self.current_namespace} -o yaml 2>/dev/null || echo 'No YAML available')",
            "--bind", f"ctrl-r:execute(kubectl get {self.current_resource_type} -n {self.current_namespace} -o name)+refresh-preview"
        ])

        # Resource-specific bindings
        if self.current_resource_type == "pod":
            logs_cmd = f"kubectl logs --all-containers --follow --tail=10000 {self.current_resource_type}/{{}} -n {self.current_namespace} 2>/dev/null || echo 'No logs available'"
            preview_bindings.extend([
                "--bind", f"ctrl-l:preview({logs_cmd})",
                "--bind", "ctrl-b:execute-silent(echo -n {2} | xclip -selection clipboard)",
                "--bind", f"ctrl-alt-x:execute(kubectl delete {self.current_resource_type} -n {self.current_namespace} {{}})+refresh-preview",
                "--bind", f"ctrl-e:execute(kubectl exec -it {self.current_resource_type}/{{}} -n {self.current_namespace} -- bash)"
            ])
            preview_label = "[Ctrl-D] describe | [Ctrl-L] logs | [Ctrl-Y] yaml | [Ctrl-R] reload | [Ctrl-E] exec | [Ctrl-B] copy name | [Ctrl-Alt-X] delete"

        elif self.current_resource_type == "deployment":
            preview_bindings.extend([
                "--bind", f"ctrl-alt-r:execute(kubectl rollout restart {self.current_resource_type}/{{}} -n {self.current_namespace})+refresh-preview",
                "--bind", f"ctrl-alt-x:execute(kubectl delete {self.current_resource_type} -n {self.current_namespace} {{}})+refresh-preview"
            ])
            preview_label = "[Ctrl-D] describe | [Ctrl-Y] yaml | [Ctrl-R] reload | [Ctrl-Alt-R] restart | [Ctrl-Alt-X] delete"

        elif self.current_resource_type == "service":
            preview_bindings.extend([
                "--bind", f"ctrl-p:execute(kubectl port-forward {self.current_resource_type}/{{}} -n {self.current_namespace} {{3}}:{{4}})",
                "--bind", f"ctrl-alt-x:execute(kubectl delete {self.current_resource_type} -n {self.current_namespace} {{}})+refresh-preview"
            ])
            preview_label = "[Ctrl-D] describe | [Ctrl-Y] yaml | [Ctrl-R] reload | [Ctrl-P] port-forward | [Ctrl-Alt-X] delete"

        elif self.current_resource_type == "statefulset":
            preview_bindings.extend([
                "--bind", f"ctrl-alt-r:execute(kubectl rollout restart {self.current_resource_type}/{{}} -n {self.current_namespace})+refresh-preview",
                "--bind", f"ctrl-alt-x:execute(kubectl delete {self.current_resource_type} -n {self.current_namespace} {{}})+refresh-preview"
            ])
            preview_label = "[Ctrl-D] describe | [Ctrl-Y] yaml | [Ctrl-R] reload | [Ctrl-Alt-R] restart | [Ctrl-Alt-X] delete"

        elif self.current_resource_type == "daemonset":
            preview_bindings.extend([
                "--bind", f"ctrl-alt-r:execute(kubectl rollout restart {self.current_resource_type}/{{}} -n {self.current_namespace})+refresh-preview",
                "--bind", f"ctrl-alt-x:execute(kubectl delete {self.current_resource_type} -n {self.current_namespace} {{}})+refresh-preview"
            ])
            preview_label = "[Ctrl-D] describe | [Ctrl-Y] yaml | [Ctrl-R] reload | [Ctrl-Alt-R] restart | [Ctrl-Alt-X] delete"

        return preview_bindings, preview_label

    def run_fzf(self, prompt: str, items: List[str], preview_cmd: str = "") -> Optional[str]:
        """Run fzf with proper key bindings and preview handling"""
        if self.should_exit:
            sys.exit(0)

        # Get current context for prompt
        try:
            context = subprocess.run(
                ["kubectl", "config", "current-context"],
                stdout=subprocess.PIPE,
                check=True
            ).stdout.decode().strip()
            prompt = f"{context}> "
        except subprocess.CalledProcessError:
            pass

        # Build color arguments
        color_args = []
        for key, value in FZF_COLORS.items():
            color_args.extend(["--color", f"{key}:{value}"])

        fzf_cmd = [
            "fzf",
            "--prompt", f"{prompt} > ",
            "--header", "[Enter] select | [ESC] back | [Ctrl+C] exit",
            "--layout=reverse",
            "--border",
            "--preview-window=right:70%:wrap",
            *color_args,
            "--expect", "ctrl-c"
        ]

        # Add query to jump to last selection if available
        current_level = self.nav_stack[-1] if self.nav_stack else None
        if current_level and current_level in self.selection_memory:
            last_selection = self.selection_memory[current_level]
            if last_selection in items:
                # Use print-query to position cursor without executing
                fzf_cmd.extend(["--print-query", "--query", last_selection])

        if preview_cmd:
            fzf_cmd += ["--preview", preview_cmd]
            preview_bindings, preview_label = self.get_resource_bindings()
            fzf_cmd.extend(preview_bindings)
            fzf_cmd += ["--preview-label", preview_label]

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
                
            # With print-query, the first line is the query, the second is the selection
            selected = output[-1] if output else None
            if selected and self.nav_stack:
                # Remember the selection for the current level
                self.selection_memory[self.nav_stack[-1]] = selected
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
        return result.stdout.decode().strip().split()

    def get_crds(self) -> List[str]:
        """Get list of available Custom Resource Definitions"""
        # Return cached CRDs if available
        if self.cached_crds is not None:
            return self.cached_crds

        try:
            print("\nLoading custom resources...", file=sys.stderr)
            result = subprocess.run(
                ["kubectl", "get", "crd", "-o", "jsonpath={.items[*].spec.names.plural}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
            crds = result.stdout.decode().strip().split()
            print(f"Found {len(crds)} CRDs", file=sys.stderr)

            # Cache the CRDs
            self.cached_crds = crds
            return crds

        except subprocess.CalledProcessError as e:
            print(f"\nError loading CRDs: {e.stderr.decode()}", file=sys.stderr)
            return []

    def handle_namespace_selection(self) -> bool:
        """Namespace selection with proper preview"""
        namespaces = self.get_namespaces()
        preview = "kubectl get pods -n {} 2>/dev/null || echo 'No pods in namespace'"
        selected = self.run_fzf("Namespace", namespaces, preview)

        if selected is None:
            return False

        self.current_namespace = selected
        self.nav_stack.append(MenuLevel.NAMESPACE)
        return True

    def push_nav_history(self, level: MenuLevel, context: str = "") -> None:
        """Push a navigation state to history"""
        self.nav_history.append((level, context))

    def pop_nav_history(self) -> Optional[Tuple[MenuLevel, str]]:
        """Pop the last navigation state from history"""
        return self.nav_history.pop() if self.nav_history else None

    def handle_resource_type_selection(self) -> bool:
        """Resource type selection menu"""
        # Get standard resource types and add CRDs
        types = STANDARD_RESOURCE_TYPES.copy()
        crds = self.get_crds()
        if crds:
            types.append("CustomResourceDefinitions")
        
        selected = self.run_fzf("Resource Type", types)

        if selected is None:
            return False

        if selected == "CustomResourceDefinitions":
            # Show the list of CRDs
            selected = self.run_fzf("Custom Resource Definition", self.cached_crds)
            if selected is None:
                return False
            self.is_crd_mode = True  # We're now in CRD mode
            self.current_resource_type = selected
            self.nav_stack.append(MenuLevel.RESOURCE_TYPE)
            self.push_nav_history(MenuLevel.RESOURCE_TYPE, "CustomResourceDefinitions")
            return True
        else:
            # For non-CRD resources
            self.current_resource_type = selected
            self.nav_stack.append(MenuLevel.RESOURCE_TYPE)
            self.push_nav_history(MenuLevel.RESOURCE_TYPE, selected)
            return True

    def get_resources(self, resource_type: str, namespace: str) -> List[str]:
        """Get resources in name format"""
        # If we're showing the CRD list, use the cached CRDs
        if resource_type == "CustomResourceDefinitions":
            return self.get_crds()

        args = ["kubectl", "get", resource_type, "-n", namespace, "-o", "name"]

        try:
            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
            resources = []
            for line in result.stdout.splitlines():
                name = line.decode().strip().split("/")[-1]
                # For CRDs, clean up the name
                if resource_type in self.get_crds() and "." in name:
                    name = name.split(".")[0]
                resources.append(name)
            return resources
        except subprocess.CalledProcessError as e:
            print(f"\n⚠️ Error getting resources: {e.stderr.decode()}", file=sys.stderr)
            return []

    def handle_resource_selection(self) -> bool:
        """Resource selection with fixed describe command"""
        # If we're in CRD mode and pressing escape, go back to CRD list
        if self.is_crd_mode and self.current_resource_type == "CustomResourceDefinitions":
            self.is_crd_mode = False
            return False

        resources = self.get_resources(self.current_resource_type, self.current_namespace)
        
        if not resources:
            preview = f"echo 'No {self.current_resource_type} resources found in namespace {self.current_namespace}'"
        else:
            preview = f"kubectl describe {self.current_resource_type}/{{}} -n {self.current_namespace} 2>/dev/null || echo 'No description available'"
        
        selected = self.run_fzf(self.current_resource_type, resources, preview)

        if selected is None:
            # Check our navigation history
            last_nav = self.pop_nav_history()
            if last_nav and last_nav[0] == MenuLevel.RESOURCE_TYPE:
                if last_nav[1] == "CustomResourceDefinitions":
                    # If we came from CRD list, go back there
                    self.current_resource_type = "CustomResourceDefinitions"
                    # Show the CRD list again
                    selected = self.run_fzf("Custom Resource Definition", self.cached_crds)
                    if selected is None:
                        return False
                    self.current_resource_type = selected
                    self.push_nav_history(MenuLevel.RESOURCE_TYPE, "CustomResourceDefinitions")
                    return True
                else:
                    # For non-CRD resources, go back to resource type selection
                    return False
            return False

        self.current_resource = f"{self.current_resource_type}/{selected}"
        self.nav_stack.append(MenuLevel.RESOURCE)
        self.push_nav_history(MenuLevel.RESOURCE, self.current_resource)
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
            # When pressing escape, go back to resource list
            self.nav_stack.pop()  # Remove the current level
            # Don't clear the resource selection memory when going back
            return False

        # Execute the action and stay in the action menu
        self.execute_action(selected)
        return True

    def get_service_ports(self, service_name: str, namespace: str) -> List[str]:
        """Get list of ports from a service"""
        try:
            # Get ports and names in a single command
            result = subprocess.run(
                ["kubectl", "get", "service", service_name, "-n", namespace, 
                 "-o", "jsonpath={.spec.ports[*].port}:{.spec.ports[*].name}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
            output = result.stdout.decode().strip()
            if not output:
                return []
            
            ports, names = output.split(":")
            return [f"{port} ({name})" if name else port 
                   for port, name in zip(ports.split(), names.split())]
        except subprocess.CalledProcessError:
            return []

    def execute_action(self, action: str) -> None:
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
                service_name = self.current_resource.split("/")[-1]
                ports = self.get_service_ports(service_name, self.current_namespace)
                
                if not ports:
                    print("\n⚠️ No ports found for this service", file=sys.stderr)
                    return
                
                selected_port = self.run_fzf("Target Port", ports)
                if not selected_port:
                    return
                
                target_port = selected_port.split()[0]
                lport = input("Local port: ")
                if not lport:
                    return
                
                # Run port-forward
                subprocess.run(
                    ["kubectl", "port-forward", "-n", self.current_namespace,
                     self.current_resource, f"{lport}:{target_port}"],
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
                elif current_level == MenuLevel.RESOURCE_TYPE:
                    if not self.handle_resource_selection():
                        self.nav_stack.pop()
                elif current_level == MenuLevel.RESOURCE:
                    if not self.handle_action_selection():
                        # Action selection already popped the stack
                        self.nav_stack.append(MenuLevel.RESOURCE_TYPE)
                else:
                    break
            except KeyboardInterrupt:
                print("\nOperation cancelled")
                break

if __name__ == "__main__":
    KubeExplorer().run()
