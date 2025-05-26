#!/usr/bin/env python3
import subprocess
from typing import List
from kubecli.resources.kube_base import KubeBase

class PodManager(KubeBase):
    resource_type = "pods"
    resource_name = "Pod"

    def get_pod_bindings(self) -> (List[str], str):
        pod_bindings = [
            "--preview-window=right:60%",
            "--bind", f"alt-l:preview(kubectl logs {{}} -n {self.current_namespace} --tail=100)",
            "--bind", f"alt-c:execute(kubectl exec -it {{}} -n {self.current_namespace} -- /bin/bash)"
        ]
        pod_label = "Alt-L:Logs Preview | Alt-C:Exec Shell"
        return pod_bindings, pod_label

    def run(self):
        while True:
            if not self.current_namespace:
                ns = self.select_namespace()
                if not ns:
                    print("No namespace selected, exiting.")
                    return
                self.current_namespace = ns

            pods = self.refresh_resources(self.current_namespace)
            if not pods:
                print(f"No pods found in namespace {self.current_namespace}")
                self.current_namespace = None
                continue

            pod_bindings, pod_label = self.get_pod_bindings()

            selected = self.run_fzf(
                pods,
                f"Pods ({self.current_namespace})",
                extra_bindings=pod_bindings,
                header=pod_label
            )

            if selected:
                print(f"Selected pod: {selected}")
                break
            else:
                print("No pod selected or action aborted")
                break
