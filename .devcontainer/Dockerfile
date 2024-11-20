FROM alpine:3.20@sha256:1e42bbe2508154c9126d48c2b8a75420c3544343bf86fd041fb7527e017a4b4a

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID
# renovate: depName=fluxcd/flux2
ARG FLUX_VERSION=v2.0.0
ARG SOPS_VERSION=v3.9.1
ARG KUBECTL_VERSION=v1.31.2
ARG HELMFILE_VERSION=v0.169.1

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
    curl -LO "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl" && \
    curl -LO "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl.sha256" && \
    echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check --strict && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl && \
    curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 && \
    chmod +x get_helm.sh && \
    ./get_helm.sh && \
    curl -LO https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.linux.amd64 && \
    curl -LO https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.checksums.txt && \
    curl -LO https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.checksums.pem && \
    curl -LO https://github.com/getsops/sops/releases/download/$SOPS_VERSION/sops-$SOPS_VERSION.checksums.sig && \
    cosign verify-blob sops-$SOPS_VERSION.checksums.txt \
      --certificate sops-$SOPS_VERSION.checksums.pem \
      --signature sops-$SOPS_VERSION.checksums.sig \
      --certificate-identity-regexp=https://github.com/getsops \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com && \
    grep "sops-$SOPS_VERSION.linux.amd64" sops-$SOPS_VERSION.checksums.txt > checksum-linux-amd64.txt && \
    echo "$(cat checksum-linux-amd64.txt)" | sha256sum --check --strict && \
    mv sops-$SOPS_VERSION.linux.amd64 /usr/local/bin/sops && \
    chmod +x /usr/local/bin/sops && \
    curl -sL https://talos.dev/install | sh && \
    curl -LO https://github.com/helmfile/helmfile/releases/download/$HELMFILE_VERSION/helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_checksums.txt && \
    curl -LO https://github.com/helmfile/helmfile/releases/download/$HELMFILE_VERSION/helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_linux_amd64.tar.gz && \
    grep "helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_linux_amd64.tar.gz" helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_checksums.txt > checksum-helmfile-linux-amd64.txt && \
    echo "$(cat checksum-helmfile-linux-amd64.txt)" | sha256sum --check --strict && \
    tar -xvzf helmfile_$(echo $HELMFILE_VERSION | sed 's/^v//')_linux_amd64.tar.gz && \
    chmod +x ./helmfile && \
    mv helmfile /usr/local/bin/helmfile && \
    curl -fsSL -o get_task.sh https://taskfile.dev/install.sh && \
    chmod +x ./get_task.sh && \
    ./get_task.sh -d -b /usr/local/bin && \
    curl -s https://fluxcd.io/install.sh | FLUX_VERSION=$FLUX_VERSION bash && \
    echo "**** Cleaning up ****" && \
    rm -rf /root/.cache /tmp/*

WORKDIR /project

USER $USERNAME

CMD ["/bin/bash"]
