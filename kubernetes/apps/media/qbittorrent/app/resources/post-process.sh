#!/usr/bin/env bash
# shellcheck disable=SC2154

set -euo pipefail

# User-defined variables
CROSS_SEED_ENABLED="${CROSS_SEED_ENABLED:-false}"
CROSS_SEED_URL="${CROSS_SEED_URL:-required}"
CROSS_SEED_API_KEY="${CROSS_SEED_API_KEY:-required}"
CROSS_SEED_SLEEP_INTERVAL="${CROSS_SEED_SLEEP_INTERVAL:-30}"
PUSHOVER_ENABLED="${PUSHOVER_ENABLED:-false}"
PUSHOVER_USER_KEY="${PUSHOVER_USER_KEY:-required}"
PUSHOVER_TOKEN="${PUSHOVER_TOKEN:-required}"

# Function to set release variables from qBittorrent
set_qb_vars() {
    RELEASE_NAME="$1"      # %N
    RELEASE_INFOHASH="$2"  # %I
    RELEASE_CAT="$3"       # %L
    RELEASE_SIZE="$4"      # %Z
    RELEASE_INDEXER="$5"   # %T
    RELEASE_TYPE="Torrent"
}

# Function to send pushover notification
send_pushover_notification() {
    local pushover_message status_code json_data
    printf -v pushover_message \
        "<b>%s</b><small>\n<b>Category:</b> %s</small><small>\n<b>Indexer:</b> %s</small><small>\n<b>Size:</b> %s</small>" \
            "${RELEASE_NAME%.*}" \
            "${RELEASE_CAT}" \
            "$(trurl --url "${RELEASE_INDEXER}" --get '{idn:host}')" \
            "$(numfmt --to iec --format "%8.2f" "${RELEASE_SIZE}")"

    json_data=$(jo \
        token="${PUSHOVER_TOKEN}" \
        user="${PUSHOVER_USER_KEY}" \
        title="${RELEASE_TYPE} Downloaded" \
        message="${pushover_message}" \
        priority="-2" \
        html="1"
    )

    status_code=$(curl \
        --silent \
        --write-out "%{http_code}" \
        --output /dev/null \
        --request POST  \
        --header "Content-Type: application/json" \
        --data-binary "${json_data}" \
        "https://api.pushover.net/1/messages.json"
    )

    printf "pushover notification returned with HTTP status code %s and payload: %s\n" \
        "${status_code}" \
        "$(echo "${json_data}" | jq --compact-output)" >&2
}

# Function to search for cross-seed
search_cross_seed() {
    local status_code
    status_code=$(curl \
        --silent \
        --output /dev/null \
        --write-out "%{http_code}" \
        --request POST \
        --data-urlencode "infoHash=${RELEASE_INFOHASH}" \
        --data-urlencode "includeSingleEpisodes=true" \
        --header "X-Api-Key: ${CROSS_SEED_API_KEY}" \
        "${CROSS_SEED_URL}/api/webhook"
    )

    printf "cross-seed search returned with HTTP status code %s and path %s\n" \
        "${status_code}" \
        "${RELEASE_NAME}" >&2

    sleep "${CROSS_SEED_SLEEP_INTERVAL}"
}

main() {
        set_qb_vars "$@"

    # Send pushover notification
    if [[ "${PUSHOVER_ENABLED}" == "true" ]]; then
        send_pushover_notification
    fi

    # Search for cross-seed
    if [[ "${CROSS_SEED_ENABLED}" == "true" ]]; then
        search_cross_seed
    fi
}

main "$@"
