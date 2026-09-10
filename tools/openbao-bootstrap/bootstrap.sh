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

for command in kubectl bao jq aws; do
    require_command "$command"
done

readonly OPENBAO_NAMESPACE="${1:?usage: $0 <openbao-namespace>}"

readonly OPENBAO_LOCAL_PORT="${OPENBAO_LOCAL_PORT:-18200}"
readonly OPENBAO_TLS_SERVER_NAME="${OPENBAO_TLS_SERVER_NAME:-openbao.darkfellanetwork.com}"

readonly SNAPSHOT_BUCKET="${SNAPSHOT_BUCKET:-openbao-snapshots}"
readonly SNAPSHOT_PREFIX="${SNAPSHOT_PREFIX:-bao_}"

readonly TMP_DIR="$(mktemp -d -t openbao-bootstrap.XXXXXX)"
readonly INIT_FILE="$TMP_DIR/init.json"
readonly RESTORE_FILE="$TMP_DIR/restore.snapshot"
readonly PORT_FORWARD_LOG="$TMP_DIR/port-forward.log"

PORT_FORWARD_PID=""

cleanup() {
    local exit_code=$?

    if [[ -n "$PORT_FORWARD_PID" ]] &&
       kill -0 "$PORT_FORWARD_PID" 2>/dev/null; then
        log "stopping port-forward (pid=$PORT_FORWARD_PID)"
        kill "$PORT_FORWARD_PID" 2>/dev/null || true
        wait "$PORT_FORWARD_PID" 2>/dev/null || true
    fi

    rm -rf "$TMP_DIR"

    exit "$exit_code"
}

trap cleanup EXIT

# ---------------------------------------------------------------------------
# Helper: query OpenBao through the port-forward.
# ---------------------------------------------------------------------------

bao_status() {
    BAO_ADDR="https://127.0.0.1:${OPENBAO_LOCAL_PORT}" \
    BAO_TLS_SERVER_NAME="${OPENBAO_TLS_SERVER_NAME}" \
    bao status -format=json
}

# ---------------------------------------------------------------------------
# Find OpenBao pod
# ---------------------------------------------------------------------------

log "waiting for OpenBao pod creation..."

OPENBAO_POD=""

for _ in {1..120}; do
    OPENBAO_POD="$(
        kubectl get pods \
            -n "${OPENBAO_NAMESPACE}" \
            -l app.kubernetes.io/name=openbao \
            -l openbao-active=true \
            -o jsonpath='{.items[0].metadata.name}' \
            2>/dev/null || true
    )"

    if [[ -n "${OPENBAO_POD}" ]]; then
        break
    fi

    sleep 2
done

[[ -n "${OPENBAO_POD}" ]] ||
    fatal "OpenBao pod was not found"

log "using OpenBao pod: ${OPENBAO_POD}"

# ---------------------------------------------------------------------------
# Wait for pod to be Running.
# ---------------------------------------------------------------------------

log "waiting for OpenBao pod to become Running..."

kubectl wait \
    -n "${OPENBAO_NAMESPACE}" \
    --for=jsonpath='{.status.phase}'=Running \
    "pod/${OPENBAO_POD}" \
    --timeout=10m

# ---------------------------------------------------------------------------
# Start port-forward
# ---------------------------------------------------------------------------

log "starting port-forward..."

kubectl port-forward \
    -n "${OPENBAO_NAMESPACE}" \
    "pod/${OPENBAO_POD}" \
    "${OPENBAO_LOCAL_PORT}:8200" \
    >"${PORT_FORWARD_LOG}" 2>&1 &

PORT_FORWARD_PID=$!

# ---------------------------------------------------------------------------
# Wait until the OpenBao CLI can obtain a valid status response.
# ---------------------------------------------------------------------------

log "waiting for OpenBao..."

STATUS=""

for _ in {1..120}; do
    STATUS="$(bao_status)"

    if [[ -n "${STATUS}" ]] &&
       jq -e '
           .initialized != null and
           .sealed != null
       ' >/dev/null 2>&1 <<<"${STATUS}"; then
        break
    fi

    sleep 2
done

[[ -n "${STATUS}" ]] ||
    fatal "unable to query OpenBao through port-forward"

if ! jq -e '
    .initialized != null and
    .sealed != null
' >/dev/null 2>&1 <<<"${STATUS}"; then
    log "OpenBao status response:"
    jq . <<<"${STATUS}" 2>/dev/null || echo "${STATUS}"
    fatal "OpenBao returned an invalid status response"
fi

INITIALIZED="$(jq -r '.initialized' <<<"${STATUS}")"
SEALED="$(jq -r '.sealed' <<<"${STATUS}")"
SEAL_TYPE="$(jq -r '.type // empty' <<<"${STATUS}")"

log "initialized: ${INITIALIZED}"
log "sealed: ${SEALED}"

# ---------------------------------------------------------------------------
# Already initialized.
# ---------------------------------------------------------------------------

if [[ "${INITIALIZED}" == "true" ]]; then
    log "OpenBao is already initialized; nothing to do"
    exit 0
fi

# ---------------------------------------------------------------------------
# OpenBao is not initialized.
# ---------------------------------------------------------------------------

log "OpenBao is not initialized; initializing..."

bao operator init -format=json >"${INIT_FILE}"

jq -e '.root_token' "${INIT_FILE}" >/dev/null ||
    fatal "OpenBao initialization did not return a root token"

export BAO_TOKEN="$(jq -r '.root_token' "${INIT_FILE}")"

# ---------------------------------------------------------------------------
# Detect seal type after initialization.
# ---------------------------------------------------------------------------

STATUS="$(bao_status)"

SEAL_TYPE="$(jq -r '.type // empty' <<<"${STATUS}")"

[[ -n "${SEAL_TYPE}" ]] ||
    fatal "unable to determine OpenBao seal type after initialization"

log "seal type: ${SEAL_TYPE}"

# ---------------------------------------------------------------------------
# Unseal if required.
# ---------------------------------------------------------------------------

case "${SEAL_TYPE}" in
    shamir)
        log "Shamir seal detected; unsealing..."

        mapfile -t unseal_keys < <(
            jq -r '.unseal_keys_b64[]' "$INIT_FILE"
        )

        for key in "${unseal_keys[@]}"; do
            bao operator unseal "$key" >/dev/null
        done
        ;;

    gcpckms)
        log "GCP KMS auto-unseal detected; waiting for unseal..."
        ;;

    *)
        fatal "unsupported OpenBao seal type: ${SEAL_TYPE}"
        ;;
esac

# ---------------------------------------------------------------------------
# Wait for initialized + unsealed.
# ---------------------------------------------------------------------------

log "waiting for OpenBao to become unsealed..."

UNSEALED=false

for _ in {1..120}; do
    STATUS="$(bao_status)"

    CURRENT_INITIALIZED="$(
        jq -r '.initialized // false' <<<"${STATUS}" 2>/dev/null || echo false
    )"

    CURRENT_SEALED="$(
        jq -r '.sealed // true' <<<"${STATUS}" 2>/dev/null || echo true
    )"

    if [[ "${CURRENT_INITIALIZED}" == "true" &&
          "${CURRENT_SEALED}" == "false" ]]; then
        UNSEALED=true
        break
    fi

    sleep 2
done

[[ "${UNSEALED}" == "true" ]] ||
    fatal "OpenBao is still sealed"

log "OpenBao initialized and unsealed"

# ---------------------------------------------------------------------------
# Find latest snapshot.
# ---------------------------------------------------------------------------

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
    fatal "no OpenBao snapshot found in s3://${SNAPSHOT_BUCKET}/${SNAPSHOT_PREFIX}"

log "latest snapshot: ${LATEST_SNAPSHOT}"

# ---------------------------------------------------------------------------
# Download snapshot.
# ---------------------------------------------------------------------------

log "downloading snapshot..."

aws s3 cp \
    "s3://${SNAPSHOT_BUCKET}/${LATEST_SNAPSHOT}" \
    "${RESTORE_FILE}"

[[ -s "${RESTORE_FILE}" ]] ||
    fatal "downloaded snapshot is empty: ${RESTORE_FILE}"

# ---------------------------------------------------------------------------
# Restore snapshot.
# ---------------------------------------------------------------------------

log "restoring Raft snapshot..."

bao operator raft snapshot restore \
    -force \
    "${RESTORE_FILE}"

log "restore command completed"

log "bootstrap completed successfully"
