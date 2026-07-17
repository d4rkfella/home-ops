#!/usr/bin/env bash

set -euo pipefail

KUBECTL_ARGS=(kubectl)

if [ -n "${KUBECTL_CONTEXT:-}" ]; then
    KUBECTL_ARGS=(kubectl --context="${KUBECTL_CONTEXT}")
fi


if ! command -v kubectl >/dev/null 2>&1; then
    echo "kubectl is required"
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required"
    exit 1
fi

if ! python3 -c "import yaml" >/dev/null 2>&1; then
    echo "Python module 'pyyaml' is required"
    exit 1
fi


if [ -z "${OUTPUT_DIR:-}" ]; then
    echo "OUTPUT_DIR must be set"
    exit 1
fi


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TMP="$(mktemp -d)"
CONVERSION_TMP="$(mktemp -d)"

trap 'rm -rf "${TMP}" "${CONVERSION_TMP}"' EXIT


mkdir -p "${OUTPUT_DIR}"


fetch_crd() {
    local crd="$1"

    echo "Fetching CRD: ${crd}"

    if "${KUBECTL_ARGS[@]}" get crd "${crd}" -o yaml \
        > "${TMP}/${crd}.yaml"; then

        return 0

    fi

    echo "Warning: Failed to fetch CRD: ${crd}" >&2

    echo "kubectl error:" >&2

    "${KUBECTL_ARGS[@]}" get crd "${crd}" -o yaml \
        >/dev/null 2>&1 || true

    rm -f "${TMP}/${crd}.yaml"

    return 0
}


echo "Fetching list of CRDs..."


mapfile -t CRD_LIST < <(
    "${KUBECTL_ARGS[@]}" get crds -o name |
    sed 's#customresourcedefinition.apiextensions.k8s.io/##'
)


if [ "${#CRD_LIST[@]}" -eq 0 ]; then
    echo "No CRDs found"
    exit 0
fi


if [ -n "${CRD_FILTER:-}" ]; then

    mapfile -t CRD_LIST < <(
        printf '%s\n' "${CRD_LIST[@]}" |
        grep -E "${CRD_FILTER}" || true
    )

fi


echo "Found ${#CRD_LIST[@]} CRDs"


PARALLELISM="${PARALLELISM:-10}"


for crd in "${CRD_LIST[@]}"; do

    fetch_crd "${crd}" &

    while [ "$(jobs -r | wc -l)" -ge "${PARALLELISM}" ]; do
        sleep 1
    done

done


wait || true


if ! compgen -G "${TMP}/*.yaml" >/dev/null; then

    echo "No CRD YAML files were fetched"
    exit 1

fi


echo "Converting CRDs to JSON schemas..."


export FILENAME_FORMAT="{fullgroup}_{kind}_{version}"


(
    cd "${CONVERSION_TMP}"

    python3 \
        "${SCRIPT_DIR}/openapi2jsonschema.py" \
        "${TMP}"/*.yaml
)


echo "Copying schemas..."


shopt -s nullglob

SCHEMA_COUNT=0


for schema in "${CONVERSION_TMP}"/*.json; do

    filename="$(basename "${schema}")"

    group="$(echo "${filename}" | cut -d '_' -f1)"

    output_name="$(echo "${filename}" | cut -d '_' -f2-)"


    mkdir -p "${OUTPUT_DIR}/${group}"


    cp "${schema}" \
       "${OUTPUT_DIR}/${group}/${output_name}"


    ((SCHEMA_COUNT++))

done


shopt -u nullglob



echo "Generating index.html..."


cat > "${OUTPUT_DIR}/index.html" <<'EOF'
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Kubernetes CRD Schemas</title>
<style>
body {
    font-family: sans-serif;
    margin: 2rem;
}

li {
    margin: 0.25rem 0;
}

a {
    text-decoration: none;
}
</style>
</head>
<body>

<h1>Kubernetes CRD Schemas</h1>

<ul>
EOF


find "${OUTPUT_DIR}" \
    -type f \
    -name "*.json" \
    | sort \
    | sed "s#${OUTPUT_DIR}/##" \
    | while read -r schema; do

        echo "<li><a href=\"${schema}\">${schema}</a></li>" \
            >> "${OUTPUT_DIR}/index.html"

done


cat >> "${OUTPUT_DIR}/index.html" <<'EOF'
</ul>

</body>
</html>
EOF



echo
echo "====================================="
echo "Generated schemas: ${SCHEMA_COUNT}"
echo "Output directory: ${OUTPUT_DIR}"
echo "====================================="

