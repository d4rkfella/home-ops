FROM debian:trixie-slim@sha256:4ffb3a1511099754cddc70eb1b12e50ffdb67619aa0ab6c13fcd800a78ef7c7a

ARG USERNAME=vscode

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

COPY --from=ghcr.io/siderolabs/talosctl:v1.13.0-beta.0@sha256:a11ca1a30b2706c8da706f7e6ac3ee37504cd834b5345e82ee0faca5efaaba6f /talosctl /usr/local/bin/talosctl
RUN talosctl version --client

COPY --from=ghcr.io/fluxcd/flux-cli:v2.8.5@sha256:f1947272d998247ce959adf8ffe13626f153e8b373ccd0322a18b4f7aad132f1 /usr/local/bin/flux /usr/local/bin/
RUN flux --version

COPY --from=ghcr.io/sigstore/cosign/cosign:v3.0.6@sha256:de9c65609e6bde17e6b48de485ee788407c9502fa08b8f4459f595b21f56cd00 /ko-app/cosign /usr/local/bin/
RUN cosign version

COPY --from=ghcr.io/helmfile/helmfile:v1.4.4@sha256:d6dd15bfc569b9b02a2cfb995ef48927a21d367a51f8b95d58bcce820268ba31 /usr/local/bin/helmfile /usr/local/bin/
RUN helmfile --version

COPY --from=ghcr.io/astral-sh/uv:0.11.5-trixie@sha256:3b3a0eeef7839fd5e945db36fdc12a576b54b9d56a55f094e544c9f77d5e9cc9 /usr/local/bin/uv* /usr/local/bin/
RUN uv self version && uvx --version

COPY --from=ghcr.io/getsops/sops:v3.12.2@sha256:96589a5e4c746809d50cda1d6c3f8f292818eb014a97322da03bad024ddefaba /usr/local/bin/sops /usr/local/bin/
RUN sops --version

COPY --from=mikefarah/yq:4.52.5@sha256:603ebff15eb308a05f1c5b8b7613179cad859aed3ec9fdd04f2ef5d32345950e /usr/bin/yq /usr/local/bin/
RUN yq --version

# renovate: datasource=github-releases depName=go-task/task
ARG TASK_VERSION=v3.49.1
RUN curl -fsSLO "https://github.com/go-task/task/releases/download/$TASK_VERSION/task_{linux_amd64.tar.gz,checksums.txt}" && \
    sha256sum -c --strict --ignore-missing task_checksums.txt && \
    tar -xvzf task_linux_amd64.tar.gz && \
    mv task /usr/local/bin/task && \
    rm -rf /tmp/*

# renovate: datasource=github-releases depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.8.1
RUN curl -fsSL -o /usr/local/bin/virtctl https://github.com/kubevirt/kubevirt/releases/download/$VIRTCTL_VERSION/virtctl-$VIRTCTL_VERSION-linux-amd64

# renovate: datasource=github-releases depName=helm/helm
ARG HELM_VERSION=v4.1.3
RUN curl -fsSLO "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz{,.sha256}" && \
    sha256sum -c <(echo "$(cat helm-${HELM_VERSION}-linux-amd64.tar.gz.sha256)  helm-${HELM_VERSION}-linux-amd64.tar.gz") && \
    tar -xzf helm-${HELM_VERSION}-linux-amd64.tar.gz --strip-components=1 && \
    mv helm /usr/local/bin/helm && \
    rm -rf /tmp/*

# renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
ARG KUBECTL_VERSION=v1.35.3
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

# renovate: datasource=github-releases depName=evilmartians/lefthook
ARG LEFTHOOK_VERSION=v2.1.5
RUN curl -fsSLO "https://github.com/evilmartians/lefthook/releases/download/${LEFTHOOK_VERSION}/lefthook_${LEFTHOOK_VERSION#v}_amd64.deb" && \
    dpkg -i lefthook_${LEFTHOOK_VERSION#v}_amd64.deb && \
    rm lefthook_${LEFTHOOK_VERSION#v}_amd64.deb

# renovate: datasource=github-releases depName=google/yamlfmt
ARG YAMLFMT_VERSION=v0.21.0
RUN curl -fsSLO "https://github.com/google/yamlfmt/releases/download/${YAMLFMT_VERSION}/yamlfmt_${YAMLFMT_VERSION#v}_Linux_x86_64.tar.gz" && \
    tar -xzf yamlfmt_*.tar.gz yamlfmt && \
    mv yamlfmt /usr/local/bin/yamlfmt && \
    rm -rf /tmp/*


RUN groupadd $USERNAME && \
    useradd -s /bin/bash -g $USERNAME -m $USERNAME && \
    echo 'alias k=kubectl' >> /home/$USERNAME/.bashrc && \
    echo 'complete -o default -F __start_kubectl k' >> /home/$USERNAME/.bashrc && \
    echo 'eval "$(direnv hook bash)"' >> /home/$USERNAME/.bashrc && \
    kubectl completion bash | tee /etc/bash_completion.d/kubectl > /dev/null && \
    helm plugin install --verify=false https://github.com/databus23/helm-diff

USER $USERNAME

# renovate: datasource=pypi depName=home-ops-cli
ARG HOME_OPS_CLI_VERSION=0.4.53
RUN uv tool install home-ops-cli==${HOME_OPS_CLI_VERSION} && \
    uv python update-shell && \
    uv cache clean

WORKDIR /project
ENTRYPOINT ["/bin/bash"]
