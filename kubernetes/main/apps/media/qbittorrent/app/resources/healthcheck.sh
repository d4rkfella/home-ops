#!/bin/bash
#
# This script first checks if qBittorrent is up, and after
# that changes the listening port to that of the forwarded
# port of the VPN.
#
# This script requires to enable the "Bypass authentication
# for clients on localhost" in the Web UI options.
#
# https://gist.github.com/rourke/a553e54062af1149ff226df36cdc9e90
#
# Author: github.com/rourke

# Logging information | 0 = disabled | 1 = enabled
logging=0
# The file containing the forwarded port of the VPN
vpn_port_file="/forwarded_port.dat"
# Log file in case logging is enabled
healthcheck_log_file="/healthcheck.log"

function log() {
    if [[ $logging == 1 ]]; then
        echo "$(date): $1" >> ${healthcheck_log_file}
    fi
}

log "-------------"

# Check if vpn port file exists
if [ ! -f "${vpn_port_file}" ]; then
    log "Script error: the file containing the VPN forwarded port (${vpn_port_file}) does not exist."
    exit 1
fi

# Check if API call returns http code 200
http_code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:80/api/v2/app/version)
if [[ $http_code != 200 ]]; then
    log "App status: not up yet, did you enable \"Bypass authentication for clients on localhost\" in the Web UI options?"
    exit 1
else
    log "App status: up and running"
fi

# Get current listening port and vpn forwarded port
current_forwarded_port=$(curl -s http://localhost:8080/api/v2/app/preferences | jq '.listen_port')
forwarded_port_vpn=$(cat ${vpn_port_file})

if [[ $forwarded_port_vpn != $current_forwarded_port ]]; then
    # Ports are not the same, so update the port
    resp_code=$(curl -s -o /dev/null -w "%{http_code}" --request POST --data 'json={"listen_port":'${forwarded_port_vpn}'}' http://localhost:8080/api/v2/app/setPreferences)
    if [[ $resp_code == 200 ]]; then
        log "Listening port: updated from ${current_forwarded_port} to ${forwarded_port_vpn}"
    else
        log "Listening port: could not update from ${current_forwarded_port} to ${forwarded_port_vpn}: HTTP ${resp_code}"
        exit 1
    fi
else
    log "Listening port: good (${current_forwarded_port})"
fi

exit 0
