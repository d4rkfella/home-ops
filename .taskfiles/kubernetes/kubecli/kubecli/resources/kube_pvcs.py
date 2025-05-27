#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase
import sys
import time # Needed for waiting

class PVCManager(KubeBase):
    resource_type = "persistentvolumeclaims"
    resource_name = "PersistentVolumeClaim"

    def get_pvc_bindings(self) -> Tuple[List[str], str]:
        pvc_specific_bindings = [
            "--bind", "alt-f:accept",
            "--bind", "enter:ignore"
        ]

        pvc_header = "Alt-F: File Browser"

        return pvc_specific_bindings, pvc_header

    def select_resource(self) -> Tuple[Optional[str], Optional[str]]:
        pvcs = self.refresh_resources(self.current_namespace)
        if not pvcs:
            subprocess.run(["clear"])
            print(f"No persistentvolumeclaims found in namespace {self.current_namespace}", file=sys.stderr)
            input("\nPress Enter to continue...")
            return "esc", None

        bindings, header = self.get_pvc_bindings()

        result = self.run_fzf(
            pvcs,
            f"PersistentVolumeClaims ({self.current_namespace})",
            extra_bindings=bindings,
            header=header,
            expect="esc,alt-f"
        )
        if isinstance(result, tuple):
            return result
        else:
            return "esc", None

    def navigate(self):
        while True:
            if not self.current_namespace:
                key, ns = self.select_namespace()
                if key == "esc" or ns is None:
                    return
                self.current_namespace = ns

            key, pvc = self.select_resource()
            if key == "esc" or pvc is None:
                self.current_namespace = None
                continue
            elif key == "alt-f":
                 self.file_browser_pvc(pvc)

    def file_browser_pvc(self, pvc_name: str):
        subprocess.run(["clear"])
        print(f"Attempting to launch file browser for PVC {pvc_name} in namespace {self.current_namespace}...")

        pod_name = f"filebrowser-{pvc_name}"
        namespace = self.current_namespace

        try:
            check_cmd = ["kubectl", "get", "pod", pod_name, "-n", namespace, "--ignore-not-found", "-o", "name"]
            check_result = subprocess.run(check_cmd, capture_output=True, text=True, check=True)
            if check_result.stdout.strip():
                print(f"\nPod '{pod_name}' already exists in namespace '{namespace}'.")
                response = input("Delete existing pod and proceed? (y/N): ")
                if response.lower() == 'y':
                    print(f"Deleting existing pod '{pod_name}'...")
                    subprocess.run(["kubectl", "delete", "pod", pod_name, "-n", namespace, "--ignore-not-found"], check=True)
                    time.sleep(2)
                else:
                    print("Operation cancelled.")
                    input("\nPress Enter to continue...")
                    return
        except subprocess.CalledProcessError as e:
             subprocess.run(["clear"])
             print(f"Error checking for existing pod: {e.stderr.strip()}", file=sys.stderr)
             input("\nPress Enter to continue...")
             return
        except KeyboardInterrupt:
             subprocess.run(["clear"])
             print("\nOperation cancelled by user.", file=sys.stderr)
             input("\nPress Enter to continue...")
             return

        print(f"\n🚀 Deploying File Browser pod in namespace '{namespace}' with default credentials admin/admin...")

        run_cmd = [
            "kubectl", "run", pod_name,
            "--image=filebrowser/filebrowser",
            "--restart=Never",
            f"--namespace={namespace}",
            "--overrides={\"spec\":{\"hostUsers\":false,\"securityContext\":{\"runAsNonRoot\":true,\"runAsUser\":65532,\"runAsGroup\":65532,\"seccompProfile\":{\"type\":\"RuntimeDefault\"}},\"volumes\":[{\"name\":\"target-pvc\",\"persistentVolumeClaim\":{\"claimName\":\"" + pvc_name + "\"}},{\"name\":\"fb-data\",\"emptyDir\":{}}],\"containers\":[{\"name\":\"fb\",\"image\":\"filebrowser/filebrowser\",\"args\":[\"--database\",\"/data/filebrowser.db\"],\"ports\":[{\"containerPort\":80}],\"volumeMounts\":[{\"mountPath\":\"/srv\",\"name\":\"target-pvc\"},{\"mountPath\":\"/data\",\"name\":\"fb-data\"}],\"securityContext\":{\"readOnlyRootFilesystem\":true,\"allowPrivilegeEscalation\":false,\"capabilities\":{\"drop\":[\"ALL\"]}}}]}}"
        ]

        try:
            subprocess.run(run_cmd, check=True)
            print(f"Pod '{pod_name}' deployed.")

            print("\n⏳ Waiting for pod to be ready...")
            wait_cmd = ["kubectl", "wait", f"--for=condition=Ready", f"pod/{pod_name}", f"--namespace={namespace}", "--timeout=60s"]
            subprocess.run(wait_cmd, check=True)
            print(f"Pod '{pod_name}' is ready.")

            print("\n🌐 Starting port-forward to access File Browser UI at http://localhost:8080")
            print("Press Ctrl+C to stop the port-forward and clean up the pod.")
            port_forward_cmd = ["kubectl", "port-forward", f"pod/{pod_name}", "8080:80", f"--namespace={namespace}"]

            try:
                subprocess.run(port_forward_cmd)
            except KeyboardInterrupt:
                print("\nCtrl+C detected. Stopping port-forward and cleaning up...")

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"An error occurred during the process: {e.stderr.strip()}", file=sys.stderr)
        except KeyboardInterrupt:
             subprocess.run(["clear"])
             print("\nOperation cancelled by user.", file=sys.stderr)
        finally:
            print("\n🧹 Cleaning up pod...")
            subprocess.run(["kubectl", "delete", "pod", pod_name, "-n", namespace, "--ignore-not-found"])
            print("Cleanup complete.")
            input("\nPress Enter to continue...")
