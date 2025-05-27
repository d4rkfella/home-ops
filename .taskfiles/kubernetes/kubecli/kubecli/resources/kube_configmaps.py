#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase
import sys
import json

class ConfigMapManager(KubeBase):
    resource_type = "configmaps"
    resource_name = "ConfigMap"

    def get_configmap_bindings(self) -> Tuple[List[str], str]:
        configmap_bindings = [
            "--bind", "alt-c:accept",
            "--bind", "enter:ignore"
        ]
        configmap_header = "Alt-C: View Content"
        return configmap_bindings, configmap_header

    def select_resource(self) -> Tuple[Optional[str], Optional[str]]:
        configmaps = self.refresh_resources(self.current_namespace)
        if not configmaps:
            subprocess.run(["clear"])
            print(f"No configmaps found in namespace {self.current_namespace}", file=sys.stderr)
            input("\nPress Enter to continue...")
            return "esc", None

        bindings, header = self.get_configmap_bindings()

        result = self.run_fzf(
            configmaps,
            f"ConfigMaps ({self.current_namespace})",
            extra_bindings=bindings,
            header=header,
            expect="esc,alt-c"
        )
        if isinstance(result, tuple):
            return result
        else:
            return "esc", None

    def view_content(self, configmap_name: str):
        print(f"Fetching data for ConfigMap {configmap_name} in namespace {self.current_namespace}...")
        try:
            result = subprocess.run(
                ["kubectl", "get", "configmap", configmap_name, "-n", self.current_namespace, "-o=jsonpath={.data}"],
                capture_output=True, text=True, check=True
            )

            data_str = result.stdout.strip()

            subprocess.run(["clear"])
            print(f"Data for ConfigMap: {configmap_name}")
            print("-------------------------")

            if data_str and data_str != "{}":
                 try:
                     import json
                     data_dict = json.loads(data_str)
                     for key, value in data_dict.items():
                         print(f"{key}: {value}")
                 except (json.JSONDecodeError, Exception) as e:
                     print(f"Could not parse data JSON: {e}", file=sys.stderr)
                     print("Raw data output:")
                     print(data_str)

            else:
                print("No data found in this ConfigMap.")

            print("-------------------------")
            input("\nPress Enter to continue...")

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error fetching ConfigMap data: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            subprocess.run(["clear"])
            print("\nFetching data cancelled by user.", file=sys.stderr)
            input("\nPress Enter to continue...")

    def navigate(self):
        while True:
            if not self.current_namespace:
                key, ns = self.select_namespace()
                if key == "esc" or ns is None:
                    return
                self.current_namespace = ns

            key, configmap = self.select_resource()
            if key == "esc" or configmap is None:
                self.current_namespace = None
                continue
            elif key == "alt-c":
                 self.view_content(configmap)

    def edit_configmap(self, configmap_name: str):
        subprocess.run(["clear"])
        print(f"Editing configmap {configmap_name} in namespace {self.current_namespace}")
        try:
            # Get configmap details
            configmap_result = subprocess.run(
                ["kubectl", "get", "configmap", configmap_name, "-n", self.current_namespace, "-o", "json"],
                capture_output=True, text=True, check=True
            )
            configmap_data = json.loads(configmap_result.stdout)
            
            # Get data
            data = configmap_data.get('data', {})
            if not data:
                print("No data found in configmap.")
                input("\nPress Enter to continue...")
                return

            # Create key selection menu
            keys = list(data.keys())
            print("Select key to edit:")
            key_result = self.run_fzf(
                keys,
                f"Edit ConfigMap ({configmap_name})",
                header="Select key to edit (Esc to cancel)",
                use_common_bindings=False,
                expect="esc,enter"
            )

            if key_result is None or (isinstance(key_result, tuple) and key_result[0] == "esc"):
                subprocess.run(["clear"])
                print("Edit cancelled.")
                input("\nPress Enter to continue...")
                return

            selected_key, key = key_result if isinstance(key_result, tuple) else ("enter", key_result)
            if selected_key != "enter":
                subprocess.run(["clear"])
                print(f"Unexpected key pressed: {selected_key}")
                input("\nPress Enter to continue...")
                return

            # Get new value
            while True:
                try:
                    print(f"\nCurrent value for {key}:")
                    print(data[key])
                    new_value = input("\nEnter new value (or press Enter to cancel): ").strip()
                    if not new_value:
                        print("Edit cancelled.")
                        input("\nPress Enter to continue...")
                        return
                    break
                except KeyboardInterrupt:
                    return self.handle_keyboard_interrupt()

            # Update configmap
            subprocess.run(["clear"])
            print(f"Updating configmap {configmap_name}...")
            try:
                subprocess.run(
                    ["kubectl", "patch", "configmap", configmap_name, "-n", self.current_namespace, "--patch", f'{{"data":{{"{key}":"{new_value}"}}}}'],
                    check=True
                )
                print("Configmap updated successfully.")
                input("\nPress Enter to continue...")
            except subprocess.CalledProcessError as e:
                subprocess.run(["clear"])
                print(f"Error updating configmap: {e.stderr.strip()}", file=sys.stderr)
                input("\nPress Enter to continue...")

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error getting configmap details: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except json.JSONDecodeError:
            subprocess.run(["clear"])
            print("Error parsing configmap details.", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()
