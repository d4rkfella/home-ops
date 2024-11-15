#!/bin/bash
# Logging information | 0 = disabled | 1 = enabled
logging=0
# Log file in case logging is enabled
healthcheck_log_file="/healthcheck.log"

function log() {
    if [[ $logging == 1 ]]; then
        echo "$(date): $1" >> ${healthcheck_log_file}
    fi
}

log "-------------"

# Check if API call returns http code 200
http_code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:80/api/v2/app/version)
if [[ $http_code != 200 ]]; then
    log "App status: not up yet, did you enable \"Bypass authentication for clients on localhost\" in the Web UI options?"
    exit 1
else
    log "App status: up and running"
fi

exit 0
