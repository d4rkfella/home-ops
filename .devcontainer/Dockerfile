FROM alpine:edge@sha256:f4b9f111e2c5290552a920590dd48dc58f5ea1cacda6e25b0a2718974d090cf0

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID
# renovate: depName=fluxcd/flux2
ARG FLUX_VERSION=v2.4.0
# renovate: depName=getsops/sops
ARG SOPS_VERSION=v3.9.2
# renovate: depName=kubernetes/kubernetes
ARG KUBECTL_VERSION=v1.31.3
# renovate: depName=helmfile/helmfile
ARG HELMFILE_VERSION=v0.169.2
# renovate: depName=helm/helm
ARG HELM_VERSION=v3.16.3
# renovate: depName=go-task/task
ARG TASK_VERSION=v3.40.1
# renovate: depName=siderolabs/talos
ARG TALOSCTL_VERSION=v1.8.3
# renovate: depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.4.0
# renovate: depName=int128/kubelogin
ARG KUBELOGIN_VERSION=v1.31.0
# renovate: depName=cilium/hubble
ARG HUBBLE_VERSION=v1.16.4
# renovate: depName=cilium/cilium-cli
ARG CILIUM_VERSION=v0.16.21

ENV LANG="C.UTF-8"
ENV SHELL=/bin/bash
ENV EDITOR=/usr/bin/nano

WORKDIR /tmp

RUN apk update && \
    apk upgrade && \
    apk add --no-cache \
    coreutils \
    curl \
    cosign \
    jq \
    nano \
    bash \
    bash-completion \
    openssl \
    ca-certificates \
    git \
    github-cli \
    libstdc++ \
    direnv \
    yq \
    aws-cli \
    unzip && \
    rm -rf /var/cache/apk/* && \
    addgroup -g $USER_GID $USERNAME && \
    adduser -u $USER_UID -G $USERNAME -s /bin/sh -D $USERNAME && \
    echo 'alias k=kubectl' >> /home/$USERNAME/.bashrc && \
    echo 'complete -o default -F __start_kubectl k' >> /home/$USERNAME/.bashrc && \
    echo 'eval "$(direnv hook bash)"' >> /home/$USERNAME/.bashrc && \
    curl -fsSLO "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl" && \
    curl -fsSLO "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl.sha256" && \
    echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check --strict && \
    mv ./kubectl /usr/local/bin/kubectl && \
    curl -L --fail --remote-name-all https://github.com/cilium/cilium-cli/releases/download/$CILIUM_VERSION/cilium-linux-amd64.tar.gz{,.sha256sum} && \
    sha256sum --check --strict cilium-linux-amd64.tar.gz.sha256sum && \
    tar xzvf cilium-linux-amd64.tar.gz -C /usr/local/bin && \
    curl -L --fail --remote-name-all https://github.com/cilium/hubble/releases/download/$HUBBLE_VERSION/hubble-linux-amd64.tar.gz{,.sha256sum} && \
    sha256sum --check --strict hubble-linux-amd64.tar.gz.sha256sum && \
    tar xzvf hubble-linux-amd64.tar.gz -C /usr/local/bin && \
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash -s -- -v $HELM_VERSION && \
    curl -fsSLO https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION{,.linux.amd64,.checksums.txt,.checksums.pem,.checksums.sig} && \
    cosign verify-blob sops-$SOPS_VERSION.checksums.txt \
      --certificate sops-$SOPS_VERSION.checksums.pem \
      --signature sops-$SOPS_VERSION.checksums.sig \
      --certificate-identity-regexp=https://github.com/getsops \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com && \
    sha256sum --check --strict --ignore-missing sops-$SOPS_VERSION.checksums.txt && \
    mv sops-$SOPS_VERSION.linux.amd64 /usr/local/bin/sops && \
    curl -fsSLO https://github.com/siderolabs/talos/releases/download/$TALOSCTL_VERSION/{,talosctl-linux-amd64,sha256sum.txt} && \
    sha256sum --check --strict --ignore-missing sha256sum.txt && \
    mv ./talosctl-linux-amd64 /usr/local/bin/talosctl && \
    curl -fsSLO https://github.com/helmfile/helmfile/releases/download/$HELMFILE_VERSION/helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//'){,_linux_amd64.tar.gz,_checksums.txt} && \
    sha256sum --check --strict --ignore-missing helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_checksums.txt && \
    tar -xvzf helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_linux_amd64.tar.gz && \
    mv helmfile /usr/local/bin/helmfile && \
    curl -fsSL https://taskfile.dev/install.sh | bash -s -- -d $TASK_VERSION -b /usr/local/bin && \
    curl -fsSL https://fluxcd.io/install.sh | FLUX_VERSION=$(echo $FLUX_VERSION | sed 's/^v//') bash && \
    curl -fsSLO https://github.com/kubevirt/kubevirt/releases/download/$VIRTCTL_VERSION/virtctl-$VIRTCTL_VERSION-linux-amd64 && \
    mv ./virtctl-$VIRTCTL_VERSION-linux-amd64 /usr/local/bin/virtctl && \
    curl -fsSLO https://github.com/int128/kubelogin/releases/download/$KUBELOGIN_VERSION/kubelogin_linux_amd64.zip{,.sha256} && \
    sha256sum --check --strict kubelogin_linux_amd64.zip.sha256 && \
    unzip -n kubelogin_linux_amd64.zip && \
    mv ./kubelogin /usr/local/bin/kubectl-oidc_login && \
    chown -R root:root /usr/local/bin && chmod -R 755 /usr/local/bin && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME && chmod -R 750 /home/$USERNAME && \
    kubectl completion bash | tee /etc/bash_completion.d/kubectl > /dev/null && \
    rm -rf /root/.cache /tmp/*

WORKDIR /project

USER $USERNAME

SHELL ["/bin/bash", "-c"]
