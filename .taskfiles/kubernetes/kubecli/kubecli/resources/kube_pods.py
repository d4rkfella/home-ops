#!/usr/bin/env python3
import subprocess
import json
import re
import sys
import os
from typing import List, Tuple, Optional
from kubecli.resources.kube_base import KubeBase
import libtmux

class PodManager(KubeBase):
    resource_type = "pods"
    resource_name = "Pod"

    def get_pod_bindings(self) -> Tuple[List[str], str]:
        pod_bindings = [
            "--bind", f"alt-l:change-preview(kubectl logs {{1}} -n {self.current_namespace} --all-containers)+change-preview-window(hidden|right:60%:wrap)",
            "--bind", "alt-c:accept",
            "--bind", "alt-p:accept",
            "--bind", "alt-f:accept",  # Alt-F: Full Logs
            "--bind", "alt-s:accept",  # Alt-S: Session Management
            "--bind", "enter:ignore"
        ]
        pod_header = "Alt-L: Logs Preview | Alt-C: Exec Shell | Alt-P: Port Forward | Alt-F: Full Logs | Alt-S: Session Management"
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
            expect="esc,alt-c,alt-p,alt-f,alt-s"
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
            elif key == "alt-s":
                self.manage_log_sessions()

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
        
        try:
            clean_title = title.replace("Logs:", "").strip()
            session_name = f"logs-{clean_title.lower().replace(' ', '-').replace(':', '-')}"
            
            server = libtmux.Server()
            
            # Create new session with a wrapper command that handles Ctrl+C and displays help
            help_text = '''echo -e "\n=== Log Viewing Help ===\n"
echo "Search: Ctrl+S (fuzzy search) / (search up) ? (search down) n/N (next/prev)"
echo "Exit: Ctrl+C (stop logs) Ctrl+B then D (detach)"
echo "Scroll: Arrow keys, Page Up/Down, or mouse wheel\n"
echo "=== Logs Start Below ===\n\n"
clear'''
            
            wrapped_command = f"""trap 'tmux kill-session -t {session_name}' INT TERM; {help_text}; {command}"""
            
            session = server.new_session(
                session_name=session_name,
                window_name=title,
                start_directory=None,
                attach=False,
                window_command=wrapped_command
            )
            
            window = session.windows[0]
            pane = window.panes[0]
            
            session.set_option('status', 'on')
            session.set_option('status-interval', 1)
            session.set_option('status-left-length', 100)
            session.set_option('status-right-length', 100)
            session.set_option('status-style', 'fg=black,bg=green')
            
            session.set_option('status-left', '#[fg=green]#H #[fg=black]• #[fg=yellow]🔍 C-s(fzf) /(up) ?(down) n/N(next/prev)#[default]')
            session.set_option('status-right', '#[fg=green]#(cut -d " " -f 1 /proc/loadavg)#[default] #[fg=blue]%H:%M#[default] #[fg=yellow]🚪 C-c(stop) C-b d(detach)#[default]')
            
            # Unbind default Ctrl+S binding and set up our bindings
            session.cmd('unbind-key', '-T', 'root', 'C-s')
            session.cmd('unbind-key', '-T', 'copy-mode-vi', 'C-s')
            
            # Set up key bindings for search
            session.cmd('bind-key', '-T', 'root', 'C-s', 'copy-mode')
            session.cmd('bind-key', '-T', 'copy-mode-vi', '/', 'command-prompt', '-i', '-p', 'search up', 'send -X search-backward-incremental "%%%"')
            session.cmd('bind-key', '-T', 'copy-mode-vi', '?', 'command-prompt', '-i', '-p', 'search down', 'send -X search-forward-incremental "%%%"')
            session.cmd('bind-key', '-T', 'copy-mode-vi', 'n', 'send', '-X', 'search-again')
            session.cmd('bind-key', '-T', 'copy-mode-vi', 'N', 'send', '-X', 'search-reverse')
            
            # Set up fzf search binding using fzf-tmux with full path
            session.cmd('bind-key', '-T', 'copy-mode-vi', 'C-s', 'send', '-X', 'copy-pipe-and-cancel', f'tmux capture-pane -p -S -1000 | {os.path.expanduser("~/.fzf/bin/fzf-tmux")} -p 80% --no-sort --reverse --inline-info --preview "echo {{}}" --preview-window=up:3:wrap --bind "ctrl-y:execute-silent(echo -n {{}} | xclip -in -selection clipboard)+abort"')
            
            # Display help text using libtmux's display-message
            help_text = [
                "\n=== Log Viewing Help ===\n",
                "Search: Ctrl+S (fuzzy search) / (search up) ? (search down) n/N (next/prev)",
                "Exit: Ctrl+C (stop logs) Ctrl+B then D (detach)",
                "Scroll: Arrow keys, Page Up/Down, or mouse wheel\n",
                "=== Logs Start Below ===\n\n"
            ]
            
            for line in help_text:
                session.cmd('display-message', '-p', line)
            
            # Clear the screen
            pane.send_keys('clear')
            
            # Attach to the session
            session.attach_session()
            
            # Clean up when detached
            try:
                session.kill_session()
            except:
                pass  # Session might already be killed
            
            return True
            
        except Exception as e:
            print(f"Error setting up tmux: {str(e)}")
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
                print("\nSearch and Navigation:")
                print("- Enter copy mode: Ctrl+B then [")
                print("- Search with fzf: Ctrl+S")
                print("- Regular search: / (forward) or ? (backward)")
                print("- Next match: n")
                print("- Previous match: N")
                print("\nExit and Return:")
                print("- Press Ctrl+C to stop logs and return to menu")
                print("- Or use Ctrl+B then D to detach (logs will continue running)")
                print("- To reattach: tmux attach -t logs-{pod_name}")
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

    def manage_log_sessions(self):
        """Manage active log sessions."""
        subprocess.run(["clear"])
        print("Managing Log Sessions")
        
        try:
            # Get list of active tmux sessions
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
                check=True
            )
            
            # Filter for log sessions
            log_sessions = [s for s in result.stdout.splitlines() if s.startswith("logs-")]
            
            if not log_sessions:
                print("No active log sessions found.")
                input("\nPress Enter to continue...")
                return
            
            # Create menu options
            options = []
            for session in log_sessions:
                # Extract pod name from session name
                pod_name = session.replace("logs-", "").replace("-", " ")
                options.append(f"{pod_name} (Session: {session})")
            
            # Add option to kill all sessions
            options.append("Kill All Log Sessions")
            
            # Show menu
            print("Select a session to manage:")
            result = self.run_fzf(
                options,
                "Log Sessions",
                header="Select session to manage (Esc to cancel)",
                use_common_bindings=False,
                expect="esc,enter"
            )
            
            if result is None or (isinstance(result, tuple) and result[0] == "esc"):
                return
            
            selected = result[1] if isinstance(result, tuple) else result
            
            if selected == "Kill All Log Sessions":
                # Kill all log sessions
                for session in log_sessions:
                    subprocess.run(["tmux", "kill-session", "-t", session])
                print("All log sessions have been terminated.")
            else:
                # Extract session name
                session_name = selected.split("(Session: ")[1].rstrip(")")
                
                # Show session management options
                print("\nSession Management Options:")
                print("1. Reattach to session")
                print("2. Kill session")
                print("3. Back to menu")
                
                while True:
                    try:
                        choice = input("\nEnter your choice (1-3): ").strip()
                        if choice == "1":
                            subprocess.run(["tmux", "attach-session", "-t", session_name])
                            break
                        elif choice == "2":
                            subprocess.run(["tmux", "kill-session", "-t", session_name])
                            print(f"Session {session_name} has been terminated.")
                            break
                        elif choice == "3":
                            break
                        else:
                            print("Invalid choice. Please enter 1-3.")
                    except KeyboardInterrupt:
                        return self.handle_keyboard_interrupt()
            
        except subprocess.CalledProcessError as e:
            print(f"Error managing sessions: {e.stderr.strip()}", file=sys.stderr)
        except KeyboardInterrupt:
            return self.handle_keyboard_interrupt()
        
        input("\nPress Enter to continue...")
