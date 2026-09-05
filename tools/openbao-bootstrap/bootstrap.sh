#!/usr/bin/env bash
set -euo pipefail

log() {
    echo "[bootstrap] $*"
}

fatal() {
    echo "[bootstrap] ERROR: $*" >&2
    exit 1
}

OPENBAO_NAMESPACE="${1:?OpenBao namespace must be provided}"

OPENBAO_LOCAL_PORT="${OPENBAO_LOCAL_PORT:-18200}"
OPENBAO_TLS_SERVER_NAME="${OPENBAO_TLS_SERVER_NAME:-openbao.darkfellanetwork.com}"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:?AWS_ENDPOINT_URL is required}"
export AWS_REGION="${AWS_REGION:-us-east-1}"

SNAPSHOT_BUCKET="${SNAPSHOT_BUCKET:-openbao-snapshots}"
SNAPSHOT_PREFIX="${SNAPSHOT_PREFIX:-bao_}"

TMP_DIR="/tmp/openbao-bootstrap"
INIT_FILE="${TMP_DIR}/init.json"
RESTORE_FILE="${TMP_DIR}/restore.snapshot"
PORT_FORWARD_LOG="${TMP_DIR}/port-forward.log"

mkdir -p "${TMP_DIR}"

PORT_FORWARD_PID=""

cleanup() {
    if [[ -n "${PORT_FORWARD_PID}" ]]; then
        log "stopping port-forward..."
        kill "${PORT_FORWARD_PID}" 2>/dev/null || true
        wait "${PORT_FORWARD_PID}" 2>/dev/null || true
        PORT_FORWARD_PID=""
    fi
}

trap cleanup EXIT

# ---------------------------------------------------------------------------
# Helper: query OpenBao through the port-forward.
# ---------------------------------------------------------------------------

bao_status() {
    BAO_ADDR="https://127.0.0.1:${OPENBAO_LOCAL_PORT}" \
    BAO_TLS_SERVER_NAME="${OPENBAO_TLS_SERVER_NAME}" \
    bao status -format=json 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Find OpenBao pod
# ---------------------------------------------------------------------------

log "waiting for OpenBao pod..."

OPENBAO_POD=""

for _ in {1..120}; do
    OPENBAO_POD="$(
        kubectl get pods \
            -n "${OPENBAO_NAMESPACE}" \
            -l app.kubernetes.io/name=openbao \
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

    if [[ "${SEALED}" == "false" ]]; then
        log "OpenBao is already initialized and unsealed"
        log "bootstrap already completed; nothing to do"
        exit 0
    fi

    log "OpenBao is initialized but sealed"

    case "${SEAL_TYPE}" in
        gcpckms)
            log "GCP KMS auto-unseal detected; waiting for unseal..."

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
                    log "OpenBao successfully auto-unsealed"
                    exit 0
                fi

                sleep 2
            done

            fatal "OpenBao remained sealed after waiting for GCP KMS auto-unseal"
            ;;

        shamir)
            fatal "OpenBao is initialized and sealed with Shamir; refusing to destroy or reinitialize it"
            ;;

        *)
            fatal "OpenBao is initialized and sealed with unsupported seal type: ${SEAL_TYPE:-unknown}"
            ;;
    esac
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

        jq -r '.unseal_keys_b64[]' "${INIT_FILE}" |
            while IFS= read -r key; do
                bao operator unseal "${key}" >/dev/null
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
