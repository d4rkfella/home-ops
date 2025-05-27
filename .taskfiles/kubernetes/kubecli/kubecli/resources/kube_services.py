#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase

class ServiceManager(KubeBase):
    resource_type = "services"
    resource_name = "Service"

    def get_service_bindings(self) -> Tuple[List[str], str]:
        service_bindings = [
             "--bind", "alt-p:accept", # Alt-P for Port-forward
             "--bind", "enter:ignore" # Ignore Enter key press
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
                target_ports = self.get_target_ports(service)
                if not target_ports:
                    print(f"No target ports found for service {service}")
                    input("\nPress Enter to continue...")
                    continue

                port_result = self.run_fzf(
                    target_ports,
                    f"Select target port for service {service}",
                    header="Target Ports",
                    use_common_bindings=False
                )
                if isinstance(port_result, tuple):
                    _, target_port = port_result
                else:
                    target_port = port_result

                if not target_port:
                    print("No target port selected, aborting port-forward")
                    input("\nPress Enter to continue...")
                    continue

                local_port = self.select_local_port()
                if not local_port:
                    print("No local port selected, aborting port-forward")
                    input("\nPress Enter to continue...")
                    continue

                print(f"Starting port-forward: local {local_port} -> target {target_port}")
                try:
                    subprocess.run(
                        [
                            "kubectl", "port-forward",
                            f"service/{service}",
                            f"{local_port}:{target_port}",
                            "-n", self.current_namespace
                        ]
                    )
                except KeyboardInterrupt:
                    print("\nPort-forward stopped by user")
