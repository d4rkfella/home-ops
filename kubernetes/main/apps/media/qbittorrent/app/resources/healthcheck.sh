#!/usr/bin/env bash
# shellcheck disable=SC2154

set -euo pipefail

http_code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:80/api/v2/app/version)
if [[ $http_code != 200 ]]; then
    log "App status: not up yet, did you enable \"Bypass authentication for clients on localhost\" in the Web UI options?"
    exit 1
else
    log "App status: up and running"
fi

exit 0
