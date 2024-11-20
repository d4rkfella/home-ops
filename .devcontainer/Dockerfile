FROM alpine:3.20@sha256:1e42bbe2508154c9126d48c2b8a75420c3544343bf86fd041fb7527e017a4b4a

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID
# renovate: depName=fluxcd/flux2
ARG FLUX_VERSION=v2.4.0
# renovate: depName=getsops/sops
ARG SOPS_VERSION=v3.9.1
ARG KUBECTL_VERSION=v1.31.2
# renovate: depName=helmfile/helmfile
ARG HELMFILE_VERSION=v0.169.1
# renovate: depName=helm/helm
ARG HELM_VERSION=v3.16.2
# renovate: depName=go-task/task
ARG TASK_VERSION=v3.40.0
# renovate: depName=siderolabs/talos
ARG TALOSCTL_VERSION=v1.8.3

ENV SHELL=/bin/bash

WORKDIR /tmp

RUN echo "**** Installing packages ****" && \ 
    apk add --no-cache \
    coreutils \
    curl \
    cosign \
    jq \
    nano \
    bash \
    openssl \
    ca-certificates \
    git \
    github-cli \
    libstdc++ \
    direnv \
    yq \
    unzip && \
    echo "**** Creating user and group ****" && \
    addgroup -g $USER_GID $USERNAME && \
    adduser -u $USER_UID -G $USERNAME -s /bin/sh -D $USERNAME && \
    echo "**** Adding direnv hook ****" && \
    echo 'eval "$(direnv hook bash)"' >> /home/$USERNAME/.bashrc && \
    echo "**** Installing binaries ****" && \
    curl -fsSL -O "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl" && \
    curl -fsSL -O "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl.sha256" && \
    echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check --strict && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl && \
    curl -fsSL -O get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 && \
    chmod +x get_helm.sh && \
    ./get_helm.sh -v $HELM_VERSION && \
    curl -fsSL -O https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.linux.amd64 && \
    curl -fsSL -O https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.checksums.txt && \
    curl -fsSL -O https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.checksums.pem && \
    curl -fsSL -O https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.checksums.sig && \
    cosign verify-blob sops-$SOPS_VERSION.checksums.txt \
      --certificate sops-$SOPS_VERSION.checksums.pem \
      --signature sops-$SOPS_VERSION.checksums.sig \
      --certificate-identity-regexp=https://github.com/getsops \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com && \
    grep "sops-$SOPS_VERSION.linux.amd64" sops-$SOPS_VERSION.checksums.txt > checksum-linux-amd64.txt && \
    echo "$(cat checksum-linux-amd64.txt)" | sha256sum --check --strict && \
    mv sops-$SOPS_VERSION.linux.amd64 /usr/local/bin/sops && \
    chmod +x /usr/local/bin/sops && \
    curl -fsSL -O https://github.com/siderolabs/talos/releases/download/$TALOSCTL_VERSION/talosctl-linux-amd64 && \
    curl -fsSL -O talosctl_sha256sum.txt https://github.com/siderolabs/talos/releases/download/$TALOSCTL_VERSION/sha256sum.txt && \
    grep "talosctl-linux-amd64" talosctl_sha256sum.txt > talosctl_amd64_sha256sum.txt && \
    echo "$(cat talosctl_amd64_sha256sum.txt)" | sha256sum --check --strict && \
    chmod +x ./talosctl-linux-amd64 && mv ./talosctl-linux-amd64 /usr/local/bin/talosctl && \
    curl -fsSL -O https://github.com/helmfile/helmfile/releases/download/$HELMFILE_VERSION/helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_checksums.txt && \
    curl -fsSL -O https://github.com/helmfile/helmfile/releases/download/$HELMFILE_VERSION/helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_linux_amd64.tar.gz && \
    grep "helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_linux_amd64.tar.gz" helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_checksums.txt > checksum-helmfile-linux-amd64.txt && \
    echo "$(cat checksum-helmfile-linux-amd64.txt)" | sha256sum --check --strict && \
    tar -xvzf helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_linux_amd64.tar.gz && \
    chmod +x ./helmfile && \
    mv helmfile /usr/local/bin/helmfile && \
    curl -fsSL https://taskfile.dev/install.sh | bash -s -- -d $TASK_VERSION -b /usr/local/bin && \
    curl -fsSL https://fluxcd.io/install.sh | FLUX_VERSION=$(echo $FLUX_VERSION | sed 's/^v//') bash && \
    echo "**** Cleaning up ****" && \
    rm -rf /root/.cache /tmp/*

WORKDIR /project

USER $USERNAME

CMD ["/bin/bash"]
