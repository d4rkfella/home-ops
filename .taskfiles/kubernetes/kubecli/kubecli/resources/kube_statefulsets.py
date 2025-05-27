#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase
import sys

class StatefulSetManager(KubeBase):
    resource_type = "statefulsets"
    resource_name = "StatefulSet"

    def get_statefulset_bindings(self) -> Tuple[List[str], str]:
        statefulset_specific_bindings = [
            "--bind", "alt-r:accept", # Alt-R: Rolling Restart
            "--bind", "alt-h:accept", # Alt-H: Rollout History
            "--bind", "alt-u:accept", # Alt-U: Undo Rollout
            "--bind", "alt-t:accept", # Alt-T: Rollout Status
            "--bind", "enter:ignore"  # Ignore Enter key press
        ]

        statefulset_header = "Alt-R: Rolling Restart | Alt-H: History | Alt-U: Undo | Alt-T: Rollout Status"
        
        return statefulset_specific_bindings, statefulset_header

    def select_resource(self) -> Tuple[Optional[str], Optional[str]]:
        statefulsets = self.refresh_resources(self.current_namespace)
        if not statefulsets:
            subprocess.run(["clear"])
            print(f"No statefulsets found in namespace {self.current_namespace}", file=sys.stderr)
            input("\nPress Enter to continue...")
            return "esc", None

        bindings, header = self.get_statefulset_bindings()

        result = self.run_fzf(
            statefulsets,
            f"StatefulSets ({self.current_namespace})",
            extra_bindings=bindings,
            header=header,
            expect="esc,alt-d,alt-w,alt-v,alt-x,alt-e,alt-r,alt-h,alt-u,alt-t"
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

            key, statefulset = self.select_resource()
            if key == "esc" or statefulset is None:
                self.current_namespace = None
                continue
            elif key == "alt-r":
                 self.rolling_restart_statefulset(statefulset)
            elif key == "alt-h":
                 self.rollout_history(statefulset)
            elif key == "alt-u":
                 self.undo_rollout(statefulset)
            elif key == "alt-t":
                 self.rollout_status(statefulset)

    def rolling_restart_statefulset(self, statefulset_name: str):
        subprocess.run(["clear"])
        print(f"Attempting to restart statefulset {statefulset_name} in namespace {self.current_namespace}...")
        try:
            result = subprocess.run(
                ["kubectl", "rollout", "restart", "statefulset", statefulset_name, "-n", self.current_namespace],
                capture_output=True, text=True, check=True
            )
            subprocess.run(["clear"])
            print(result.stdout.strip())
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error restarting statefulset: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()

    def rollout_history(self, statefulset_name: str):
        subprocess.run(["clear"])
        print(f"Showing rollout history for statefulset {statefulset_name} in namespace {self.current_namespace}")
        try:
            subprocess.run(
                ["kubectl", "rollout", "history", "statefulset", statefulset_name, "-n", self.current_namespace],
                check=True
            )
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error fetching rollout history: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()

    def undo_rollout(self, statefulset_name: str):
        subprocess.run(["clear"])
        print(f"Fetching rollout history for {statefulset_name} in namespace {self.current_namespace}...")
        try:
            history_result = subprocess.run(
                ["kubectl", "rollout", "history", "statefulset", statefulset_name, "-n", self.current_namespace],
                capture_output=True, text=True, check=True
            )
            history_lines = history_result.stdout.strip().splitlines()

            if not history_lines:
                subprocess.run(["clear"])
                print(f"No rollout history found for statefulset {statefulset_name}.")
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
                print(f"Could not parse revisions from history for {statefulset_name}.")
                input("\nPress Enter to continue...")
                return

            fzf_items = ["<Previous Revision>"] + revisions
            
            revision_result = self.run_fzf(
                fzf_items,
                f"Undo Rollout ({statefulset_name})",
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
                undo_command = ["kubectl", "rollout", "undo", "statefulset", statefulset_name, "-n", self.current_namespace]

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
                print(f"Executing undo rollout for {statefulset_name}...")
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
                    return self.handle_keyboard_interrupt()

            else:
                subprocess.run(["clear"])
                print(f"Unexpected key pressed: {selected_key}")
                input("\nPress Enter to continue...")

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error fetching rollout history: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()

    def rollout_status(self, statefulset_name: str):
        subprocess.run(["clear"])
        print(f"Showing rollout status for statefulset {statefulset_name} in namespace {self.current_namespace}")
        try:
            subprocess.run(
                ["kubectl", "rollout", "status", "statefulset", statefulset_name, "-n", self.current_namespace],
                check=True
            )
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error fetching rollout status: {e}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()

    def scale_statefulset(self, statefulset_name: str):
        subprocess.run(["clear"])
        print(f"Current scale for statefulset {statefulset_name} in namespace {self.current_namespace}:")
        try:
            result = subprocess.run(
                ["kubectl", "get", "statefulset", statefulset_name, "-n", self.current_namespace, "-o", "jsonpath={.spec.replicas}"],
                capture_output=True, text=True, check=True
            )
            current_replicas = result.stdout.strip()
            print(f"Current replicas: {current_replicas}")
            
            new_replicas = input("\nEnter new number of replicas (or press Enter to cancel): ").strip()
            if not new_replicas:
                print("Operation cancelled.")
                input("\nPress Enter to continue...")
                return

            try:
                replicas = int(new_replicas)
                if replicas < 0:
                    print("Number of replicas must be non-negative.")
                    input("\nPress Enter to continue...")
                    return
            except ValueError:
                print("Please enter a valid integer.")
                input("\nPress Enter to continue...")
                return

            subprocess.run(
                ["kubectl", "scale", "statefulset", statefulset_name, f"--replicas={replicas}", "-n", self.current_namespace],
                check=True
            )
            print(f"Successfully scaled statefulset to {replicas} replicas")
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error scaling statefulset: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt() 