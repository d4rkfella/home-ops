set default-list
set default-script
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

[doc('Prune pods in Failed, Pending, or Succeeded state')]
prune-pods:
    for phase in Failed Pending Succeeded; do
        kubectl delete pods -A --field-selector status.phase="$phase" --ignore-not-found=true
    done

[arg('resource', pattern='hr|ks|gitrepo|ocirepo|es')]
[doc('Sync a resource')]
sync resource:
    kubectl get {{ resource }} --no-headers -A | while read -r ns name _; do
        kubectl -n "$ns" annotate --field-manager flux-client-side-apply --overwrite {{ resource }} "$name" \
            "force-sync=$(date +%s)" \
            "reconcile.fluxcd.io/requestedAt=$(date +%s)" \
            "reconcile.fluxcd.io/forceAt=$(date +%s)"
    done

[doc('Browse a PVC')]
browse-pvc ns='' claim='' user='65532':
    command -v gum >/dev/null || just log fatal "Missing gum"
    command -v kubectl >/dev/null || just log fatal "Missing kubectl"

    if [[ -z "{{ claim }}" ]]; then
        claim=$(gum input --placeholder 'PVC name')
    fi

    [[ -n "$claim" ]] || just log fatal "No PVC specified"

    if [[ -z "{{ ns }}" ]]; then
        ns=$(gum input --placeholder 'Namespace')
    fi

    [[ -n "$ns" ]] || just log fatal "No namespace specified"

    if [[ -z "{{ user }}" ]]; then
        user=$(gum input \
            --placeholder 'User ID' \
            --value '65532')
    fi

    [[ -n "$user" ]] || just log fatal "No user ID specified"

    pod="filebrowser-${claim}"

    just log info \
        "Starting File Browser" \
        "claim" "$claim" \
        "namespace" "$ns"

    kubectl run "$pod" \
        --image=filebrowser/filebrowser:latest \
        --restart=Never \
        --namespace="$ns" \
        --overrides="{
            \"spec\": {
                \"securityContext\": {
                    \"fsGroup\": $user
                },
                \"containers\": [{
                    \"name\": \"filebrowser\",
                    \"image\": \"filebrowser/filebrowser:latest\",
                    \"args\": [
                        \"--noauth\",
                        \"--root\", \"/data\",
                        \"--config\", \"/tmp/settings.json\",
                        \"--database\", \"/tmp/filebrowser.db\"
                    ],
                    \"ports\": [{
                        \"containerPort\": 80
                    }],
                    \"volumeMounts\": [{
                        \"mountPath\": \"/data\",
                        \"name\": \"data\"
                    }]
                }],
                \"volumes\": [{
                    \"name\": \"data\",
                    \"persistentVolumeClaim\": {
                        \"claimName\": \"$claim\"
                    }
                }]
            }
        }"

    trap 'kubectl delete pod "$pod" --namespace="$ns" --ignore-not-found >/dev/null 2>&1 || true' EXIT

    kubectl wait "pod/$pod" \
        --for=condition=Ready \
        --namespace="$ns" \
        --timeout=60s

    just log info "Opening File Browser at http://localhost:8080"

    xdg-open http://localhost:8080 >/dev/null 2>&1 &

    kubectl port-forward \
        "pod/$pod" \
        8080:80 \
        --namespace="$ns"

[doc('Open a VNC session to a VM')]
vnc vm='' ns='':
    command -v gum >/dev/null || just log fatal "Missing gum"
    command -v kubectl >/dev/null || just log fatal "Missing kubectl"
    command -v virtctl >/dev/null || just log fatal "Missing virtctl"
    command -v vncviewer >/dev/null || just log fatal "Missing vncviewer"

    if [[ -z "{{ vm }}" ]]; then
        if [[ -z "{{ ns }}" ]]; then
            selection=$(kubectl get virtualmachines -A \
                -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}' |
                gum choose --header 'Select VM')

            [[ -n "$selection" ]] || just log fatal "No VM selected"

            selected_ns="${selection%%$'\t'*}"
            selected_vm="${selection#*$'\t'}"

            virtctl vnc \
                --vnc-type=tiger \
                --vnc-path=/usr/bin/vncviewer \
                --namespace "$selected_ns" \
                "$selected_vm"
        else
            selection=$(kubectl get virtualmachines \
                -n "{{ ns }}" \
                -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' |
                gum choose --header 'Select VM')

            [[ -n "$selection" ]] || just log fatal "No VM selected"

            virtctl vnc \
                --vnc-type=tiger \
                --vnc-path=/usr/bin/vncviewer \
                --namespace "{{ ns }}" \
                "$selection"
        fi
    else
        virtctl vnc \
            --vnc-type=tiger \
            --vnc-path=/usr/bin/vncviewer \
            --namespace "{{ ns }}" \
            "{{ vm }}"
    fi


[doc('Connect to a VM console')]
console vm='' ns='':
    command -v gum >/dev/null || just log fatal "Missing gum"
    command -v kubectl >/dev/null || just log fatal "Missing kubectl"
    command -v virtctl >/dev/null || just log fatal "Missing virtctl"

    if [[ -z "{{ vm }}" ]]; then
        if [[ -z "{{ ns }}" ]]; then
            selection=$(kubectl get virtualmachines -A \
                -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}' |
                gum choose --header 'Select VM')

            [[ -n "$selection" ]] || just log fatal "No VM selected"

            selected_ns="${selection%%$'\t'*}"
            selected_vm="${selection#*$'\t'}"

            virtctl console \
                --namespace "$selected_ns" \
                "$selected_vm"
        else
            selection=$(kubectl get virtualmachines \
                -n "{{ ns }}" \
                -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' |
                gum choose --header 'Select VM')

            [[ -n "$selection" ]] || just log fatal "No VM selected"

            virtctl console \
                --namespace "{{ ns }}" \
                "$selection"
        fi
    else
        virtctl console \
            --namespace "{{ ns }}" \
            "{{ vm }}"
    fi
