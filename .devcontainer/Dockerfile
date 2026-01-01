FROM debian:trixie AS build

# renovate: datasource=github-releases depName=go-task/task
ARG TASK_VERSION=v3.46.4
# renovate: datasource=github-releases depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.7.0
# renovate: datasource=github-releases depName=helm/helm
ARG HELM_VERSION=v4.0.4
# renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
ARG KUBECTL_VERSION=v1.35.0
# renovate: datasource=github-releases depName=getsops/sops
ARG SOPS_VERSION=v3.11.0
# renovate: datasource=github-releases depName=sigstore/cosign
ARG COSIGN_VERSION=v3.0.3
# renovate: datasource=github-releases depName=mikefarah/yq
ARG YQ_VERSION=v4.50.1
# renovate: datasource=github-releases depName=astral-sh/uv
ARG UV_VERSION=0.9.21
# renovate: datasource=pypi depName=home-ops-cli
ARG HOME-OPS-CLI_VERSION=0.4.2
# renovate: datasource=pypi depName=pgadmin4
ARG PGADMIN4_VERSION=9.11

USER root
WORKDIR /tmp

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND="noninteractive"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        cosign \
        curl \
        ca-certificates \
        gnupg \
        xz-utils \
        unzip && \
    #Download and verify cosign binary
    curl -fsSL -o cosign https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-amd64 && \
    curl -fsSL -o sigstore.json https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-amd64.sigstore.json  && \
    /usr/bin/cosign verify-blob cosign  --certificate-identity keyless@projectsigstore.iam.gserviceaccount.com --certificate-oidc-issuer https://accounts.google.com --bundle sigstore.json && \
    mv cosign /usr/local/bin/cosign && chmod +x /usr/local/bin/cosign && \
    #Download and verify kubectl binary
    curl -fsSLO "https://dl.k8s.io/$KUBECTL_VERSION/bin/linux/amd64/kubectl{,.sig,.cert}" && \
    /usr/local/bin/cosign verify-blob kubectl \
      --certificate kubectl.cert \
      --signature kubectl.sig \
      --certificate-identity krel-staging@k8s-releng-prod.iam.gserviceaccount.com \
      --certificate-oidc-issuer https://accounts.google.com && \
    mv kubectl /usr/local/bin/kubectl && \
    #Download and verify sops binary
    curl -fsSLO "https://github.com/getsops/sops/releases/download/${SOPS_VERSION}/sops-${SOPS_VERSION}{.linux.amd64,.checksums.txt,.checksums.pem,.checksums.sig}" && \
    /usr/local/bin/cosign verify-blob sops-${SOPS_VERSION}.checksums.txt \
      --certificate sops-${SOPS_VERSION}.checksums.pem \
      --signature sops-${SOPS_VERSION}.checksums.sig \
      --certificate-identity-regexp=https://github.com/getsops \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com && \
    sha256sum -c --strict sops-${SOPS_VERSION}.checksums.txt --ignore-missing && \
    mv sops-${SOPS_VERSION}.linux.amd64 /usr/local/bin/sops && \
    #Download virtctl binary
    curl -fsSL -o /usr/local/bin/virtctl https://github.com/kubevirt/kubevirt/releases/download/$VIRTCTL_VERSION/virtctl-$VIRTCTL_VERSION-linux-amd64 && \
    #Download and verify task binary
    curl -fsSLO "https://github.com/go-task/task/releases/download/$TASK_VERSION/task_{linux_amd64.tar.gz,checksums.txt}" && \
    sha256sum -c --strict --ignore-missing task_checksums.txt && \
    tar -xvzf task_linux_amd64.tar.gz && mv task /usr/local/bin/task && \
    #Download yq binary
    curl -fsSL -o yq https://github.com/mikefarah/yq/releases/download/$YQ_VERSION/yq_linux_amd64 && \
    mv yq /usr/local/bin/yq && \
    #Download and verify helm binary
    curl -fsSLO "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz{,.sha256}" && \
    sha256sum -c <(echo "$(cat helm-${HELM_VERSION}-linux-amd64.tar.gz.sha256)  helm-${HELM_VERSION}-linux-amd64.tar.gz") && \
    tar -xzf helm-${HELM_VERSION}-linux-amd64.tar.gz --strip-components=1 && \
    mv helm /usr/local/bin/helm && \
    #Download kubectl node-shell plugin
    curl -fsSL -o /usr/local/bin/kubectl-node_shell https://github.com/kvaps/kubectl-node-shell/raw/master/kubectl-node_shell && \
    #Download and verify libguestfs appliance
    curl -fsSL -O https://download.libguestfs.org/binaries/appliance/appliance-1.56.0.tar.xz \
               -O https://download.libguestfs.org/binaries/appliance/appliance-1.56.0.tar.xz.sig \
               -O https://download.libguestfs.org/libguestfs.keyring && \
    gpg --no-default-keyring --keyring ./libguestfs.keyring --verify appliance-1.56.0.tar.xz.sig appliance-1.56.0.tar.xz && \
    tar -xJf appliance-1.56.0.tar.xz && \
    mkdir -p /usr/local/lib/guestfs && \
    mv appliance /usr/local/lib/guestfs/ && \
    #Download and verify uv and uvx binaries
    curl -fsSLO https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz{,.sha256} && \
    sha256sum -c --strict --ignore-missing uv-x86_64-unknown-linux-gnu.tar.gz.sha256 && \
    tar -xzf uv-x86_64-unknown-linux-gnu.tar.gz && \
    mv uv uvx /usr/local/bin/ && \
    #Set permissions
    chmod +x /usr/local/bin/*

COPY --from=ghcr.io/siderolabs/talosctl:v1.12.0 /talosctl /usr/local/bin/talosctl
RUN talosctl version --client

COPY --from=ghcr.io/helmfile/helmfile:v1.2.3 /usr/local/bin/helmfile /usr/local/bin/helmfile
RUN helmfile --version

FROM debian:trixie-slim

ENV LANG="C.UTF-8"
ENV EDITOR=/usr/bin/nano
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ARG USERNAME=vscode
ARG USER_UID=2100
ARG USER_GID=$USER_UID

ENV DEBIAN_FRONTEND="noninteractive"

COPY --from=build /usr/local/bin/ /usr/local/bin/
COPY --from=build /usr/local/lib/guestfs /usr/local/lib/guestfs

SHELL ["/bin/bash", "-c"]

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        jq \
        nano \
        bash \
        bash-completion \
        ca-certificates \
        git \
        gnupg \
        libguestfs-tools \
        direnv \
        docker-cli \
        docker-buildx \
        tigervnc-viewer \
        libusb-1.0-0 \
        usbredirect \
        fontconfig \
        fonts-dejavu \
        && groupadd --gid $USER_GID $USERNAME || true && \
    useradd -s /bin/bash -u $USER_UID -g $USERNAME -m $USERNAME && \
    groupadd -g 1003 docker || true && \
    usermod -aG docker $USERNAME && \
    echo 'alias k=kubectl' >> /home/$USERNAME/.bashrc && \
    echo 'complete -o default -F __start_kubectl k' >> /home/$USERNAME/.bashrc && \
    echo 'eval "$(direnv hook bash)"' >> /home/$USERNAME/.bashrc && \
    kubectl completion bash | tee /etc/bash_completion.d/kubectl > /dev/null && \
    helm plugin install --verify=false https://github.com/databus23/helm-diff && \
    uv tool install pgadmin4==${PGADMIN4_VERSION} && \
    uv tool install home-ops-cli==${HOME-OPS-CLI_VERSION} && \
    uv cache clean && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

USER $USERNAME

WORKDIR /project

ENTRYPOINT ["/bin/bash"]
