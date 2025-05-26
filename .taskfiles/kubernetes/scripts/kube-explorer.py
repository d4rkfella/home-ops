#!/usr/bin/env python3
import subprocess
import sys
import signal
from enum import Enum
from typing import List, Optional, Dict, Tuple
import json

class MenuLevel(Enum):
    NAMESPACE = 1
    RESOURCE_TYPE = 2
    RESOURCE = 3

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
        self.current_namespace: str = ""
        self.current_resource_type: str = ""
        self.current_resource: str = ""
        self.is_all_namespaces: bool = False
        self.cached_crds: Optional[List[str]] = None
        self.is_crd_mode: bool = False
        signal.signal(signal.SIGINT, self.handle_sigint)
        self.should_exit: bool = False
        # Cache CRDs on startup
        self.cache_crds()

    def handle_sigint(self, signum, frame):
        """Handle Ctrl+C by setting exit flag"""
        self.should_exit = True
        print("\nExiting...")
        sys.exit(0)

    def cache_crds(self):
        """Cache the list of available CRDs"""
        try:
            # Get CRDs with their scope information
            result = subprocess.run(
                ["kubectl", "get", "crd", "-o", "json"],
                capture_output=True,
                text=True,
                check=True
            )
            
            # Parse the JSON output
            crds_data = json.loads(result.stdout)
            namespaced_crds = []
            
            # Extract namespaced CRDs
            for crd in crds_data.get('items', []):
                if crd.get('spec', {}).get('scope') == 'Namespaced':
                    namespaced_crds.append(crd['spec']['names']['plural'])
            
            self.cached_crds = namespaced_crds
            print(f"Cached {len(namespaced_crds)} namespaced CRDs", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(f"Error caching CRDs: {e}")
            self.cached_crds = []
        except json.JSONDecodeError as e:
            print(f"Error parsing CRD data: {e}")
            self.cached_crds = []

    def get_preview_bindings(self) -> Tuple[List[str], str]:
        """Get preview bindings for the current resource type"""
        preview_bindings = []
        preview_label = "[Alt-D] describe | [Alt-Y] yaml"
        
        # Common preview bindings for all resources
        preview_bindings.extend([
            "--bind", f"alt-d:preview(kubectl describe {self.current_resource_type}/{{}} -n {self.current_namespace} 2>/dev/null || echo 'No description available')",
            "--bind", f"alt-y:preview(kubectl get {self.current_resource_type}/{{}} -n {self.current_namespace} -o yaml 2>/dev/null || echo 'No YAML available')"
        ])

        # Resource-specific preview bindings
        if self.current_resource_type == "pod":
            logs_cmd = f"kubectl logs --all-containers --follow --tail=100 {self.current_resource_type}/{{}} -n {self.current_namespace} 2>/dev/null || echo 'No logs available'"
            preview_bindings.extend([
                "--bind", f"alt-l:preview({logs_cmd})"
            ])
            preview_label += " | [Alt-L] logs"

        return preview_bindings, preview_label

    def get_command_bindings(self) -> Tuple[List[str], str]:
        """Get command bindings and label based on resource type"""
        cmd_bindings = []
        label = ""

        # Common command bindings for all resources
        cmd_bindings.extend([
            "--bind", f"alt-r:execute(kubectl get {self.current_resource_type} -n {self.current_namespace} -o name)+refresh-preview",
            "--bind", f"alt-x:execute(kubectl delete {self.current_resource_type} -n {self.current_namespace} {{}})+refresh-preview",
            "--bind", "alt-p:toggle-preview"  # Add toggle preview binding
        ])
        label += "[Alt-R] reload | [Alt-X] delete | [Alt-P] toggle preview"

        # Resource-specific command bindings
        if self.current_resource_type == "pod":
            cmd_bindings.extend([
                "--bind", f"alt-b:execute(echo -n {{}} | xclip -selection clipboard)+refresh-preview",
                "--bind", f"alt-e:execute(kubectl exec -it {self.current_resource_type}/{{}} -n {self.current_namespace} -- bash)"
            ])
            label += " | [Alt-E] exec | [Alt-B] copy name"

        elif self.current_resource_type == "deployment":
            cmd_bindings.extend([
                "--bind", f"alt-r:execute(kubectl rollout restart {self.current_resource_type}/{{}} -n {self.current_namespace})+refresh-preview"
            ])
            label += " | [Alt-R] restart"

        elif self.current_resource_type == "service":
            cmd_bindings.extend([
                "--bind", (
                    f"alt-f:execute("
                    f"target_port=$(kubectl get service {{}} -n {self.current_namespace} -o jsonpath='{{.spec.ports[*].port}}' | tr ' ' '\\n' | fzf --prompt='Select target port: ' {self.get_fzf_style()}); "
                    f"if [ -z \"$target_port\" ]; then exit; fi; "
                    f"local_port=$(seq 1 65535 | fzf --prompt='Select local port: ' {self.get_fzf_style()}); "
                    f"if [ -z \"$local_port\" ]; then exit; fi; "
                    f"kubectl port-forward {self.current_resource_type}/{{}} -n {self.current_namespace} $local_port:$target_port"
                    f")"
                )
            ])
            label += " | [Alt-F] port-forward"

        elif self.current_resource_type == "statefulset":
            cmd_bindings.extend([
                "--bind", f"alt-r:execute(kubectl rollout restart {self.current_resource_type}/{{}} -n {self.current_namespace})+refresh-preview"
            ])
            label += " | [Alt-R] restart"

        elif self.current_resource_type == "daemonset":
            cmd_bindings.extend([
                "--bind", f"alt-r:execute(kubectl rollout restart {self.current_resource_type}/{{}} -n {self.current_namespace})+refresh-preview"
            ])
            label += " | [Alt-R] restart"

        return cmd_bindings, label

    def get_fzf_style(self, level="main"):
        """Get consistent fzf styling"""
        history_file = f"/tmp/kube-explorer-{level}-history"
        style_options = [
            "--history-size=1000",
            f"--history={history_file}",
            "--layout=reverse",
            "--border=rounded",
            "--margin=1,2",
            "--preview-window=right:60%:wrap",
            "--bind", "ctrl-s:toggle-sort",
            "--bind", "ctrl-c:clear-query",
            "--bind", "ctrl-y:execute-silent(echo {} | xclip -selection clipboard)",
            "--bind", "ctrl-g:first",
            "--bind", "ctrl-l:last",
            "--bind", "ctrl-h:toggle-preview",
            "--bind", "esc:abort"
        ]
        
        # Add colors
        for key, value in FZF_COLORS.items():
            style_options.extend(["--color", f"{key}:{value}"])
            
        return style_options

    def run_fzf(self, items, prompt, level="main", preview_cmd=None):
        """Run fzf with consistent styling"""
        try:
            # Split the items into header and content
            lines = items.split('\n')
            header = lines[0] if lines else ""
            content = '\n'.join(lines[1:]) if len(lines) > 1 else ""
            
            # Build fzf command
            fzf_cmd = ["fzf"] + self.get_fzf_style(level) + [
                "--prompt", f"{prompt}> ",
                "--header", header
            ]
            
            # Add preview if provided
            if preview_cmd:
                fzf_cmd.extend(["--preview", preview_cmd])
            
            # Add command bindings and labels
            cmd_bindings, cmd_label = self.get_command_bindings()
            preview_bindings, preview_label = self.get_preview_bindings()
            
            fzf_cmd.extend(cmd_bindings)
            fzf_cmd.extend(preview_bindings)
            
            # Add header with all bindings
            fzf_cmd.extend([
                "--header-lines", "1",
                "--header-first",
                "--header", f"{header}\n[Enter] select | [ESC] back | {cmd_label} | {preview_label}"
            ])
            
            # Run fzf
            result = subprocess.run(
                fzf_cmd,
                input=content,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if e.returncode == 130:  # ESC pressed
                return None
            print(f"Error running fzf: {e}")
            return None

    def get_namespaces(self) -> List[str]:
        result = subprocess.run(
            ["kubectl", "get", "ns", "-o", "jsonpath={.items[*].metadata.name}"],
            stdout=subprocess.PIPE,
            check=True
        )
        return result.stdout.decode().strip().split()

    def get_crds(self) -> List[str]:
        """Get list of available Custom Resource Definitions"""
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

            self.cached_crds = crds
            return crds

        except subprocess.CalledProcessError as e:
            print(f"\nError loading CRDs: {e.stderr.decode()}", file=sys.stderr)
            return []

    def get_resources(self, resource_type: str, namespace: str) -> List[str]:
        """Get resources in name format"""
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
                if resource_type in self.get_crds() and "." in name:
                    name = name.split(".")[0]
                resources.append(name)
            return resources
        except subprocess.CalledProcessError as e:
            print(f"\n⚠️ Error getting resources: {e.stderr.decode()}", file=sys.stderr)
            return []

    def get_resource_types(self, namespace, show_crds=True):
        """Get available resource types for the namespace"""
        try:
            # Get all resources in the namespace
            result = subprocess.run(
                ["kubectl", "get", "all", "-n", namespace, "--no-headers", "-o", "name"],
                capture_output=True,
                text=True,
                check=True
            )
            
            # Get all resource types that exist in the namespace
            existing_resources = set()
            for line in result.stdout.strip().split("\n"):
                if line:
                    resource_type = line.split("/")[0]
                    existing_resources.add(resource_type)
            
            # Check which CRDs have resources in this namespace
            crd_resources = set()
            if show_crds and self.cached_crds:
                print(f"\nChecking {len(self.cached_crds)} cached CRDs for resources in namespace {namespace}", file=sys.stderr)
                # Use cached CRDs to check for resources
                for crd in self.cached_crds:
                    try:
                        check_result = subprocess.run(
                            ["kubectl", "get", crd, "-n", namespace, "--no-headers", "-o", "name"],
                            capture_output=True,
                            text=True,
                            check=True
                        )
                        if check_result.stdout.strip():
                            crd_resources.add(crd)
                    except subprocess.CalledProcessError:
                        continue
                print(f"Found {len(crd_resources)} CRDs with resources", file=sys.stderr)
            
            # Separate native resources and CRD resources
            native_resources = sorted(r for r in existing_resources if r not in crd_resources)
            crd_resources_list = sorted(crd_resources) if show_crds else []
            
            # Combine resources with native resources first
            all_resources = native_resources + crd_resources_list
            
            # Add header with toggle info
            header = f"Resource Types (Ctrl-H to {'hide' if show_crds else 'show'} CRDs)"
            return header + "\n" + "\n".join(all_resources)
        except subprocess.CalledProcessError as e:
            print(f"Error getting resource types: {e}")
            return ""

    def run(self):
        """Main navigation loop"""
        show_crds = True  # Track CRD visibility state
        
        while True:
            try:
                # Start with namespace selection
                namespaces = self.get_namespaces()
                preview = "kubectl get pods -n {} 2>/dev/null || echo 'No pods in namespace'"
                selected = self.run_fzf(
                    "Namespaces\n" + "\n".join(namespaces),
                    "Namespace",
                    level="namespace",
                    preview_cmd=preview
                )
                if selected is None:
                    break
                self.current_namespace = selected

                while True:  # Resource type selection loop
                    selected = self.run_fzf(
                        self.get_resource_types(self.current_namespace, show_crds),
                        "Resource Type",
                        level="resource_type",
                        preview_cmd=f"kubectl get {{}} -n {self.current_namespace} -o wide"
                    )
                    if selected is None:
                        break  # Go back to namespace selection

                    # Handle Ctrl-H toggle
                    if selected == "Resource Types":
                        show_crds = not show_crds
                        continue

                    self.current_resource_type = selected

                    while True:  # Resource selection loop
                        resources = self.get_resources(self.current_resource_type, self.current_namespace)
                        if not resources:
                            preview = f"echo 'No {self.current_resource_type} resources found in namespace {self.current_namespace}'"
                        else:
                            preview = f"kubectl describe {self.current_resource_type}/{{}} -n {self.current_namespace} 2>/dev/null || echo 'No description available'"
                        
                        selected = self.run_fzf(
                            f"{self.current_resource_type} Resources\n" + "\n".join(resources),
                            self.current_resource_type,
                            level="resource",
                            preview_cmd=preview
                        )
                        if selected is None:
                            break  # Go back to resource type selection
                        
                        self.current_resource = f"{self.current_resource_type}/{selected}"

            except KeyboardInterrupt:
                print("\nOperation cancelled")
                break

if __name__ == "__main__":
    KubeExplorer().run()
