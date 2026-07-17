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

# Remove previous generated content
rm -rf "${OUTPUT_DIR:?}"/*



echo "Fetching CRDs..."


"${KUBECTL_ARGS[@]}" get crds -o yaml > "${TMP}/crds.yaml"


if [ ! -s "${TMP}/crds.yaml" ]; then
    echo "No CRDs returned from cluster"
    exit 1
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

declare -A GROUPS



for schema in "${CONVERSION_TMP}"/*.json; do


    [ -f "${schema}" ] || continue


    filename="$(basename "${schema}")"


    group="${filename%%_*}"

    output_name="${filename#*_}"



    mkdir -p "${OUTPUT_DIR}/${group}"



    cp "${schema}" \
       "${OUTPUT_DIR}/${group}/${output_name}"



    GROUPS["${group}"]=1


    SCHEMA_COUNT=$((SCHEMA_COUNT + 1))


done


shopt -u nullglob



if [ "${SCHEMA_COUNT}" -eq 0 ]; then
    echo "No schemas were generated"
    exit 1
fi



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


h1 {
    margin-bottom: 1rem;
}


#search {

    width: 350px;
    padding: 8px;
    margin-bottom: 2rem;
    font-size: 1rem;

}


.group {

    margin-bottom: 1rem;

}


.group-title {

    cursor: pointer;
    font-size: 1.15rem;
    font-weight: bold;
    padding: .5rem;

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

</style>



<script>


function filterSchemas() {


    const query =
        document
        .getElementById("search")
        .value
        .toLowerCase();



    document
    .querySelectorAll(".group")
    .forEach(group => {


        const matches =
            group.innerText
            .toLowerCase()
            .includes(query);



        group.style.display =
            matches
            ? ""
            : "none";



        if (query && matches) {

            group.open = true;

        }



        if (!query) {

            group.open = false;

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
    placeholder="Search schemas..."
    onkeyup="filterSchemas()"
/>


EOF



for group in $(printf "%s\n" "${!GROUPS[@]}" | sort); do


    group_dir="${OUTPUT_DIR}/${group}"


    group_count=$(find "${group_dir}" -maxdepth 1 -type f -name "*.json" | wc -l)



    cat >> "${OUTPUT_DIR}/index.html" <<EOF

<details class="group">

<summary class="group-title">

${group} (${group_count})

</summary>


<ul>

EOF



    for schema in "${group_dir}"/*.json; do


        filename="$(basename "${schema}")"


        relative_path="${group}/${filename}"



        printf \
            '<li><a href="%s">%s</a></li>\n' \
            "${relative_path}" \
            "${filename}" \
            >> "${OUTPUT_DIR}/index.html"


    done



    cat >> "${OUTPUT_DIR}/index.html" <<EOF

</ul>

</details>


EOF


done



cat >> "${OUTPUT_DIR}/index.html" <<'EOF'

</body>

</html>

EOF



echo
echo "====================================="
echo "Generated schemas: ${SCHEMA_COUNT}"
echo "Output directory: ${OUTPUT_DIR}"
echo "====================================="
