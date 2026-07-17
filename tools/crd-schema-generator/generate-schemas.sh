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


echo "Fetching CRDs..."

"${KUBECTL_ARGS[@]}" get crds -o yaml > "${TMP}/crds.yaml"


if [ ! -s "${TMP}/crds.yaml" ]; then
    echo "No CRDs returned"
    exit 1
fi


if [ -n "${CRD_FILTER:-}" ]; then

    echo "Filtering CRDs using: ${CRD_FILTER}"

    python3 - "${TMP}/crds.yaml" "${TMP}/filtered.yaml" "${CRD_FILTER}" <<'PY'
import sys
import re
import yaml

source = sys.argv[1]
dest = sys.argv[2]
pattern = sys.argv[3]

with open(source) as f:
    data = yaml.safe_load(f)

items = [
    item for item in data.get("items", [])
    if re.search(pattern, item["metadata"]["name"])
]

data["items"] = items

with open(dest, "w") as f:
    yaml.safe_dump(data, f)
PY

    mv "${TMP}/filtered.yaml" "${TMP}/crds.yaml"

fi


CRD_COUNT=$(python3 - "${TMP}/crds.yaml" <<'PY'
import sys
import yaml

with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)

print(len(data.get("items", [])))
PY
)


echo "Found ${CRD_COUNT} CRDs"


if [ "${CRD_COUNT}" -eq 0 ]; then
    echo "No CRDs to convert"
    exit 0
fi


echo "Converting CRDs to JSON schemas..."


export FILENAME_FORMAT="{fullgroup}_{kind}_{version}"


(
    cd "${CONVERSION_TMP}"

    python3 \
        "${SCRIPT_DIR}/openapi2jsonschema.py" \
        "${TMP}/crds.yaml"
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
