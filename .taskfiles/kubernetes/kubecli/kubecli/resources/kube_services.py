#!/usr/bin/env python3
import subprocess
import json
import re
import sys
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase

class ServiceManager(KubeBase):
    resource_type = "services"
    resource_name = "Service"

    def get_service_bindings(self) -> Tuple[List[str], str]:
        service_bindings = [
             "--bind", "alt-p:accept",
             "--bind", "enter:ignore"
        ]
        service_header = "Alt-P: Port-forward"
        return service_bindings, service_header

    def get_target_ports(self, service_name: str) -> List[str]:
        try:
            result = subprocess.run(
                [
                    "kubectl", "get", "service", service_name,
                    "-n", self.current_namespace,
                    "-o", "jsonpath={.spec.ports[*].targetPort}"
                ],
                capture_output=True, text=True, check=True
            )
            ports_str = result.stdout.strip()
            return ports_str.split() if ports_str else []
        except subprocess.CalledProcessError as e:
            print(f"Error fetching target ports: {e.stderr}")
            input("\nPress Enter to continue...")
            return []

    def select_local_port(self) -> Optional[str]:
        ports = [str(p) for p in range(1, 65536)]
        result = self.run_fzf(
            ports,
            "Local port",
            header="Select a local port to forward to",
            use_common_bindings=False
        )
        if isinstance(result, tuple):
            key, port = result
            if key == "esc" or not port:
                return None
            return port
        elif isinstance(result, str):
            return result
        else:
            return None

    def select_resource(self) -> Tuple[Optional[str], Optional[str]]:
        services = self.refresh_resources(self.current_namespace)
        if not services:
            print(f"No services found in namespace {self.current_namespace}")
            input("\nPress Enter to continue...")
            return "esc", None

        bindings, header = self.get_service_bindings()

        result = self.run_fzf(
            services,
            f"Services ({self.current_namespace})",
            extra_bindings=bindings,
            header=header,
            expect="esc,alt-p"
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

            key, service = self.select_resource()
            if key == "esc" or service is None:
                self.current_namespace = None
                continue

            if key == "alt-p":
                self.port_forward_service(service)

    def port_forward_service(self, service_name: str):
        subprocess.run(["clear"])
        print(f"Port forwarding for service {service_name} in namespace {self.current_namespace}")
        try:
            # Get service details
            service_result = subprocess.run(
                ["kubectl", "get", "service", service_name, "-n", self.current_namespace, "-o", "json"],
                capture_output=True, text=True, check=True
            )
            service_data = json.loads(service_result.stdout)
            
            # Extract ports
            ports = service_data.get('spec', {}).get('ports', [])
            if not ports:
                print("No ports found in service definition.")
                input("\nPress Enter to continue...")
                return

            # Create port selection menu
            port_options = []
            for port in ports:
                name = port.get('name', 'unnamed')
                protocol = port.get('protocol', 'TCP')
                port_num = port.get('port')
                target_port = port.get('targetPort')
                if port_num:
                    port_options.append(f"{name} ({protocol}): {port_num} -> {target_port}")

            if not port_options:
                print("No valid ports found in service definition.")
                input("\nPress Enter to continue...")
                return

            # Let user select port
            print("Select port to forward:")
            port_result = self.run_fzf(
                port_options,
                f"Port Forward ({service_name})",
                header="Select port to forward (Esc to cancel)",
                use_common_bindings=False,
                expect="esc,enter"
            )

            if port_result is None or (isinstance(port_result, tuple) and port_result[0] == "esc"):
                subprocess.run(["clear"])
                print("Port forward cancelled.")
                input("\nPress Enter to continue...")
                return

            selected_key, selected_port = port_result if isinstance(port_result, tuple) else ("enter", port_result)
            if selected_key != "enter":
                subprocess.run(["clear"])
                print(f"Unexpected key pressed: {selected_key}")
                input("\nPress Enter to continue...")
                return

            # Extract port number from selection
            port_match = re.search(r': (\d+) ->', selected_port)
            if not port_match:
                print("Could not parse port number from selection.")
                input("\nPress Enter to continue...")
                return

            service_port = port_match.group(1)
            
            # Get local port
            while True:
                try:
                    local_port = input(f"Enter local port to forward to (default: {service_port}): ").strip()
                    if not local_port:
                        local_port = service_port
                    local_port = int(local_port)
                    if local_port < 1 or local_port > 65535:
                        print("Port must be between 1 and 65535")
                        continue
                    break
                except ValueError:
                    print("Please enter a valid port number")
                    continue
                except KeyboardInterrupt:
                    return self.handle_keyboard_interrupt()

            # Start port forwarding
            subprocess.run(["clear"])
            print(f"Starting port forward for {service_name}...")
            print(f"Forwarding local port {local_port} to service port {service_port}")
            print("Press Ctrl+C to stop port forwarding")
            
            try:
                subprocess.run(
                    ["kubectl", "port-forward", f"svc/{service_name}", f"{local_port}:{service_port}", "-n", self.current_namespace],
                    check=True
                )
            except subprocess.CalledProcessError as e:
                subprocess.run(["clear"])
                print(f"Error during port forwarding: {e.stderr.strip()}", file=sys.stderr)
                input("\nPress Enter to continue...")
            except KeyboardInterrupt:
                return self.handle_keyboard_interrupt()

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error getting service details: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except json.JSONDecodeError:
            subprocess.run(["clear"])
            print("Error parsing service details.", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()
