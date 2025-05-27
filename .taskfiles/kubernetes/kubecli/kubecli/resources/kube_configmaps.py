#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase
import sys

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
