#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase
import sys
import base64
import json

class SecretManager(KubeBase):
    resource_type = "secrets"
    resource_name = "Secret"

    def get_secret_bindings(self) -> Tuple[List[str], str]:
        secret_bindings = [
            "--bind", "alt-c:accept",
            "--bind", "enter:ignore"
        ]
        secret_header = "Alt-C: View Content (CAUTION: Sensitive Data)"
        return secret_bindings, secret_header

    def select_resource(self) -> Tuple[Optional[str], Optional[str]]:
        secrets = self.refresh_resources(self.current_namespace)
        if not secrets:
            subprocess.run(["clear"])
            print(f"No secrets found in namespace {self.current_namespace}", file=sys.stderr)
            input("\nPress Enter to continue...")
            return "esc", None

        bindings, header = self.get_secret_bindings()

        result = self.run_fzf(
            secrets,
            f"Secrets ({self.current_namespace})",
            extra_bindings=bindings,
            header=header,
            expect="esc,alt-c"
        )
        if isinstance(result, tuple):
            return result
        else:
            return "esc", None

    def view_content(self, secret_name: str):
        print(f"Fetching data for Secret {secret_name} in namespace {self.current_namespace}...")
        try:
            # Get only the data field using jsonpath
            result = subprocess.run(
                ["kubectl", "get", "secret", secret_name, "-n", self.current_namespace, "-o=jsonpath={.data}"],
                capture_output=True, text=True, check=True
            )

            data_str = result.stdout.strip()

            subprocess.run(["clear"])
            print(f"Data for Secret: {secret_name} (Base64 Decoded)")
            print("-------------------------")

            if data_str and data_str != "{}": # Check if data is not empty JSON object
                try:
                    import json
                    import base64
                    data_dict = json.loads(data_str)
                    for key, encoded_value in data_dict.items():
                        try:
                            decoded_value_bytes = base64.b64decode(encoded_value.strip())
                            try:
                                decoded_value = decoded_value_bytes.decode("utf-8")
                            except UnicodeDecodeError:
                                decoded_value = str(decoded_value_bytes) # Represent bytes

                            print(f"{key}: {decoded_value}")
                        except base64.binascii.Error:
                            print(f"{key}: [UNDECODABLE or NOT BASE64] {encoded_value.strip()}")
                except (json.JSONDecodeError, Exception) as e:
                    print(f"Could not parse data JSON or decode base64: {e}", file=sys.stderr)
                    print("Raw data output:")
                    print(data_str)

            else:
                print("No data found in this Secret.")

            print("-------------------------")
            input("\nPress Enter to continue...")

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error fetching Secret data: {e.stderr.strip()}", file=sys.stderr)
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

            key, secret = self.select_resource()
            if key == "esc" or secret is None:
                self.current_namespace = None
                continue
            elif key == "alt-c":
                 self.view_content(secret)

    def edit_secret(self, secret_name: str):
        subprocess.run(["clear"])
        print(f"Editing secret {secret_name} in namespace {self.current_namespace}")
        try:
            # Get secret details
            secret_result = subprocess.run(
                ["kubectl", "get", "secret", secret_name, "-n", self.current_namespace, "-o", "json"],
                capture_output=True, text=True, check=True
            )
            secret_data = json.loads(secret_result.stdout)
            
            # Get data
            data = secret_data.get('data', {})
            if not data:
                print("No data found in secret.")
                input("\nPress Enter to continue...")
                return

            # Create key selection menu
            keys = list(data.keys())
            print("Select key to edit:")
            key_result = self.run_fzf(
                keys,
                f"Edit Secret ({secret_name})",
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

            # Update secret
            subprocess.run(["clear"])
            print(f"Updating secret {secret_name}...")
            try:
                # Base64 encode the new value
                encoded_value = base64.b64encode(new_value.encode()).decode()
                subprocess.run(
                    ["kubectl", "patch", "secret", secret_name, "-n", self.current_namespace, "--patch", f'{{"data":{{"{key}":"{encoded_value}"}}}}'],
                    check=True
                )
                print("Secret updated successfully.")
                input("\nPress Enter to continue...")
            except subprocess.CalledProcessError as e:
                subprocess.run(["clear"])
                print(f"Error updating secret: {e.stderr.strip()}", file=sys.stderr)
                input("\nPress Enter to continue...")

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error getting secret details: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except json.JSONDecodeError:
            subprocess.run(["clear"])
            print("Error parsing secret details.", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()
 