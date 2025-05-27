#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase
import sys

class DaemonSetManager(KubeBase):
    resource_type = "daemonsets"
    resource_name = "DaemonSet"

    def get_daemonset_bindings(self) -> Tuple[List[str], str]:
        # Common bindings are handled by KubeBase and combined in run_fzf
        daemonset_specific_bindings = [
            "--bind", "alt-r:accept", # Alt-R: Rolling Restart
            "--bind", "alt-h:accept", # Alt-H: Rollout History
            "--bind", "alt-u:accept", # Alt-U: Undo Rollout
            "--bind", "alt-t:accept", # Alt-T: Rollout Status
            "--bind", "enter:ignore"  # Ignore Enter key press
        ]

        daemonset_header = "Alt-R: Rolling Restart | Alt-H: History | Alt-U: Undo | Alt-T: Rollout Status"
        
        return daemonset_specific_bindings, daemonset_header

    def select_resource(self) -> Tuple[Optional[str], Optional[str]]:
        daemonsets = self.refresh_resources(self.current_namespace)
        if not daemonsets:
            subprocess.run(["clear"])
            print(f"No daemonsets found in namespace {self.current_namespace}", file=sys.stderr)
            input("\nPress Enter to continue...")
            return "esc", None

        bindings, header = self.get_daemonset_bindings()

        result = self.run_fzf(
            daemonsets,
            f"DaemonSets ({self.current_namespace})",
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

            key, daemonset = self.select_resource()
            if key == "esc" or daemonset is None:
                self.current_namespace = None
                continue
            elif key == "alt-r":
                 self.rolling_restart_daemonset(daemonset)
            elif key == "alt-h":
                 self.rollout_history(daemonset)
            elif key == "alt-u":
                 self.undo_rollout(daemonset)
            elif key == "alt-t":
                 self.rollout_status(daemonset)

    def rolling_restart_daemonset(self, daemonset_name: str):
        subprocess.run(["clear"])
        print(f"Attempting to restart daemonset {daemonset_name} in namespace {self.current_namespace}...")
        try:
            result = subprocess.run(
                ["kubectl", "rollout", "restart", "daemonset", daemonset_name, "-n", self.current_namespace],
                capture_output=True, text=True, check=True
            )
            subprocess.run(["clear"])
            print(result.stdout.strip())
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error restarting daemonset: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()

    def rollout_history(self, daemonset_name: str):
        subprocess.run(["clear"])
        print(f"Showing rollout history for daemonset {daemonset_name} in namespace {self.current_namespace}")
        try:
            subprocess.run(
                ["kubectl", "rollout", "history", "daemonset", daemonset_name, "-n", self.current_namespace],
                check=True
            )
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error fetching rollout history: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()

    def undo_rollout(self, daemonset_name: str):
        subprocess.run(["clear"])
        print(f"Fetching rollout history for {daemonset_name} in namespace {self.current_namespace}...")
        try:
            history_result = subprocess.run(
                ["kubectl", "rollout", "history", "daemonset", daemonset_name, "-n", self.current_namespace],
                capture_output=True, text=True, check=True
            )
            history_lines = history_result.stdout.strip().splitlines()

            if not history_lines:
                subprocess.run(["clear"])
                print(f"No rollout history found for daemonset {daemonset_name}.")
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
                print(f"Could not parse revisions from history for {daemonset_name}.")
                input("\nPress Enter to continue...")
                return

            fzf_items = ["<Previous Revision>"] + revisions
            
            revision_result = self.run_fzf(
                fzf_items,
                f"Undo Rollout ({daemonset_name})",
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
                undo_command = ["kubectl", "rollout", "undo", "daemonset", daemonset_name, "-n", self.current_namespace]

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
                print(f"Executing undo rollout for {daemonset_name}...")
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

    def rollout_status(self, daemonset_name: str):
        subprocess.run(["clear"])
        print(f"Showing rollout status for daemonset {daemonset_name} in namespace {self.current_namespace}")
        try:
            subprocess.run(
                ["kubectl", "rollout", "status", "daemonset", daemonset_name, "-n", self.current_namespace],
                check=True
            )
            input("\nPress Enter to continue...")
        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error fetching rollout status: {e}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt() 