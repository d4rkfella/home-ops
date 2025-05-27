#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase
import sys

class DeploymentManager(KubeBase):
    resource_type = "deployments"
    resource_name = "Deployment"

    def get_deployment_bindings(self) -> Tuple[List[str], str]:
        deployment_bindings = [
            "--bind", "alt-s:accept",
            "--bind", "alt-r:accept",
            "--bind", "alt-h:accept",
            "--bind", "alt-u:accept",
            "--bind", "alt-t:accept",
            "--bind", "enter:ignore"
        ]
        deployment_header = "Alt-S: Scale | Alt-R: Rolling Restart | Alt-H: History | Alt-U: Undo | Alt-T: Rollout Status"
        return deployment_bindings, deployment_header

    def select_resource(self) -> Tuple[Optional[str], Optional[str]]:
        deployments = self.refresh_resources(self.current_namespace)
        if not deployments:
            print(f"No deployments found in namespace {self.current_namespace}")
            return "esc", None

        bindings, header = self.get_deployment_bindings()

        result = self.run_fzf(
            deployments,
            f"Deployments ({self.current_namespace})",
            extra_bindings=bindings,
            header=header,
            expect="esc,alt-s,alt-r,alt-t,alt-h,alt-u"
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

            key, deployment = self.select_resource()
            if key == "esc" or deployment is None:
                self.current_namespace = None
                continue
            elif key == "alt-s":
                 self.scale_deployment(deployment)
            elif key == "alt-r":
                 self.rolling_restart_deployment(deployment)
            elif key == "alt-h":
                 self.rollout_history(deployment)
            elif key == "alt-u":
                 self.undo_rollout(deployment)
            elif key == "alt-t":
                 self.rollout_status(deployment)

    def rolling_restart_deployment(self, deployment_name: str):
        print(f"Attempting to restart deployment {deployment_name} in namespace {self.current_namespace}...")
        try:
            result = subprocess.run(
                ["kubectl", "rollout", "restart", "deployment", deployment_name, "-n", self.current_namespace],
                capture_output=True, text=True, check=True
            )
            subprocess.run(["clear"])
            print(result.stdout.strip())
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error restarting deployment: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            subprocess.run(["clear"])
            print("\nRolling restart cancelled by user.", file=sys.stderr)
            input("\nPress Enter to continue...")

    def rollout_history(self, deployment_name: str):
        print(f"Showing rollout history for deployment {deployment_name} in namespace {self.current_namespace}")
        try:
            subprocess.run(["clear"])
            subprocess.run(
                ["kubectl", "rollout", "history", "deployment", deployment_name, "-n", self.current_namespace],
                check=True
            )
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error fetching rollout history: {e}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            subprocess.run(["clear"])
            print("\nRollout history cancelled by user.", file=sys.stderr)
            input("\nPress Enter to continue...")

    def rollout_status(self, deployment_name: str):
        print(f"Showing rollout status for deployment {deployment_name} in namespace {self.current_namespace}")
        try:
            subprocess.run(["clear"])
            subprocess.run(
                ["kubectl", "rollout", "status", "deployment", deployment_name, "-n", self.current_namespace],
                check=True
            )
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error fetching rollout status: {e}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            subprocess.run(["clear"])
            print("\nRollout status cancelled by user.", file=sys.stderr)
            input("\nPress Enter to continue...")

    def undo_rollout(self, deployment_name: str):
        print(f"Fetching rollout history for {deployment_name} in namespace {self.current_namespace}...")
        try:
            history_result = subprocess.run(
                ["kubectl", "rollout", "history", "deployment", deployment_name, "-n", self.current_namespace],
                capture_output=True, text=True, check=True
            )
            history_lines = history_result.stdout.strip().splitlines()

            if not history_lines:
                subprocess.run(["clear"])
                print(f"No rollout history found for deployment {deployment_name}.")
                input("\nPress Enter to continue...")
                return

            subprocess.run(["clear"])
            print("Select a revision to undo to:")

            revisions = []
            for line in history_lines:
                parts = line.split(None, 1)
                if len(parts) >= 1 and parts[0].isdigit():
                    revisions.append(line)

            if not revisions:
                subprocess.run(["clear"])
                print(f"Could not parse revisions from history for {deployment_name}.")
                input("\nPress Enter to continue...")
                return

            fzf_items = ["<Previous Revision>"] + revisions
            
            revision_result = self.run_fzf(
                fzf_items,
                f"Undo Rollout ({deployment_name})",
                header="Select revision to undo to (Esc to cancel)",
                use_common_bindings=False,
                expect="esc,enter"
            )

            if revision_result is None or (isinstance(revision_result, tuple) and revision_result[0] == "esc"):
                subprocess.run(["clear"])
                print("Undo rollout cancelled.")
                input("\nPress Enter to continue...")
                return

            selected_key, selected_line = revision_result if isinstance(revision_result, tuple) else ("enter", revision_result)

            if selected_key == "enter":
                undo_command = ["kubectl", "rollout", "undo", "deployment", deployment_name, "-n", self.current_namespace]

                if selected_line != "<Previous Revision>":
                    try:
                        revision_number = int(selected_line.split(None, 1)[0])
                        undo_command.extend(["--to-revision", str(revision_number)])
                    except (ValueError, IndexError):
                        subprocess.run(["clear"])
                        print(f"Error parsing revision number from: {selected_line}", file=sys.stderr)
                        input("\nPress Enter to continue...")
                        return

                subprocess.run(["clear"])
                print(f"Executing undo rollout for {deployment_name}...")
                try:
                    undo_result = subprocess.run(
                        undo_command,
                        capture_output=True, text=True, check=True
                    )
                    print(undo_result.stdout.strip())
                    input("\nPress Enter to continue...")
                except subprocess.CalledProcessError as e:
                    subprocess.run(["clear"])
                    print(f"Error executing undo rollout: {e.stderr.strip()}", file=sys.stderr)
                    input("\nPress Enter to continue...")
                except KeyboardInterrupt:
                    subprocess.run(["clear"])
                    print("\nUndo rollout command cancelled.", file=sys.stderr)
                    input("\nPress Enter to continue...")

            else:
                subprocess.run(["clear"])
                print(f"Unexpected key pressed: {selected_key}")
                input("\nPress Enter to continue...")

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error fetching rollout history: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            subprocess.run(["clear"])
            print("\nRollout history fetch cancelled.", file=sys.stderr)
            input("\nPress Enter to continue...")

    def scale_deployment(self, deployment_name: str):
        print(f"Attempting to scale deployment {deployment_name} in namespace {self.current_namespace}...")
        try:
            replica_count_str = input(f"Enter desired replica count for {deployment_name}: ")
            replica_count = int(replica_count_str)

            if replica_count < 0:
                subprocess.run(["clear"])
                print("Replica count cannot be negative.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return

            print(f"Scaling {deployment_name} to {replica_count} replicas...")
            result = subprocess.run(
                ["kubectl", "scale", "deployment", deployment_name, f"--replicas={replica_count}", "-n", self.current_namespace],
                capture_output=True, text=True, check=True
            )
            subprocess.run(["clear"])
            print(result.stdout.strip())
            input("\nPress Enter to continue...")

        except ValueError:
            subprocess.run(["clear"])
            print("Invalid input. Please enter a number.", file=sys.stderr)
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error scaling deployment: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            subprocess.run(["clear"])
            print("\nScaling cancelled by user.", file=sys.stderr)
            input("\nPress Enter to continue...")
 