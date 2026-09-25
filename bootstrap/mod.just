set default-list
set default-script
set no-exit-message
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']


[confirm('Bootstrap cluster? [y|N]')]
[doc('Bootstrap a Talos & Kubernetes cluster end-to-end')]
cluster: talos kubeconfig base apps

[private]
talos:
    just log info "Running stage..." "stage" "{{ recipe_name() }}"

    if ! op=$(topf apply --auto-bootstrap --confirm=false 2>&1); then
        just log fatal \
            "Failed to apply Talos configuration and bootstrap the etcd cluster" \
            "stage" "{{ recipe_name() }}" \
            "output" "$op"
    fi

[private]
kubeconfig:
    just log info "Running stage..." "stage" "{{ recipe_name() }}"

    if ! topf kubeconfig > "$KUBECONFIG"; then
        just log fatal \
            "Failed to fetch kubeconfig" \
            "stage" "{{ recipe_name() }}"
    fi

[private]
api-ready:
    just log info "Running stage..." "stage" "{{ recipe_name() }}"

    api_server=$(kubectl config view \
        --raw \
        -o jsonpath='{.clusters[0].cluster.server}')

    until [[ "$(curl -ks \
        -o /dev/null \
        -w '%{http_code}' \
        --connect-timeout 2 \
        "${api_server}/readyz")" == "200" ]]; do

        just log info \
            "Waiting for kube-apiserver. Retrying in 5 seconds..." \
            "stage" "{{ recipe_name() }}"

        sleep 5
    done

[private]
base: api-ready
    just log info "Running stage..." "stage" "{{ recipe_name() }}"

    if ! helmfile \
        -f "{{ source_directory() }}/helmfile/crds.yaml" \
        template \
        --quiet \
        | yq ea -r -e 'select(.kind == "CustomResourceDefinition")' \
        | kubectl apply \
        --server-side \
        --force-conflicts \
        -f -; then

        just log fatal \
            "Failed to apply base CRDs" \
            "stage" "{{ recipe_name() }}"
    fi

[private]
deploy-apps:
    just log info "Running stage..." "stage" "{{ recipe_name() }}"

    if ! helmfile \
        -f "{{ source_directory() }}/helmfile/apps.yaml" \
        sync \
        --hide-notes; then

        just log fatal \
            "Failed to sync helmfile" \
            "stage" "{{ recipe_name() }}"
    fi
