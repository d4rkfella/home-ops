#!/usr/bin/env python3
import subprocess
import sys
import json

def run_cmd(cmd):
    """Run a shell command and return stdout, raise on error."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {' '.join(cmd)}")
        print(e.stderr)
        sys.exit(1)

def run_fzf(options, prompt="> ", preview=None, with_nth=None):
    """Run fzf with given options and return selection."""
    if not options:
        return None
    cmd = ["fzf", "--prompt", prompt]
    if preview:
        cmd += ["--preview", preview]
    if with_nth:
        cmd += ["--with-nth", str(with_nth)]

    try:
        result = subprocess.run(cmd, input="\n".join(options),
                                text=True, capture_output=True, check=True)
        return result.stdout.strip() if result.stdout else None
    except subprocess.CalledProcessError:
        return None

def main():
    raw = run_cmd(["kubectl", "get", "vms", "--all-namespaces", "-o", "json"])
    data = json.loads(raw)

    vms = []
    for item in data.get("items", []):
        status = item.get("status", {}).get("printableStatus")
        if status == "Running":
            ns = item["metadata"]["namespace"]
            name = item["metadata"]["name"]
            vms.append(f"{ns}\t{name}")

    if not vms:
        print("❌ No running VMs found.")
        sys.exit(0)

    selected = run_fzf(
        vms,
        prompt="🖥 Select a running VM: ",
        with_nth=2,
        preview="echo Namespace: {1}"
    )

    if not selected:
        print("❌ Selection cancelled.")
        sys.exit(0)

    namespace, vm_name = selected.split("\t")

    if not namespace or not vm_name:
        print("❌ Invalid VM selection.")
        sys.exit(0)

    print(f"🔌 Connecting to VMI {vm_name} in namespace {namespace}...")

    try:
        exit_code = subprocess.call(["virtctl", "vnc", vm_name, "-n", namespace])
    except FileNotFoundError:
        print("❌ virtctl not found in PATH.")
        sys.exit(1)

    if exit_code != 0:
        print(f"❌ virtctl command failed with exit code {exit_code}")

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
