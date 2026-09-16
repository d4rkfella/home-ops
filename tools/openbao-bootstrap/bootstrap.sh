#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_NAME="openbao-bootstrap"

log() {
    printf '[%s] [%s] %s\n' \
        "$(date --iso-8601=seconds)" \
        "$SCRIPT_NAME" \
        "$*"
}

fatal() {
    printf '[%s] [%s] ERROR: %s\n' \
        "$(date --iso-8601=seconds)" \
        "$SCRIPT_NAME" \
        "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 ||
        fatal "required command not found: $1"
}

for command in kubectl bao jq aws sort sed head wc; do
    require_command "$command"
done

readonly OPENBAO_NAMESPACE="${1:?usage: $0 <openbao-namespace>}"
readonly BAO_TLS_SERVER_NAME="${BAO_TLS_SERVER_NAME:-openbao.local}"
readonly BAO_CACERT="${BAO_CACERT:?BAO_CACERT is not set}"
readonly SNAPSHOT_BUCKET="${SNAPSHOT_BUCKET:-openbao-snapshots}"
readonly SNAPSHOT_PREFIX="${SNAPSHOT_PREFIX:-bao_}"

[[ -f "${BAO_CACERT}" ]] ||
    fatal "OpenBao CA certificate does not exist: ${BAO_CACERT}"

readonly TMP_DIR="$(mktemp -d -t openbao-bootstrap.XXXXXX)"
readonly INIT_FILE="${TMP_DIR}/init.json"
readonly RESTORE_FILE="${TMP_DIR}/restore.snapshot"

declare -a OPENBAO_PODS=()
declare -a UNSEAL_KEYS=()

declare -A PORT_FORWARD_PIDS=()
declare -A PORT_FORWARD_PORTS=()
declare -A PORT_FORWARD_LOGS=()

cleanup() {
    local exit_code=$?

    for pod in "${!PORT_FORWARD_PIDS[@]}"; do
        local pid="${PORT_FORWARD_PIDS[$pod]}"

        if kill -0 "${pid}" 2>/dev/null; then
            log "stopping port-forward for ${pod} (pid=${pid})"
            kill "${pid}" 2>/dev/null || true
            wait "${pid}" 2>/dev/null || true
        fi
    done

    rm -rf "${TMP_DIR}"

    exit "${exit_code}"
}

trap cleanup EXIT

bao() {
    local port="$1"
    shift

    BAO_ADDR="https://127.0.0.1:${port}" \
    bao "$@"
}

get_status() {
    local pod="$1"
    local port="${PORT_FORWARD_PORTS[$pod]}"
    local output
    local exit_code=0

    output="$(
        bao "${port}" status -format=json \
            2>"${TMP_DIR}/${pod}-status.stderr"
    )" || exit_code=$?

    if [[ "${exit_code}" -ne 0 ]]; then
        printf '%s\n' "${output}"

        if [[ -s "${TMP_DIR}/${pod}-status.stderr" ]]; then
            cat "${TMP_DIR}/${pod}-status.stderr" >&2
        fi

        return "${exit_code}"
    fi

    printf '%s\n' "${output}"
}

discover_openbao_pods() {
    mapfile -t OPENBAO_PODS < <(
        kubectl get pods \
            -n "${OPENBAO_NAMESPACE}" \
            -l app.kubernetes.io/name=openbao \
            -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' |
        sed '/^$/d' |
        sort
    )

    [[ "${#OPENBAO_PODS[@]}" -gt 0 ]]
}

log "waiting for OpenBao pods..."

for _ in {1..120}; do
    if discover_openbao_pods; then
        break
    fi

    sleep 2
done

discover_openbao_pods ||
    fatal "no OpenBao pods found in namespace ${OPENBAO_NAMESPACE}"

log \
    "discovered ${#OPENBAO_PODS[@]} OpenBao pod(s): " \
    "${OPENBAO_PODS[*]}"

log "waiting for OpenBao pods to become Running..."

for pod in "${OPENBAO_PODS[@]}"; do
    kubectl wait \
        -n "${OPENBAO_NAMESPACE}" \
        --for=jsonpath='{.status.phase}'=Running \
        "pod/${pod}" \
        --timeout=10m
done

start_port_forward() {
    local pod="$1"
    local log_file="${TMP_DIR}/${pod}-port-forward.log"
    local pid
    local port=""

    if [[ -n "${PORT_FORWARD_PIDS[$pod]+x}" ]]; then
        return 0
    fi

    log "starting port-forward for ${pod}..."

    kubectl port-forward \
        -n "${OPENBAO_NAMESPACE}" \
        "pod/${pod}" \
        ":8200" \
        >"${log_file}" 2>&1 &

    pid=$!

    PORT_FORWARD_PIDS["${pod}"]="${pid}"
    PORT_FORWARD_LOGS["${pod}"]="${log_file}"

    for _ in {1..60}; do
        if ! kill -0 "${pid}" 2>/dev/null; then
            log "port-forward for ${pod} exited unexpectedly"
            cat "${log_file}" >&2 || true
            fatal "port-forward terminated for ${pod}"
        fi

        port="$(
            sed -nE \
                's/.*Forwarding from 127\.0\.0\.1:([0-9]+) -> 8200.*/\1/p' \
                "${log_file}" |
            head -n1
        )"

        if [[ -n "${port}" ]]; then
            PORT_FORWARD_PORTS["${pod}"]="${port}"

            log \
                "port-forward ${pod}: " \
                "localhost:${port} -> 8200"

            return 0
        fi

        sleep 1
    done

    log "port-forward output for ${pod}:"
    cat "${log_file}" >&2 || true

    fatal "unable to determine local port for ${pod}"
}

wait_for_api() {
    local pod="$1"
    local status=""

    log "waiting for OpenBao API on ${pod}..."

    for _ in {1..120}; do
        status="$(
            get_status "${pod}" 2>&1
        )" || true

        if jq -e '
            .initialized != null and
            .sealed != null
        ' >/dev/null 2>&1 <<<"${status}"; then
            printf '%s\n' "${status}"
            return 0
        fi

        sleep 2
    done

    log "last OpenBao status response/error from ${pod}:"
    printf '%s\n' "${status}" >&2

    log "port-forward log for ${pod}:"
    cat "${PORT_FORWARD_LOGS[$pod]}" >&2 || true

    fatal "OpenBao API did not become queryable on ${pod}"
}

for pod in "${OPENBAO_PODS[@]}"; do
    start_port_forward "${pod}"
done

INITIALIZE_POD="${OPENBAO_PODS[0]}"
INITIALIZE_PORT="${PORT_FORWARD_PORTS[${INITIALIZE_POD}]}"

STATUS="$(
    wait_for_api "${INITIALIZE_POD}"
)"

INITIALIZED="$(jq -r '.initialized' <<<"${STATUS}")"
SEALED="$(jq -r '.sealed' <<<"${STATUS}")"
SEAL_TYPE="$(jq -r '.type // empty' <<<"${STATUS}")"

log "initialization candidate: ${INITIALIZE_POD}"
log "initialized: ${INITIALIZED}"
log "sealed: ${SEALED}"

if [[ "${INITIALIZED}" == "true" ]]; then
    log "OpenBao is already initialized"

    [[ -n "${BAO_TOKEN:-}" ]] ||
        fatal \
            "OpenBao is already initialized but BAO_TOKEN is not available"
else
    log "OpenBao is not initialized; initializing ${INITIALIZE_POD}..."

    INIT_EXIT_CODE=0

    bao \
        "${INITIALIZE_PORT}" \
        operator init -format=json \
        >"${INIT_FILE}" \
        2>"${TMP_DIR}/init.stderr" \
    || INIT_EXIT_CODE=$?

    if [[ "${INIT_EXIT_CODE}" -ne 0 ]]; then
        log "bao operator init failed with exit code ${INIT_EXIT_CODE}"
        cat "${TMP_DIR}/init.stderr" >&2 || true

        kubectl logs \
            -n "${OPENBAO_NAMESPACE}" \
            "${INITIALIZE_POD}" \
            --tail=200 >&2 || true

        exit "${INIT_EXIT_CODE}"
    fi

    jq -e '.root_token' "${INIT_FILE}" >/dev/null ||
        fatal "OpenBao initialization did not return a root token"

    export BAO_TOKEN="$(jq -r '.root_token' "${INIT_FILE}")"

    log "OpenBao initialization completed"

    [[ -n "${SEAL_TYPE}" ]] ||
        fatal "unable to determine OpenBao seal type"

    log "seal type: ${SEAL_TYPE}"

    if [[ "${SEAL_TYPE}" == "shamir" ]]; then
        UNSEAL_THRESHOLD="$(
            jq -r '.threshold // 3' "${INIT_FILE}"
        )"

        mapfile -t UNSEAL_KEYS < <(
            jq -r \
                --argjson threshold "${UNSEAL_THRESHOLD}" \
                '.unseal_keys_b64[:$threshold][]' \
                "${INIT_FILE}"
        )

        [[ "${#UNSEAL_KEYS[@]}" -eq "${UNSEAL_THRESHOLD}" ]] ||
            fatal "OpenBao returned an unexpected number of unseal keys"

        log "Shamir seal threshold: ${UNSEAL_THRESHOLD}"
    fi

    unseal_pod() {
        local pod="$1"
        local port="${PORT_FORWARD_PORTS[$pod]}"

        log "unsealing ${pod}..."

        for key in "${UNSEAL_KEYS[@]}"; do
            bao \
                "${port}" \
                operator unseal "${key}" \
                >/dev/null
        done
    }

    case "${SEAL_TYPE}" in
        shamir)
            unseal_pod "${INITIALIZE_POD}"

            log "${INITIALIZE_POD} unsealed"

            for pod in "${OPENBAO_PODS[@]}"; do
                if [[ "${pod}" == "${INITIALIZE_POD}" ]]; then
                    continue
                fi

                log "waiting for ${pod} to join the initialized Raft cluster..."

                JOINED=false

                for _ in {1..120}; do
                    STATUS_FOLLOWER="$(
                        get_status "${pod}" 2>/dev/null || true
                    )"

                    if jq -e '.initialized == true' \
                        >/dev/null 2>&1 <<<"${STATUS_FOLLOWER}"; then
                        JOINED=true
                        break
                    fi

                    sleep 2
                done

                [[ "${JOINED}" == "true" ]] ||
                    fatal \
                        "${pod} did not join the initialized Raft cluster"

                log "${pod} joined the initialized Raft cluster"

                unseal_pod "${pod}"

                log "${pod} unsealed"
            done
            ;;

        gcpckms)
            log "GCP KMS auto-unseal detected"
            ;;

        *)
            fatal "unsupported OpenBao seal type: ${SEAL_TYPE}"
            ;;
    esac
fi

log "waiting for all OpenBao pods to become initialized and unsealed..."

for pod in "${OPENBAO_PODS[@]}"; do
    STATUS=""

    for _ in {1..120}; do
        STATUS="$(
            get_status "${pod}" 2>/dev/null || true
        )"

        if jq -e '
            .initialized == true and
            .sealed == false
        ' >/dev/null 2>&1 <<<"${STATUS}"; then
            break
        fi

        sleep 2
    done

    jq -e '
        .initialized == true and
        .sealed == false
    ' >/dev/null 2>&1 <<<"${STATUS}" ||
        fatal "${pod} is not initialized and unsealed"

    log "${pod} is initialized and unsealed"
done

log "OpenBao cluster initialized and unsealed"

log "waiting for the active OpenBao pod..."

ACTIVE_POD=""

for _ in {1..120}; do
    ACTIVE_PODS="$(
        kubectl get pods \
            -n "${OPENBAO_NAMESPACE}" \
            -l openbao-active=true \
            -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
            2>/dev/null |
        sed '/^$/d' |
        sort
    )"

    ACTIVE_COUNT="$(
        if [[ -n "${ACTIVE_PODS}" ]]; then
            wc -l <<<"${ACTIVE_PODS}"
        else
            printf '0\n'
        fi
    )"

    if [[ "${ACTIVE_COUNT}" -eq 1 ]]; then
        ACTIVE_POD="${ACTIVE_PODS}"
        break
    fi

    if [[ "${ACTIVE_COUNT}" -gt 1 ]]; then
        fatal \
            "expected one active OpenBao pod, found ${ACTIVE_COUNT}: " \
            "${ACTIVE_PODS//$'\n'/ }"
    fi

    sleep 2
done

[[ -n "${ACTIVE_POD}" ]] ||
    fatal "no OpenBao pod has the openbao-active=true label"

[[ -n "${PORT_FORWARD_PORTS[${ACTIVE_POD}]+x}" ]] ||
    fatal \
        "active pod ${ACTIVE_POD} was not among the discovered OpenBao pods"

ACTIVE_PORT="${PORT_FORWARD_PORTS[${ACTIVE_POD}]}"

log \
    "active OpenBao pod: ${ACTIVE_POD} " \
    "(localhost:${ACTIVE_PORT} -> 8200)"

log "finding latest OpenBao snapshot..."

LATEST_SNAPSHOT="$(
    aws s3api list-objects-v2 \
        --bucket "${SNAPSHOT_BUCKET}" \
        --prefix "${SNAPSHOT_PREFIX}" \
        --query 'sort_by(Contents,&LastModified)[-1].Key' \
        --output text
)"

[[ -n "${LATEST_SNAPSHOT}" ]] &&
[[ "${LATEST_SNAPSHOT}" != "None" ]] ||
    fatal \
        "no OpenBao snapshot found in " \
        "s3://${SNAPSHOT_BUCKET}/${SNAPSHOT_PREFIX}"

log "latest snapshot: ${LATEST_SNAPSHOT}"

log "downloading snapshot..."

aws s3 cp \
    "s3://${SNAPSHOT_BUCKET}/${LATEST_SNAPSHOT}" \
    "${RESTORE_FILE}"

[[ -s "${RESTORE_FILE}" ]] ||
    fatal "downloaded snapshot is empty: ${RESTORE_FILE}"

log "restoring Raft snapshot through active pod ${ACTIVE_POD}"

bao \
    "${ACTIVE_PORT}" \
    operator raft snapshot restore \
    -force \
    "${RESTORE_FILE}"

log "restore command completed"
log "bootstrap completed successfully"
