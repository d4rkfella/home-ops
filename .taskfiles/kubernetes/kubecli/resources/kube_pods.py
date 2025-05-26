#!/usr/bin/env python3
import subprocess
from typing import List
from kubecli.resources.kube_base import KubeBase

class PodManager(KubeBase):
    resource_type = "pods"
    resource_name = "Pod"

    def get_pod_bindings(self) -> (List[str], str):
        # Preview command switches based on the 'preview_type' variable inside fzf
        preview_cmd = (
            '[[ $(echo {}) = "" ]] && echo "No resource selected" || '
            'case $preview_type in '
            'logs) kubectl logs {} -n {} --tail=100 ;; '
            'describe) kubectl describe pod {} -n {} ;; '
            '*) echo "Unknown preview type" ;; '
            'esac'
        )

        # We inject the pod name twice (for logs and describe), and the namespace.
        # The '{}' will be replaced by fzf with the current line (pod name)
        preview_cmd = preview_cmd.format('{+}', '{+}', self.current_namespace, '{+}', self.current_namespace)

        pod_bindings = [
            # Default preview type = logs
            "--preview-window=right:60%",
            f"--preview={preview_cmd}",
            "--bind", "alt-l:reload-silent(echo {+})+change-preview-preview_type=logs",
            "--bind", "alt-d:reload-silent(echo {+})+change-preview-preview_type=describe",
            "--bind", f"alt-c:execute(kubectl exec -it {{}} -n {self.current_namespace} -- /bin/bash)"
        ]
        pod_label = "Alt-L:Logs Preview | Alt-D:Describe Preview | Alt-C:Exec Shell"
        return pod_bindings, pod_label

    def run(self):
        while True:
            # Select namespace if not set
            if not self.current_namespace:
                ns = self.select_namespace()
                if not ns:
                    print("No namespace selected, exiting.")
                    return
                self.current_namespace = ns

            # Refresh pod list in current namespace
            pods = self.refresh_resources(self.current_namespace)
            if not pods:
                print(f"No pods found in namespace {self.current_namespace}")
                self.current_namespace = None  # reset to allow user to pick again
                continue  # loop back to select namespace again

            pod_bindings, pod_label = self.get_pod_bindings()

            selected = self.run_fzf(
                pods,
                f"Pods ({self.current_namespace})",
                extra_bindings=pod_bindings
            )

            if selected:
                print(f"Selected pod: {selected}")
                # You can place further pod-specific logic here if needed
                break  # exit loop after selection
            else:
                print("No pod selected or action aborted")
                break  # exit loop if user cancels selection
