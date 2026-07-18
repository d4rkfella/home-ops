#!/usr/bin/env bash

set -euo pipefail

KUBECTL_ARGS=(kubectl)

if [[ -n "${KUBECTL_CONTEXT:-}" ]]; then
    KUBECTL_ARGS+=(--context="${KUBECTL_CONTEXT}")
fi


require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "$1 is required"
        exit 1
    fi
}


require_command kubectl
require_command python3


if ! python3 -c "import yaml" >/dev/null 2>&1; then
    echo "Python module 'pyyaml' is required"
    exit 1
fi


if [[ -z "${OUTPUT_DIR:-}" ]]; then
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


if [[ ! -s "${TMP}/crds.yaml" ]]; then
    echo "No CRDs returned"
    exit 1
fi


echo "Converting CRDs..."


export FILENAME_FORMAT="{fullgroup}_{kind}_{version}"


(
    cd "${CONVERSION_TMP}"

    python3 \
        "${SCRIPT_DIR}/openapi2jsonschema.py" \
        "${TMP}/crds.yaml"
)



echo "Organizing schemas..."


declare -A API_GROUPS

SCHEMA_COUNT=0


while IFS= read -r -d '' schema; do

    filename="${schema##*/}"

    group="${filename%%_*}"

    schema_name="${filename#*_}"


    mkdir -p "${OUTPUT_DIR}/${group}"


    cp -f \
        "${schema}" \
        "${OUTPUT_DIR}/${group}/${schema_name}"


    API_GROUPS["${group}"]+=" ${schema_name}"


    SCHEMA_COUNT=$((SCHEMA_COUNT + 1))


done < <(
    find "${CONVERSION_TMP}" \
        -maxdepth 1 \
        -type f \
        -name "*.json" \
        -print0
)



if [[ "${SCHEMA_COUNT}" -eq 0 ]]; then
    echo "No schemas generated"
    exit 1
fi



echo "Generating index..."



cat > "${OUTPUT_DIR}/index.html" <<'HTML'
<!DOCTYPE html>
<html>

<head>

<meta charset="UTF-8">

<title>Kubernetes CRD Schemas</title>


<style>

body {
    font-family: system-ui, sans-serif;
    margin: 2rem;
}


h1 {
    margin-bottom: 1rem;
}


#search {
    width: 350px;
    padding: 8px;
    font-size: 1rem;
    margin-bottom: 1.5rem;
}


details {
    margin-bottom: 1rem;
}


summary {
    cursor: pointer;
    font-size: 1.15rem;
    font-weight: bold;
}


ul {
    margin-top: .5rem;
}


li {
    margin: .25rem 0;
}


a {
    text-decoration: none;
}


.hidden {
    display:none;
}

</style>



<script>

function searchSchemas() {

    const q =
        document
        .getElementById("search")
        .value
        .toLowerCase();


    document
    .querySelectorAll("details")
    .forEach(group => {


        const groupMatch =
            group
            .querySelector("summary")
            .innerText
            .toLowerCase()
            .includes(q);


        let visible = groupMatch;


        group
        .querySelectorAll("li")
        .forEach(item => {

            const match =
                groupMatch ||
                item.innerText
                .toLowerCase()
                .includes(q);


            item.classList.toggle(
                "hidden",
                !match
            );


            if (match) {
                visible = true;
            }

        });



        group.classList.toggle(
            "hidden",
            !visible
        );


        if (q && visible) {
            group.open = true;
        }


    });


}

</script>


</head>


<body>


<h1>Kubernetes CRD Schemas</h1>


<input
 id="search"
 type="text"
 placeholder="Search CRDs..."
 onkeyup="searchSchemas()"
/>


HTML



while IFS= read -r group; do


    echo "<details>" >> "${OUTPUT_DIR}/index.html"


    echo "<summary>${group}</summary>" \
        >> "${OUTPUT_DIR}/index.html"


    echo "<ul>" \
        >> "${OUTPUT_DIR}/index.html"



    while IFS= read -r schema; do


        printf \
        '<li><a href="%s/%s">%s</a></li>\n' \
        "${group}" \
        "${schema}" \
        "${schema}" \
        >> "${OUTPUT_DIR}/index.html"


    done < <(
        printf '%s\n' ${API_GROUPS[$group]} | sort -f
    )



    echo "</ul></details>" \
        >> "${OUTPUT_DIR}/index.html"


done < <(
    printf '%s\n' "${!API_GROUPS[@]}" | sort -f
)



cat >> "${OUTPUT_DIR}/index.html" <<'HTML'

</body>
</html>

HTML



echo
echo "====================================="
echo "Generated schemas: ${SCHEMA_COUNT}"
echo "Output directory: ${OUTPUT_DIR}"
echo "====================================="

