#!/usr/bin/env bash
set -euo pipefail

: "${BAO_ADDR:?BAO_ADDR must be set}"
: "${S3_BUCKET:?S3_BUCKET must be set}"
: "${S3_PREFIX:=}"
: "${AWS_REGION:=us-east-1}"

export BAO_ADDR

TMP_DIR="${TMP_DIR:-/tmp/openbao-bootstrap}"
mkdir -p "$TMP_DIR"

INIT_FILE="$TMP_DIR/init.json"
SNAPSHOT_FILE="$TMP_DIR/restore.snapshot"


echo "[bootstrap] waiting for OpenBao API..."

until bao status -format=json >/dev/null 2>&1; do
    sleep 5
done


STATUS="$(bao status -format=json || true)"

INITIALIZED="$(echo "$STATUS" | jq -r '.initialized // false')"

if [ "$INITIALIZED" = "true" ]; then
    echo "[bootstrap] ERROR: OpenBao is already initialized"
    exit 1
fi


echo "[bootstrap] initializing OpenBao..."

bao operator init -format=json > "$INIT_FILE"


ROOT_TOKEN="$(jq -r '.root_token' "$INIT_FILE")"

export BAO_TOKEN="$ROOT_TOKEN"


SEAL_TYPE="$(bao status -format=json | jq -r '.type')"

echo "[bootstrap] seal type: $SEAL_TYPE"


case "$SEAL_TYPE" in

    shamir)

        echo "[bootstrap] performing Shamir unseal"

        jq -r '.unseal_keys_b64[]' "$INIT_FILE" \
        | while read -r KEY; do
            bao operator unseal "$KEY" >/dev/null
        done

        ;;


    *)

        echo "[bootstrap] waiting for auto-unseal"

        until bao status -format=json \
            | jq -e '.sealed == false' >/dev/null
        do
            sleep 5
        done

        ;;

esac


echo "[bootstrap] verifying authentication..."

bao token lookup >/dev/null


echo "[bootstrap] locating newest snapshot..."


AWS_ARGS=""

if [ -n "${AWS_ENDPOINT_URL:-}" ]; then
    AWS_ARGS="--endpoint-url=${AWS_ENDPOINT_URL}"
fi


LATEST=$(
aws s3 ls \
    "s3://${S3_BUCKET}/${S3_PREFIX}" \
    --region "$AWS_REGION" \
    $AWS_ARGS \
    | awk '{print $4}' \
    | sort \
    | tail -n1
)


if [ -z "$LATEST" ]; then
    echo "[bootstrap] ERROR: no snapshot found"
    exit 1
fi


echo "[bootstrap] restoring snapshot: $LATEST"


aws s3 cp \
    "s3://${S3_BUCKET}/${S3_PREFIX}${LATEST}" \
    "$SNAPSHOT_FILE" \
    --region "$AWS_REGION" \
    $AWS_ARGS


echo "[bootstrap] restoring raft snapshot..."

bao operator raft snapshot restore \
    -force \
    "$SNAPSHOT_FILE"


echo "[bootstrap] restore completed"
