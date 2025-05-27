#!/usr/bin/env python3
import subprocess
import json
import re
import sys
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase

class PodManager(KubeBase):
    resource_type = "pods"
    resource_name = "Pod"

    def get_pod_bindings(self) -> Tuple[List[str], str]:
        pod_bindings = [
            "--bind", f"alt-l:change-preview(kubectl logs {{1}} -n {self.current_namespace} --all-containers)+change-preview-window(hidden|right:60%:wrap)",
            "--bind", "alt-c:accept",
            "--bind", "alt-p:accept",
            "--bind", "alt-f:accept",  # Alt-F: Full Logs
            "--bind", "enter:ignore"
        ]
        pod_header = "Alt-L: Logs Preview | Alt-C: Exec Shell | Alt-P: Port Forward | Alt-F: Full Logs"
        return pod_bindings, pod_header

    def select_resource(self) -> Tuple[Optional[str], Optional[str]]:
        pods = self.refresh_resources(self.current_namespace)
        if not pods:
            print(f"No pods found in namespace {self.current_namespace}")
            input("\nPress Enter to continue...")
            return "esc", None

        bindings, header = self.get_pod_bindings()

        result = self.run_fzf(
            pods,
            "Pods",
            extra_bindings=bindings,
            header=header,
            expect="esc,alt-c,alt-p,alt-f"
        )
        if isinstance(result, tuple):
            return result
        else:
            return "esc", None

    def try_shells(self, pod_name, container, namespace):
        shells = ["bash", "sh", "ash"]
        for shell in shells:
            print(f"Trying shell '{shell}' in pod '{pod_name}', container '{container}'...")
            result = subprocess.run(
                ["kubectl", "exec", pod_name, "-n", namespace, "-c", container, "--", shell, "-c", "echo Shell OK"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                subprocess.run(
                    ["kubectl", "exec", "-it", pod_name, "-n", namespace, "-c", container, "--", shell]
                )
                return
        print("No suitable shell found in the container.")

    def navigate(self):
        while True:
            if not self.current_namespace:
                key, ns = self.select_namespace()
                if key == "esc" or ns is None:
                    return
                self.current_namespace = ns

            key, pod = self.select_resource()
            if key == "esc" or pod is None:
                self.current_namespace = None
                continue
            elif key == "alt-c":
                self.exec_into_pod(pod)
            elif key == "alt-p":
                self.port_forward_pod(pod)
            elif key == "alt-f":
                self.logs_pod(pod)

    def port_forward_pod(self, pod_name: str):
        subprocess.run(["clear"])
        print(f"Port forwarding for pod {pod_name} in namespace {self.current_namespace}")
        try:
            # Get pod details
            pod_result = subprocess.run(
                ["kubectl", "get", "pod", pod_name, "-n", self.current_namespace, "-o", "json"],
                capture_output=True, text=True, check=True
            )
            pod_data = json.loads(pod_result.stdout)

            # Extract container ports
            containers = pod_data.get('spec', {}).get('containers', [])
            if not containers:
                print("No containers found in pod definition.")
                input("\nPress Enter to continue...")
                return

            port_options = []
            for container in containers:
                container_name = container.get('name', 'unnamed')
                ports = container.get('ports', [])
                for port in ports:
                    name = port.get('name', 'unnamed')
                    protocol = port.get('protocol', 'TCP')
                    container_port = port.get('containerPort')
                    if container_port:
                        port_options.append(f"{container_name} - {name} ({protocol}): {container_port}")

            if not port_options:
                print("No valid ports found in pod definition.")
                input("\nPress Enter to continue...")
                return

            print("Select port to forward:")
            port_result = self.run_fzf(
                port_options,
                f"Port Forward ({pod_name})",
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

            port_match = re.search(r': (\d+)$', selected_port)
            if not port_match:
                print("Could not parse port number from selection.")
                input("\nPress Enter to continue...")
                return

            container_port = port_match.group(1)

            while True:
                try:
                    local_port = input(f"Enter local port to forward to (default: {container_port}): ").strip()
                    if not local_port:
                        local_port = container_port
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

            subprocess.run(["clear"])
            print(f"Starting port forward for {pod_name}...")
            print(f"Forwarding local port {local_port} to container port {container_port}")
            print("Press Ctrl+C to stop port forwarding")

            try:
                subprocess.run(
                    ["kubectl", "port-forward", f"pod/{pod_name}", f"{local_port}:{container_port}", "-n", self.current_namespace],
                    check=True
                )
            except subprocess.CalledProcessError as e:
                subprocess.run(["clear"])
                print(f"Error during port forwarding: {e.stderr.strip()}", file=sys.stderr)
                input("\nPress Enter to continue...")
            except KeyboardInterrupt:
                subprocess.run(["clear"])
                print("Port forwarding stopped.")
                input("\nPress Enter to continue...")

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error getting pod details: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except json.JSONDecodeError:
            subprocess.run(["clear"])
            print("Error parsing pod details.", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()

    def exec_into_pod(self, pod_name: str):
        subprocess.run(["clear"])
        print(f"Executing into pod {pod_name} in namespace {self.current_namespace}")
        try:
            # Get pod details
            pod_result = subprocess.run(
                ["kubectl", "get", "pod", pod_name, "-n", self.current_namespace, "-o", "json"],
                capture_output=True, text=True, check=True
            )
            pod_data = json.loads(pod_result.stdout)
            
            # Get container names
            containers = pod_data.get('spec', {}).get('containers', [])
            if not containers:
                print("No containers found in pod definition.")
                input("\nPress Enter to continue...")
                return

            container_names = [container.get('name', 'unnamed') for container in containers]
            
            # If only one container, use it directly
            if len(container_names) == 1:
                container_name = container_names[0]
            else:
                # Let user select container
                print("Select container to exec into:")
                container_result = self.run_fzf(
                    container_names,
                    f"Exec Into Pod ({pod_name})",
                    header="Select container (Esc to cancel)",
                    use_common_bindings=False,
                    expect="esc,enter"
                )

                if container_result is None or (isinstance(container_result, tuple) and container_result[0] == "esc"):
                    subprocess.run(["clear"])
                    print("Exec cancelled.")
                    input("\nPress Enter to continue...")
                    return

                selected_key, container_name = container_result if isinstance(container_result, tuple) else ("enter", container_result)
                if selected_key != "enter":
                    subprocess.run(["clear"])
                    print(f"Unexpected key pressed: {selected_key}")
                    input("\nPress Enter to continue...")
                    return

            # Start exec by trying common shells
            subprocess.run(["clear"])
            print(f"Executing into {container_name} in pod {pod_name}...")
            print("Type 'exit' to return to the menu")
            
            try:
                self.try_shells(pod_name, container_name, self.current_namespace)
            except subprocess.CalledProcessError as e:
                subprocess.run(["clear"])
                print(f"Error during exec: {e.stderr.strip()}", file=sys.stderr)
                input("\nPress Enter to continue...")
            except KeyboardInterrupt:
                subprocess.run(["clear"])
                print("Exec session ended.")
                input("\nPress Enter to continue...")

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            print(f"Error getting pod details: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except json.JSONDecodeError:
            subprocess.run(["clear"])
            print("Error parsing pod details.", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()

    def spawn_terminal(self, title: str, command: str) -> bool:
        """Try to spawn a new terminal window with the given command.
        Returns True if successful, False otherwise."""
        
        # First try tmux
        try:
            # Create a new tmux session with the command
            session_name = f"logs-{title.lower().replace(' ', '-')}"
            tmux_cmd = f"tmux new-session -d -s {session_name} '{command}'"
            subprocess.run(tmux_cmd, shell=True, check=True)
            # Attach to the session
            subprocess.Popen(["tmux", "attach-session", "-t", session_name])
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Then try screen
        try:
            # Create a new screen session with the command
            session_name = f"logs-{title.lower().replace(' ', '-')}"
            screen_cmd = f"screen -dmS {session_name} {command}"
            subprocess.run(screen_cmd, shell=True, check=True)
            # Attach to the session
            subprocess.Popen(["screen", "-r", session_name])
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Finally try terminal emulators
        terminals = [
            ["gnome-terminal", "--title", title, "--", "bash", "-c", command],
            ["konsole", "-e", f"bash -c '{command}'", "--title", title],
            ["xterm", "-title", title, "-e", command],
            ["urxvt", "-title", title, "-e", command],
            ["alacritty", "-t", title, "-e", "bash", "-c", command],
            ["kitty", "-T", title, "bash", "-c", command],
            ["lxterminal", "-t", title, "-e", command]  # Added lxterminal which is common on Alpine
        ]

        for terminal_cmd in terminals:
            try:
                subprocess.Popen(terminal_cmd)
                return True
            except FileNotFoundError:
                continue
        return False

    def logs_pod(self, pod_name: str):
        subprocess.run(["clear"])
        print(f"Showing logs for pod {pod_name} in namespace {self.current_namespace}")
        try:
            # Get pod details
            pod_result = subprocess.run(
                ["kubectl", "get", "pod", pod_name, "-n", self.current_namespace, "-o", "json"],
                capture_output=True, text=True, check=True
            )
            pod_data = json.loads(pod_result.stdout)
            
            # Get container names
            containers = pod_data.get('spec', {}).get('containers', [])
            if not containers:
                print("No containers found in pod definition.")
                input("\nPress Enter to continue...")
                return

            container_names = [container.get('name', 'unnamed') for container in containers]
            
            # If only one container, use it directly
            if len(container_names) == 1:
                selected_container = container_names[0]
            else:
                # Let user select container or all containers
                print("Select container to show logs for:")
                container_options = ["<All Containers>"] + container_names
                container_result = self.run_fzf(
                    container_options,
                    f"Pod Logs ({pod_name})",
                    header="Select container (Esc to cancel)",
                    use_common_bindings=False,
                    expect="esc,enter"
                )

                if container_result is None or (isinstance(container_result, tuple) and container_result[0] == "esc"):
                    print("Logs cancelled.")
                    input("\nPress Enter to continue...")
                    return

                selected_key, selected_container = container_result if isinstance(container_result, tuple) else ("enter", container_result)
                if selected_key != "enter":
                    print(f"Unexpected key pressed: {selected_key}")
                    input("\nPress Enter to continue...")
                    return

            # Get follow option
            while True:
                try:
                    follow = input("Follow logs? (y/n, default: n): ").strip().lower()
                    if not follow:
                        follow = "n"
                    if follow not in ["y", "n"]:
                        print("Please enter 'y' or 'n'")
                        continue
                    break
                except KeyboardInterrupt:
                    return self.handle_keyboard_interrupt()

            # Get previous option
            while True:
                try:
                    previous = input("Show logs from previous container instance? (y/n, default: n) [Only available if container was restarted]: ").strip().lower()
                    if not previous:
                        previous = "n"
                    if previous not in ["y", "n"]:
                        print("Please enter 'y' or 'n'")
                        continue
                    break
                except KeyboardInterrupt:
                    return self.handle_keyboard_interrupt()

            # Get tail option
            while True:
                try:
                    tail = input("Number of lines to show (default: all): ").strip()
                    if not tail:
                        tail = None
                    else:
                        tail = int(tail)
                        if tail < 1:
                            print("Number of lines must be positive")
                            continue
                    break
                except ValueError:
                    print("Please enter a valid number")
                    continue
                except KeyboardInterrupt:
                    return self.handle_keyboard_interrupt()

            # Create title for the new terminal window
            title = f"Logs: {pod_name}"
            if selected_container != "<All Containers>":
                title += f" - {selected_container}"
            if previous == "y":
                title += " (previous)"

            # Build the command
            if follow == "y":
                # For following logs
                cmd = f"kubectl logs {pod_name} -n {self.current_namespace}"
                if selected_container != "<All Containers>":
                    cmd += f" -c {selected_container}"
                if previous == "y":
                    cmd += " -p"
                if tail is not None:
                    cmd += f" --tail {tail}"
                cmd += " -f"  # Add follow flag
            else:
                # For non-following logs with less
                cmd = f"kubectl logs {pod_name} -n {self.current_namespace}"
                if selected_container != "<All Containers>":
                    cmd += f" -c {selected_container}"
                if previous == "y":
                    cmd += " -p"
                if tail is not None:
                    cmd += f" --tail {tail}"
                cmd += " | less -R"  # Use less for viewing

            # Try to spawn a new terminal window
            if self.spawn_terminal(title, cmd):
                print(f"\nLogs are being shown in a new window.")
                print("To detach from the window:")
                print("- In tmux: Press Ctrl+B then D")
                print("- In screen: Press Ctrl+A then D")
                print("- For terminal emulators: Just close the window")
            else:
                print("\nCould not spawn a new window. Please install one of the following:")
                print("- tmux: apk add tmux")
                print("- screen: apk add screen")
                print("- A terminal emulator: apk add xterm (or lxterminal, alacritty)")
                print("\nOr you can run the following command manually:")
                print(cmd)
            input("\nPress Enter to continue...")

        except subprocess.CalledProcessError as e:
            print(f"Error getting pod details: {e.stderr.strip()}", file=sys.stderr)
            input("\nPress Enter to continue...")
        except json.JSONDecodeError:
            print("Error parsing pod details.", file=sys.stderr)
            input("\nPress Enter to continue...")
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()
