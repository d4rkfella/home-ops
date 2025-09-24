#!/usr/bin/env python3
import subprocess
import sys
import signal
import json
import yaml
import os

def sigint_handler(sig, frame):
    print("\n❌ Task cancelled by user. Exiting.")
    sys.exit(0)

signal.signal(signal.SIGINT, sigint_handler)

# Run `task --list --json`
try:
    result = subprocess.run(
        ["task", "--list", "--json"],
        check=True,
        capture_output=True,
        text=True
    )
    tasks_json = json.loads(result.stdout)
except subprocess.CalledProcessError:
    print("❌ Failed to get tasks.")
    sys.exit(1)

tasks = [(t["name"], t["desc"]) for t in tasks_json.get("tasks", [])]

# Format for fzf
fzf_input = "\n".join([f"{name}\t{desc}" for name, desc in tasks])

# Run fzf
try:
    fzf = subprocess.run(
        ["fzf"],
        input=fzf_input,
        text=True,
        capture_output=True,
        check=True
    )
    selected = fzf.stdout.strip()
except subprocess.CalledProcessError:
    print("❌ Task selection cancelled.")
    sys.exit(0)

if not selected:
    print("❌ No task selected.")
    sys.exit(0)

task_name = selected.split("\t")[0]
print(f"✅ Selected task: {task_name}")

parts = task_name.split(":")
if len(parts) == 1:
    included_file = "Taskfile.yaml"
    task_key = parts[0]
else:
    namespace, task_key = parts
    with open("Taskfile.yaml") as f:
        taskfile = yaml.safe_load(f)
    included_dir = taskfile["includes"].get(namespace)
    included_file = os.path.join(included_dir, "Taskfile.yaml")

# Load included taskfile
with open(included_file) as f:
    included_taskfile = yaml.safe_load(f)

required_vars = included_taskfile.get("tasks", {}).get(task_key, {}).get("requires", {}).get("vars", []) or []

var_args = []
for var in required_vars:
    while True:
        try:
            value = input(f"🔹 {var}: ").strip()
        except EOFError:
            sys.exit(0)
        if value:
            break
        else:
            print(f"⚠️  {var} cannot be empty.")
    var_args.append(f"{var}={value}")

# Run the task
cmd = ["task", task_name] + var_args
subprocess.run(cmd)
