# Use Debian Trixie for the build stage. This provides a more robust
# and compatible environment for libguestfs and Python build dependencies.
FROM debian:trixie AS build

# renovate: datasource=github-releases depName=go-task/task
ARG TASK_VERSION=v3.45.5
# renovate: datasource=github-releases depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.6.3
# renovate: datasource=github-releases depName=hashicorp/vault
ARG VAULT_VERSION=v1.21.1
# renovate: datasource=github-releases depName=helm/helm
ARG HELM_VERSION=v4.0.1
# renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
ARG KUBECTL_VERSION=v1.34.2
# renovate: datasource=github-releases depName=getsops/sops
ARG SOPS_VERSION=v3.11.0
# renovate: datasource=github-releases depName=fluxcd/flux2
ARG FLUX_VERSION=v2.7.5
# renovate: datasource=github-releases depName=sigstore/cosign
ARG COSIGN_VERSION=v3.0.2

USER root
WORKDIR /tmp

COPY requirements.txt /tmp/requirements.txt

SHELL ["/bin/bash", "-c"]

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3 \
        python3-pip \
        python3-dev \
        libguestfs-dev \
        git \
        cosign \
        curl \
        ca-certificates \
        coreutils \
        gnupg \
        unzip \
        && apt-get clean && rm -rf /var/lib/apt/lists/* && \
    python3 -m pip wheel --wheel-dir /tmp/wheels -r /tmp/requirements.txt && \
    # Download latest cosign (v4+) release
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
    #Download and verify flux-cli binary
    curl -fsSLO "https://github.com/fluxcd/flux2/releases/download/${FLUX_VERSION}/flux_${FLUX_VERSION#v}_{linux_amd64.tar.gz,checksums.txt,checksums.txt.pem,checksums.txt.sig}" && \
    /usr/local/bin/cosign verify-blob flux_${FLUX_VERSION#v}_checksums.txt \
      --certificate flux_${FLUX_VERSION#v}_checksums.txt.pem \
      --signature flux_${FLUX_VERSION#v}_checksums.txt.sig \
      --certificate-identity-regexp=https://github.com/fluxcd \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com && \
    sha256sum -c --strict flux_${FLUX_VERSION#v}_checksums.txt --ignore-missing && \
    tar -xzf flux_${FLUX_VERSION#v}_linux_amd64.tar.gz && \
    mv flux /usr/local/bin/flux && \
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
    #Download and verify vault binary
    curl -fsSL https://www.hashicorp.com/.well-known/pgp-key.txt | gpg --import && \
    curl -fsSLO "https://releases.hashicorp.com/vault/${VAULT_VERSION#v}/vault_${VAULT_VERSION#v}_{linux_amd64.zip,SHA256SUMS,SHA256SUMS.72D7468F.sig}" && \
    gpg --verify vault_${VAULT_VERSION#v}_SHA256SUMS.72D7468F.sig vault_${VAULT_VERSION#v}_SHA256SUMS && \
    sha256sum -c --strict vault_${VAULT_VERSION#v}_SHA256SUMS --ignore-missing && \
    unzip vault_${VAULT_VERSION#v}_linux_amd64.zip && \
    mv vault /usr/local/bin/vault && \
    #Download and verify helm binary
    curl -fsSLO "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz{,.sha256}" && \
    sha256sum -c <(echo "$(cat helm-${HELM_VERSION}-linux-amd64.tar.gz.sha256)  helm-${HELM_VERSION}-linux-amd64.tar.gz") && \
    tar -xzf helm-${HELM_VERSION}-linux-amd64.tar.gz --strip-components=1 && \
    mv helm /usr/local/bin/helm && \
    #Download kubectl node-shell plugin
    curl -fsSL -o /usr/local/bin/kubectl-node_shell https://github.com/kvaps/kubectl-node-shell/raw/master/kubectl-node_shell && \
    #Set permissions
    chmod +x /usr/local/bin/*

COPY --from=ghcr.io/siderolabs/talosctl:v1.11.5 /talosctl /usr/local/bin/talosctl
RUN talosctl version --client

COPY --from=ghcr.io/d4rkfella/vault-backup:1.11.3@sha256:06bcfadf2e857bd676b74758c8c2acf00dfda42b7cf0472bbe10090b9376d944 /usr/bin/vault-backup /usr/local/bin/vault-backup
RUN vault-backup --version

COPY --from=ghcr.io/helmfile/helmfile:v1.2.1 /usr/local/bin/helmfile /usr/local/bin/helmfile
RUN helmfile --version

FROM debian:trixie-slim

ENV LANG="C.UTF-8"
ENV EDITOR=/usr/bin/nano
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ARG USERNAME=vscode
ARG USER_UID=2100
ARG USER_GID=$USER_UID

COPY --from=build /usr/local/bin/ /usr/local/bin/
COPY --from=build /tmp/wheels /tmp/wheels

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
        python3 \
        python3-pip \
        python3.13-venv \
        direnv \
        yq \
        docker.io \
        tigervnc-viewer \
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
    python3 -m venv /home/$USERNAME/.venv && \
    . /home/$USERNAME/.venv/bin/activate && \
    pip install --upgrade pip --no-index --find-links=/tmp/wheels --no-cache-dir /tmp/wheels/*.whl && \
    rm -rf /tmp/wheels && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /project
USER $USERNAME
ENTRYPOINT ["/bin/bash"]
