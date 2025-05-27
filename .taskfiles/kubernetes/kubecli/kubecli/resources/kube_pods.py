#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase

class PodManager(KubeBase):
    resource_type = "pods"
    resource_name = "Pod"

    def get_pod_bindings(self) -> Tuple[List[str], str]:
        pod_bindings = [
            "--bind", f"alt-l:change-preview(kubectl logs {{1}} -n {self.current_namespace} --all-containers)+change-preview-window(hidden|right:60%:wrap)",
            "--bind", "alt-c:accept",
            "--bind", "enter:ignore"
        ]
        pod_header = "Alt-L: Logs Preview | Alt-C: Exec Shell"
        return pod_bindings, pod_header

    def select_resource(self) -> Tuple[Optional[str], Optional[str]]:
        pods = self.refresh_resources(self.current_namespace)
        if not pods:
            print(f"No pods found in namespace {self.current_namespace}")
            input("\nPress Enter to continue...")
            return "esc", None

        bindings, header = self.get_pod_bindings()

        result = self.run_fzf(
            pods,
            "Pods",
            extra_bindings=bindings,
            header=header,
            expect="esc,alt-c"
        )
        if isinstance(result, tuple):
            return result
        else:
            return "esc", None

    def try_shells(self, pod_name, container, namespace):
        shells = ["bash", "sh", "ash"]
        for shell in shells:
            print(f"Trying shell '{shell}' in pod '{pod_name}', container '{container}'...")
            result = subprocess.run(
                ["kubectl", "exec", pod_name, "-n", namespace, "-c", container, "--", shell, "-c", "echo Shell OK"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                subprocess.run(
                    ["kubectl", "exec", "-it", pod_name, "-n", namespace, "-c", container, "--", shell]
                )
                return
        print("No suitable shell found in the container.")

    def exec_pod_via_fzf(self, pod_name: str):
        try:
            result = subprocess.run(
                ["kubectl", "get", "pod", pod_name, "-n", self.current_namespace, "-o", "jsonpath={.spec.containers[*].name}"],
                capture_output=True, text=True, check=True
            )
            containers = result.stdout.strip().split()
        except subprocess.CalledProcessError as e:
            print(f"Error fetching containers: {e.stderr}")
            return

        if not containers:
            print(f"No containers found in pod {pod_name}")
            return

        container = containers[0]
        if len(containers) > 1:
            key, container = self.run_fzf(containers, "Container", expect="esc,enter")
            if key == "esc" or container is None:
                print("No container selected, returning.")
                return

        print(f"Starting shell in pod '{pod_name}', container '{container}'...")
        self.try_shells(pod_name, container, self.current_namespace)

    def navigate(self):
        while True:
            if not self.current_namespace:
                key, ns = self.select_namespace()
                if key == "esc" or ns is None:
                    return
                self.current_namespace = ns

            key, pod = self.select_resource()
            if key == "esc" or pod is None:
                self.current_namespace = None
                continue
            elif key == "alt-c":
                self.exec_pod_via_fzf(pod)
