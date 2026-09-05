#!/usr/bin/env bash
set -euo pipefail

yq -y '
  if .kind == "DaemonSet" and .metadata.name == "multus" then
    .spec.template.spec.containers[0].args += ["--multus-bin-file=/usr/bin/multus"]
  else
    .
  end
'
