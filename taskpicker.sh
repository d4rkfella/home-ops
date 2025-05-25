#!/bin/bash
set -euo pipefail
trap 'echo; echo "❌ Input cancelled by user. Exiting."; exit 0' SIGINT

tasks=$(task --list --json | jq -r '.tasks[] | "\(.name)\t\(.desc)"')

fzf_opts=(
  --prompt="📋 Select a task: "
  --header='⏎ to run | ESC to cancel'
  --layout=reverse
  --border
  --preview='echo {} | cut -f2'
  --preview-window=down:5:wrap
  --with-nth=1
  --color=fg:#d0d0d0,bg:#1b1b1b,hl:#00afff
  --color=fg+:#ffffff,bg+:#005f87,hl+:#00afff
  --color=info:#87ffaf,prompt:#ff5f00,pointer:#af00ff
)

selected=$(echo "$tasks" | fzf "${fzf_opts[@]}") || {
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
    read -rp "🔹 $var: " value || { echo; echo "❌ Input cancelled. Exiting."; exit 0; }
    if [ -n "$value" ]; then
      break
    else
      echo "⚠️  $var cannot be empty."
    fi
  done
  var_args="$var_args $var=$value"
done

echo "🚀 Running: task $task_name $var_args"
eval task "$task_name" $var_args
