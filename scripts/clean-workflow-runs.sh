#!/usr/bin/env bash

# Delete workflow runs - dwr

set -o errexit
set -o pipefail

declare repo=${1:?No owner/repo specified}
declare delete_all=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)
            delete_all=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

jqscript() {
    cat <<EOF
      def symbol:
        sub("skipped"; "SKIP") |
        sub("success"; "GOOD") |
        sub("failure"; "FAIL");

      def tz:
        gsub("[TZ]"; " ");

      .workflow_runs[]
        | [
            (.conclusion | symbol),
            (.created_at | tz),
            .id,
            .event,
            .name
          ]
        | @tsv
EOF
}

getruns() {
    gh api --paginate "/repos/$repo/actions/runs" \
        | jq -r -f <(jqscript)
}

selectruns() {
    if [[ "$delete_all" == true ]]; then
        getruns
    else
        getruns | fzf --multi
    fi
}

deleterun() {
    local run id result
    run=$1
    id="$(cut -f 3 <<< "$run")"
    if gh api -X DELETE "/repos/$repo/actions/runs/$id"; then
        printf "OK!\t%s\n" "$run"
    else
        printf "BAD\t%s\n" "$run" >&2
    fi
}

deleteruns() {
    while read -r run; do
        deleterun "$run"
        sleep 0.25
    done
}

main() {
    selectruns | deleteruns
}

main
