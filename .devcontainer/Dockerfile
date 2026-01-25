FROM debian:trixie-slim@sha256:77ba0164de17b88dd0bf6cdc8f65569e6e5fa6cd256562998b62553134a00ef0

ARG USERNAME=vscode
ARG USER_UID=2100
ARG USER_GID=$USER_UID

WORKDIR /tmp
SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND="noninteractive" \
    DOCKER_BUILDKIT=1 \
    LIBGUESTFS_BACKEND=direct \
    LIBGUESTFS_PATH=/usr/local/lib/guestfs/appliance \
    LANG="C.UTF-8" \
    EDITOR=/usr/bin/nano

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg xz-utils unzip \
        jq nano bash bash-completion git \
        libguestfs-tools direnv docker-cli docker-buildx tigervnc-viewer \
        libusb-1.0-0 usbredirect fontconfig fonts-dejavu && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/siderolabs/talosctl:v1.12.2@sha256:94425fac31d7685e9af3f912e7dc8f895a7167429f57b058f7cb7b6f5afa77c5 /talosctl /usr/local/bin/talosctl
RUN talosctl version --client

COPY --from=ghcr.io/sigstore/cosign/cosign:v3.0.4@sha256:0b015a3557a64a751712da8a6395534160018eaaa2d969882a85a336de9adb70 /ko-app/cosign /usr/local/bin/
RUN cosign version

COPY --from=ghcr.io/helmfile/helmfile:v1.2.3@sha256:8856e65c39ef4afb2a6852b34b5e9f535a866927b7ffe95a5ea805de63353548 /usr/local/bin/helmfile /usr/local/bin/
RUN helmfile --version

COPY --from=ghcr.io/astral-sh/uv:0.9.26-trixie@sha256:7393efbaa4445d1ebbeab2a472850d6f1705f2e6a065b88a8236fc0413321472 /usr/local/bin/uv* /usr/local/bin/
RUN uv self version && uvx --version

COPY --from=ghcr.io/getsops/sops:v3.11.0@sha256:6ce00ac946e1a52b2d1e5b7087441f7b6ef7bad907753104013f8bdb8f5fd891 /usr/local/bin/sops /usr/local/bin/
RUN sops --version

COPY --from=mikefarah/yq:4.50.1@sha256:4facc66fdcc785ec961ef7f2185f53f862f462eefe1d50c2eb311c2bb26823e3 /usr/bin/yq /usr/local/bin/
RUN yq --version

# renovate: datasource=github-releases depName=go-task/task
ARG TASK_VERSION=v3.47.0
RUN curl -fsSLO "https://github.com/go-task/task/releases/download/$TASK_VERSION/task_{linux_amd64.tar.gz,checksums.txt}" && \
    sha256sum -c --strict --ignore-missing task_checksums.txt && \
    tar -xvzf task_linux_amd64.tar.gz && \
    mv task /usr/local/bin/task && \
    rm -rf /tmp/*

# renovate: datasource=github-releases depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.7.0
RUN curl -fsSL -o /usr/local/bin/virtctl https://github.com/kubevirt/kubevirt/releases/download/$VIRTCTL_VERSION/virtctl-$VIRTCTL_VERSION-linux-amd64

# renovate: datasource=github-releases depName=helm/helm
ARG HELM_VERSION=v4.1.0
RUN curl -fsSLO "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz{,.sha256}" && \
    sha256sum -c <(echo "$(cat helm-${HELM_VERSION}-linux-amd64.tar.gz.sha256)  helm-${HELM_VERSION}-linux-amd64.tar.gz") && \
    tar -xzf helm-${HELM_VERSION}-linux-amd64.tar.gz --strip-components=1 && \
    mv helm /usr/local/bin/helm && \
    rm -rf /tmp/*

# renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
ARG KUBECTL_VERSION=v1.35.0
RUN curl -fsSLO "https://dl.k8s.io/$KUBECTL_VERSION/bin/linux/amd64/kubectl{,.sig,.cert}" && \
    cosign verify-blob kubectl \
      --certificate kubectl.cert \
      --signature kubectl.sig \
      --certificate-identity krel-staging@k8s-releng-prod.iam.gserviceaccount.com \
      --certificate-oidc-issuer https://accounts.google.com && \
    mv kubectl /usr/local/bin/kubectl && \
    rm -rf /tmp/*

RUN curl -fsSL -o /usr/local/bin/kubectl-node_shell "https://github.com/kvaps/kubectl-node-shell/raw/master/kubectl-node_shell"

RUN curl -fsSL -O "https://download.libguestfs.org/binaries/appliance/appliance-1.56.0.tar.xz{,.sig}" \
           -O "https://download.libguestfs.org/libguestfs.keyring" && \
    gpg --no-default-keyring --keyring ./libguestfs.keyring --verify appliance-1.56.0.tar.xz.sig appliance-1.56.0.tar.xz && \
    tar -xJf appliance-1.56.0.tar.xz && \
    mkdir -p /usr/local/lib/guestfs && \
    mv appliance /usr/local/lib/guestfs/ && \
    chmod +x /usr/local/bin/* && \
    rm -rf /tmp/*

RUN groupadd --gid $USER_GID $USERNAME || true && \
    useradd -s /bin/bash -u $USER_UID -g $USERNAME -m $USERNAME && \
    groupadd -g 1003 docker || true && \
    usermod -aG docker $USERNAME && \
    echo 'alias k=kubectl' >> /home/$USERNAME/.bashrc && \
    echo 'complete -o default -F __start_kubectl k' >> /home/$USERNAME/.bashrc && \
    echo 'eval "$(direnv hook bash)"' >> /home/$USERNAME/.bashrc && \
    kubectl completion bash | tee /etc/bash_completion.d/kubectl > /dev/null && \
    helm plugin install --verify=false https://github.com/databus23/helm-diff

USER $USERNAME

# renovate: datasource=pypi depName=pgadmin4
ARG PGADMIN4_VERSION=9.11
# renovate: datasource=pypi depName=home-ops-cli
ARG HOME_OPS_CLI_VERSION=0.4.51
RUN uv tool install pgadmin4==${PGADMIN4_VERSION} && \
    uv tool install home-ops-cli==${HOME_OPS_CLI_VERSION} && \
    uv python update-shell && \
    uv cache clean

WORKDIR /project
ENTRYPOINT ["/bin/bash"]
