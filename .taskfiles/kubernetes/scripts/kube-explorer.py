#!/usr/bin/env python3
import subprocess
import sys
import signal
from enum import Enum
from typing import List, Optional
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import yaml

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
        
        # Initialize Kubernetes client
        try:
            config.load_kube_config()
            self.v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.helm_v1 = client.CustomObjectsApi()
        except Exception as e:
            print(f"Error initializing Kubernetes client: {e}")
            sys.exit(1)

    def handle_sigint(self, signum, frame):
        """Handle Ctrl+C by setting exit flag"""
        self.should_exit = True
        print("\nExiting...")
        sys.exit(0)

    def get_namespaces(self) -> List[str]:
        """Get list of namespaces using the Kubernetes API"""
        try:
            namespaces = self.v1.list_namespace()
            return ["all"] + [ns.metadata.name for ns in namespaces.items]
        except ApiException as e:
            print(f"Error getting namespaces: {e}")
            return ["all"]

    def get_resources(self, resource_type: str, namespace: str) -> List[str]:
        """Get resources using the Kubernetes API"""
        try:
            if resource_type == "pod":
                if namespace == "all":
                    pods = self.v1.list_pod_for_all_namespaces()
                    return [f"{pod.metadata.namespace}/{pod.metadata.name}" for pod in pods.items]
                else:
                    pods = self.v1.list_namespaced_pod(namespace)
                    return [pod.metadata.name for pod in pods.items]
            elif resource_type == "deployment":
                if namespace == "all":
                    deployments = self.apps_v1.list_deployment_for_all_namespaces()
                    return [f"{deploy.metadata.namespace}/{deploy.metadata.name}" for deploy in deployments.items]
                else:
                    deployments = self.apps_v1.list_namespaced_deployment(namespace)
                    return [deploy.metadata.name for deploy in deployments.items]
            elif resource_type == "service":
                if namespace == "all":
                    services = self.v1.list_service_for_all_namespaces()
                    return [f"{svc.metadata.namespace}/{svc.metadata.name}" for svc in services.items]
                else:
                    services = self.v1.list_namespaced_service(namespace)
                    return [svc.metadata.name for svc in services.items]
            elif resource_type == "helmrelease":
                if namespace == "all":
                    releases = self.helm_v1.list_cluster_custom_object(
                        group="helm.toolkit.fluxcd.io",
                        version="v2beta1",
                        plural="helmreleases"
                    )
                    return [f"{release['metadata']['namespace']}/{release['metadata']['name']}" for release in releases['items']]
                else:
                    releases = self.helm_v1.list_namespaced_custom_object(
                        group="helm.toolkit.fluxcd.io",
                        version="v2beta1",
                        namespace=namespace,
                        plural="helmreleases"
                    )
                    return [release['metadata']['name'] for release in releases['items']]
            elif resource_type == "statefulset":
                if namespace == "all":
                    statefulsets = self.apps_v1.list_stateful_set_for_all_namespaces()
                    return [f"{sts.metadata.namespace}/{sts.metadata.name}" for sts in statefulsets.items]
                else:
                    statefulsets = self.apps_v1.list_namespaced_stateful_set(namespace)
                    return [sts.metadata.name for sts in statefulsets.items]
            elif resource_type == "daemonset":
                if namespace == "all":
                    daemonsets = self.apps_v1.list_daemon_set_for_all_namespaces()
                    return [f"{ds.metadata.namespace}/{ds.metadata.name}" for ds in daemonsets.items]
                else:
                    daemonsets = self.apps_v1.list_namespaced_daemon_set(namespace)
                    return [ds.metadata.name for ds in daemonsets.items]
        except ApiException as e:
            print(f"Error getting {resource_type}s: {e}")
            return []

    def get_resource_description(self, resource_type: str, namespace: str, name: str) -> str:
        """Get resource description using the Kubernetes API"""
        try:
            if resource_type == "pod":
                pod = self.v1.read_namespaced_pod(name, namespace)
                return f"Name: {pod.metadata.name}\nNamespace: {pod.metadata.namespace}\nStatus: {pod.status.phase}\nIP: {pod.status.pod_ip}\nNode: {pod.spec.node_name}\n"
            elif resource_type == "deployment":
                deploy = self.apps_v1.read_namespaced_deployment(name, namespace)
                return f"Name: {deploy.metadata.name}\nNamespace: {deploy.metadata.namespace}\nReplicas: {deploy.spec.replicas}\nAvailable: {deploy.status.available_replicas}\n"
            # Add more resource types as needed
        except ApiException as e:
            return f"Error getting description: {e}"

    def get_resource_yaml(self, resource_type: str, namespace: str, name: str) -> str:
        """Get resource YAML using the Kubernetes API"""
        try:
            if resource_type == "pod":
                pod = self.v1.read_namespaced_pod(name, namespace)
                return yaml.dump(pod.to_dict())
            elif resource_type == "deployment":
                deploy = self.apps_v1.read_namespaced_deployment(name, namespace)
                return yaml.dump(deploy.to_dict())
            # Add more resource types as needed
        except ApiException as e:
            return f"Error getting YAML: {e}"

    def get_pod_logs(self, namespace: str, name: str) -> str:
        """Get pod logs using the Kubernetes API"""
        try:
            logs = self.v1.read_namespaced_pod_log(name, namespace, tail_lines=50)
            return logs
        except ApiException as e:
            return f"Error getting logs: {e}"

    def get_preview_command(self, resource_type: str, namespace: str = None) -> str:
        """Generate the appropriate preview command based on context"""
        if namespace is None:  # All namespaces mode
            return f"python3 -c 'import sys; ns, name = sys.argv[1].split(\"/\"); from kubernetes import client, config; config.load_kube_config(); v1 = client.CoreV1Api(); print(v1.read_namespaced_pod(name, ns).to_str())' {{}} 2>/dev/null || echo 'No description available'"
        else:  # Single namespace mode
            return f"python3 -c 'import sys; from kubernetes import client, config; config.load_kube_config(); v1 = client.CoreV1Api(); print(v1.read_namespaced_pod(sys.argv[1], \"{namespace}\").to_str())' {{}} 2>/dev/null || echo 'No description available'"

    def get_yaml_command(self, resource_type: str, namespace: str = None) -> str:
        """Generate the appropriate YAML preview command based on context"""
        if namespace is None:  # All namespaces mode
            return f"python3 -c 'import sys; ns, name = sys.argv[1].split(\"/\"); from kubernetes import client, config; import yaml; config.load_kube_config(); v1 = client.CoreV1Api(); print(yaml.dump(v1.read_namespaced_pod(name, ns).to_dict()))' {{}} 2>/dev/null || echo 'No YAML available'"
        else:  # Single namespace mode
            return f"python3 -c 'import sys; from kubernetes import client, config; import yaml; config.load_kube_config(); v1 = client.CoreV1Api(); print(yaml.dump(v1.read_namespaced_pod(sys.argv[1], \"{namespace}\").to_dict()))' {{}} 2>/dev/null || echo 'No YAML available'"

    def get_logs_command(self, resource_type: str, namespace: str = None) -> str:
        """Generate the appropriate logs preview command based on context"""
        if namespace is None:  # All namespaces mode
            return f"python3 -c 'import sys; ns, name = sys.argv[1].split(\"/\"); from kubernetes import client, config; config.load_kube_config(); v1 = client.CoreV1Api(); print(v1.read_namespaced_pod_log(name, ns, tail_lines=50))' {{}} 2>/dev/null || echo 'No logs available'"
        else:  # Single namespace mode
            return f"python3 -c 'import sys; from kubernetes import client, config; config.load_kube_config(); v1 = client.CoreV1Api(); print(v1.read_namespaced_pod_log(sys.argv[1], \"{namespace}\", tail_lines=50))' {{}} 2>/dev/null || echo 'No logs available'"

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
            "--preview-window=right:50%:wrap",
            "--color=fg:#d0d0d0,bg:#1b1b1b,hl:#00afff",
            "--color=fg+:#ffffff,bg+:#005f87,hl+:#00afff",
            "--color=info:#87ffaf,prompt:#ff5f00,pointer:#af00ff",
            "--bind", "ctrl-d:preview-page-down",
            "--bind", "ctrl-u:preview-page-up",
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
                    "--bind", f"ctrl-y:preview({self.get_yaml_command(self.current_resource_type)})"
                ])
            else:
                preview_bindings.extend([
                    "--bind", f"ctrl-y:preview({self.get_yaml_command(self.current_resource_type, self.current_namespace)})"
                ])

            # Add logs preview for pods
            if self.current_resource_type == "pod":
                if self.is_all_namespaces:
                    preview_bindings.extend([
                        "--bind", f"ctrl-l:preview({self.get_logs_command(self.current_resource_type)})"
                    ])
                else:
                    preview_bindings.extend([
                        "--bind", f"ctrl-l:preview({self.get_logs_command(self.current_resource_type, self.current_namespace)})"
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
                # Only test the command if we have a namespace/name pair
                namespace, name = selected.split("/")
                print(f"\nSelected resource: namespace={namespace}, name={name}")
                print(self.test_kubectl_command(namespace, self.current_resource_type, name))

            return selected

        except subprocess.CalledProcessError as e:
            if e.returncode == 130:
                return None
            raise

    def test_kubectl_command(self, namespace: str, resource_type: str, name: str) -> str:
        """Test a resource using the Kubernetes API"""
        try:
            if resource_type == "pod":
                pod = self.v1.read_namespaced_pod(name, namespace)
                return yaml.dump(pod.to_dict())
            elif resource_type == "deployment":
                deploy = self.apps_v1.read_namespaced_deployment(name, namespace)
                return yaml.dump(deploy.to_dict())
            elif resource_type == "service":
                svc = self.v1.read_namespaced_service(name, namespace)
                return yaml.dump(svc.to_dict())
            elif resource_type == "helmrelease":
                release = self.helm_v1.get_namespaced_custom_object(
                    group="helm.toolkit.fluxcd.io",
                    version="v2beta1",
                    namespace=namespace,
                    plural="helmreleases",
                    name=name
                )
                return yaml.dump(release)
            elif resource_type == "statefulset":
                sts = self.apps_v1.read_namespaced_stateful_set(name, namespace)
                return yaml.dump(sts.to_dict())
            elif resource_type == "daemonset":
                ds = self.apps_v1.read_namespaced_daemon_set(name, namespace)
                return yaml.dump(ds.to_dict())
        except ApiException as e:
            return f"Error: {e}"

    def handle_namespace_selection(self) -> bool:
        """Namespace selection with proper preview"""
        namespaces = self.get_namespaces()
        preview = "kubectl get pods -n {} -o wide 2>/dev/null || echo 'No pods in namespace'"
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
            preview = self.get_preview_command(self.current_resource_type)
            print(f"\nDebug - All namespaces preview command: {preview}")
        else:
            preview = self.get_preview_command(self.current_resource_type, self.current_namespace)
            print(f"\nDebug - Single namespace preview command: {preview}")
        selected = self.run_fzf(self.current_resource_type, resources, preview)

        if selected is None:
            return False

        if self.is_all_namespaces:
            namespace, name = selected.split("/")
            print(f"\nDebug - Selected resource in all namespaces: namespace={namespace}, name={name}")
            self.current_namespace = namespace
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
        """Execute action using the Kubernetes API"""
        try:
            if action == "edit":
                # For edit, we still need to use kubectl as the Python client doesn't support interactive editing
                subprocess.run(
                    ["kubectl", "edit", self.current_resource, "-n", self.current_namespace],
                    check=True
                )
            elif action == "delete":
                if self.current_resource_type == "pod":
                    self.v1.delete_namespaced_pod(
                        name=self.current_resource.split("/")[-1],
                        namespace=self.current_namespace
                    )
                elif self.current_resource_type == "deployment":
                    self.apps_v1.delete_namespaced_deployment(
                        name=self.current_resource.split("/")[-1],
                        namespace=self.current_namespace
                    )
                elif self.current_resource_type == "service":
                    self.v1.delete_namespaced_service(
                        name=self.current_resource.split("/")[-1],
                        namespace=self.current_namespace
                    )
                elif self.current_resource_type == "helmrelease":
                    self.helm_v1.delete_namespaced_custom_object(
                        group="helm.toolkit.fluxcd.io",
                        version="v2beta1",
                        namespace=self.current_namespace,
                        plural="helmreleases",
                        name=self.current_resource.split("/")[-1]
                    )
                elif self.current_resource_type == "statefulset":
                    self.apps_v1.delete_namespaced_stateful_set(
                        name=self.current_resource.split("/")[-1],
                        namespace=self.current_namespace
                    )
                elif self.current_resource_type == "daemonset":
                    self.apps_v1.delete_namespaced_daemon_set(
                        name=self.current_resource.split("/")[-1],
                        namespace=self.current_namespace
                    )
            elif action == "exec":
                # For exec, we still need to use kubectl as the Python client doesn't support interactive sessions
                resource_name = self.current_resource.split("/")[-1]
                subprocess.run(
                    ["kubectl", "exec", "-it", resource_name, "-n", self.current_namespace, "--", "/bin/sh"],
                    check=True
                )
            elif action == "port-forward":
                # For port-forward, we still need to use kubectl as the Python client doesn't support port forwarding
                lport = input("Local port: ")
                tport = input("Target port: ")
                subprocess.run(
                    ["kubectl", "port-forward", "-n", self.current_namespace,
                     self.current_resource, f"{lport}:{tport}"],
                    check=True
                )
        except ApiException as e:
            print(f"\n⚠️ Command failed with error: {e}", file=sys.stderr)
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
