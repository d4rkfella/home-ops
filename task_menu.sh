#!/bin/bash
set -euo pipefail
trap 'echo; echo "❌ Task cancelled by user. Exiting."; exit 0' SIGINT

tasks=$(task --list --json | jq -r '.tasks[] | "\(.name)\t\(.desc)"')

selected=$(echo "$tasks" | fzf) || {
  echo "❌ Task selection cancelled."
  exit 0
}

task_name=$(echo "$selected" | cut -f1)
echo "✅ Selected task: $task_name"

IFS=':' read -ra parts <<< "$task_name"

if [ "${#parts[@]}" -eq 1 ]; then
  included_file="Taskfile.yaml"
  task_key="${parts[0]}"
else
  namespace="${parts[0]}"
  task_key="${parts[1]}"
  included_dir=$(yq e ".includes.\"$namespace\"" Taskfile.yaml)
  included_file="$included_dir/Taskfile.yaml"
fi

required_vars=$(yq e ".tasks.\"$task_key\".requires.vars // [] | .[]" "$included_file")

var_args=""
for var in $required_vars; do
  while true; do
    read -rp "🔹 $var: " value
    if [ -n "$value" ]; then
      break
    else
      echo "⚠️  $var cannot be empty."
    fi
  done
  var_args="$var_args $var=$value"
done

eval task "$task_name" $var_args
