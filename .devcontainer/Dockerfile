FROM alpine:edge@sha256:8431297eedca8df8f1e6144803c6d7e057ecff2408aa6861213cb9e507acadf8

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID
# renovate: depName=fluxcd/flux2
ARG FLUX_VERSION=v2.4.0
# renovate: depName=getsops/sops
ARG SOPS_VERSION=v3.9.1
# renovate: depName=kubernetes/kubernetes
ARG KUBECTL_VERSION=v1.31.3
# renovate: depName=helmfile/helmfile
ARG HELMFILE_VERSION=v0.169.1
# renovate: depName=helm/helm
ARG HELM_VERSION=v3.16.3
# renovate: depName=go-task/task
ARG TASK_VERSION=v3.40.0
# renovate: depName=siderolabs/talos
ARG TALOSCTL_VERSION=v1.8.3
# renovate: depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.4.0

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
    bash-completion \
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
    curl -fsSLO "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl" && \
    curl -fsSLO "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl.sha256" && \
    echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check --strict && \
    mv ./kubectl /usr/local/bin/kubectl && \
    kubectl completion bash | sudo tee /etc/bash_completion.d/kubectl > /dev/null && \
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash -s -- -v $HELM_VERSION && \
    curl -fsSLO https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.linux.amd64 && \
    curl -fsSLO https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.checksums.txt && \
    curl -fsSLO https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.checksums.pem && \
    curl -fsSLO https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.checksums.sig && \
    cosign verify-blob sops-$SOPS_VERSION.checksums.txt \
      --certificate sops-$SOPS_VERSION.checksums.pem \
      --signature sops-$SOPS_VERSION.checksums.sig \
      --certificate-identity-regexp=https://github.com/getsops \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com && \
    grep "sops-$SOPS_VERSION.linux.amd64" sops-$SOPS_VERSION.checksums.txt > checksum-linux-amd64.txt && \
    echo "$(cat checksum-linux-amd64.txt)" | sha256sum --check --strict && \
    mv sops-$SOPS_VERSION.linux.amd64 /usr/local/bin/sops && \
    curl -fsSLO https://github.com/siderolabs/talos/releases/download/$TALOSCTL_VERSION/talosctl-linux-amd64 && \
    curl -fsSL -o talosctl_sha256sum.txt https://github.com/siderolabs/talos/releases/download/$TALOSCTL_VERSION/sha256sum.txt && \
    grep "talosctl-linux-amd64" talosctl_sha256sum.txt > talosctl_amd64_sha256sum.txt && \
    echo "$(cat talosctl_amd64_sha256sum.txt)" | sha256sum --check --strict && \
    mv ./talosctl-linux-amd64 /usr/local/bin/talosctl && \
    curl -fsSLO https://github.com/helmfile/helmfile/releases/download/$HELMFILE_VERSION/helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_checksums.txt && \
    curl -fsSLO https://github.com/helmfile/helmfile/releases/download/$HELMFILE_VERSION/helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_linux_amd64.tar.gz && \
    grep "helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_linux_amd64.tar.gz" helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_checksums.txt > checksum-helmfile-linux-amd64.txt && \
    echo "$(cat checksum-helmfile-linux-amd64.txt)" | sha256sum --check --strict && \
    tar -xvzf helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_linux_amd64.tar.gz && \
    mv helmfile /usr/local/bin/helmfile && \
    curl -fsSL https://taskfile.dev/install.sh | bash -s -- -d $TASK_VERSION -b /usr/local/bin && \
    curl -fsSL https://fluxcd.io/install.sh | FLUX_VERSION=$(echo $FLUX_VERSION | sed 's/^v//') bash && \
    curl -fsSLO https://github.com/kubevirt/kubevirt/releases/download/$VIRTCTL_VERSION/virtctl-$VIRTCTL_VERSION-linux-amd64 && \
    mv ./virtctl-$VIRTCTL_VERSION-linux-amd64 /usr/local/bin/virtctl && \
    echo "**** Setting permissions ****" && \
    chown -R root:root /usr/local/bin && chmod -R 755 /usr/local/bin && \
    echo "**** Cleaning up ****" && \
    rm -rf /root/.cache /tmp/*

WORKDIR /project

USER $USERNAME

CMD ["/bin/bash"]
