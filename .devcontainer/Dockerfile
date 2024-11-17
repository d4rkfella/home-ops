FROM alpine:3.20@sha256:1e42bbe2508154c9126d48c2b8a75420c3544343bf86fd041fb7527e017a4b4a

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

WORKDIR /tmp

RUN apk add --no-cache \
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
    unzip \
    sudo && \
    addgroup -g $USER_GID $USERNAME && \
    adduser -u $USER_UID -G $USERNAME -s /bin/sh -D $USERNAME && \
    \
    echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME && \
    chmod 0440 /etc/sudoers.d/$USERNAME && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256" && \
    echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check --strict && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl && \
    curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 && \
    chmod 700 get_helm.sh && \
    ./get_helm.sh && \
    curl -LO https://github.com/getsops/sops/releases/download/$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name')/sops-$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name').linux.amd64 && \
    curl -LO https://github.com/getsops/sops/releases/download/$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name')/sops-$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name').checksums.txt && \
    curl -LO https://github.com/getsops/sops/releases/download/$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name')/sops-$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name').checksums.pem && \
    curl -LO https://github.com/getsops/sops/releases/download/$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name')/sops-$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name').checksums.sig && \
    cosign verify-blob sops-$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name').checksums.txt \
      --certificate sops-$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name').checksums.pem \
      --signature sops-$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name').checksums.sig \
      --certificate-identity-regexp=https://github.com/getsops \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com && \
    grep "sops-$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name').linux.amd64" sops-$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name').checksums.txt > checksum-linux-amd64.txt && \
    echo "$(cat checksum-linux-amd64.txt)" | sha256sum --check --strict && \
    mv sops-$(curl -s https://api.github.com/repos/getsops/sops/releases/latest | jq -r '.tag_name').linux.amd64 /usr/local/bin/sops && \
    chmod +x /usr/local/bin/sops && \
    curl -sL https://talos.dev/install | sh && \
    curl -LO https://github.com/helmfile/helmfile/releases/download/$(curl -s https://api.github.com/repos/helmfile/helmfile/releases/latest | jq -r '.tag_name')/helmfile_$(curl -s https://api.github.com/repos/helmfile/helmfile/releases/latest | jq -r '.tag_name' | sed 's/^v//')_checksums.txt && \
    curl -LO https://github.com/helmfile/helmfile/releases/download/$(curl -s https://api.github.com/repos/helmfile/helmfile/releases/latest | jq -r '.tag_name')/helmfile_$(curl -s https://api.github.com/repos/helmfile/helmfile/releases/latest | jq -r '.tag_name' | sed 's/^v//')_linux_amd64.tar.gz && \
    grep "helmfile_$(curl -s https://api.github.com/repos/helmfile/helmfile/releases/latest | jq -r '.tag_name' | sed 's/^v//')_linux_amd64.tar.gz" helmfile_$(curl -s https://api.github.com/repos/helmfile/helmfile/releases/latest | jq -r '.tag_name' | sed 's/^v//')_checksums.txt > checksum-helmfile-linux-amd64.txt && \
    echo "$(cat checksum-helmfile-linux-amd64.txt)" | sha256sum --check --strict && \
    tar -xvzf helmfile_$(curl -s https://api.github.com/repos/helmfile/helmfile/releases/latest | jq -r '.tag_name' | sed 's/^v//')_linux_amd64.tar.gz && \
    chmod +x ./helmfile && \
    mv helmfile /usr/local/bin/helmfile && \
    curl -fsSL -o get_task.sh https://taskfile.dev/install.sh && \
    chmod +x ./get_task.sh && \
    ./get_task.sh -d -b /usr/local/bin && \
    echo "**** Cleaning temporary directory ****" && \
    rm -rf /root/.cache /tmp/*

USER $USERNAME

CMD ["/bin/sh"]
