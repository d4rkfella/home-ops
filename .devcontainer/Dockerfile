FROM ubuntu:resolute-20260421@sha256:f3d28607ddd78734bb7f71f117f3c6706c666b8b76cbff7c9ff6e5718d46ff64

WORKDIR /tmp
SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND="noninteractive" \
    LANG="C.UTF-8" \
    EDITOR=/usr/bin/nano

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg xz-utils unzip \
        jq nano bash bash-completion git direnv tigervnc-viewer && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/siderolabs/talosctl:v1.13.4@sha256:22101c9dc8b4dcab5534a9ce0192a6d40245183324f19785cd4e36f9a9ed5e7a /talosctl /usr/local/bin/
RUN talosctl version --client

COPY --from=ghcr.io/fluxcd/flux-cli:v2.8.8@sha256:3113a880461938a47ab2ec877aecbf19c570e4df9848d20228d1b4d2c7f8a764 /usr/local/bin/flux /usr/local/bin/
RUN flux --version

COPY --from=ghcr.io/sigstore/cosign/cosign:v3.1.1@sha256:6bbe0d281d955c79f85b325f0f7e651c1bcab5a4fa4ad4903d74955178a3b2eb /ko-app/cosign /usr/local/bin/
RUN cosign version

COPY --from=ghcr.io/helmfile/helmfile:v1.5.5@sha256:64c4d0ead4e19e1368fb04980ed3859d466dc80c5738d91cafb1fc45473242f2 /usr/local/bin/helmfile /usr/local/bin/
RUN helmfile --version

COPY --from=ghcr.io/astral-sh/uv:0.11.22-trixie@sha256:10d8af482ed6b2602500a8a5adc0493c2ce1be984ac9c1f72387503508748716 /usr/local/bin/uv* /usr/local/bin/
RUN uv self version && uvx --version

COPY --from=ghcr.io/getsops/sops:v3.13.1@sha256:320f253aced1393537b1e90c77eb48295204d805d4c68933264cd1285192465d /usr/local/bin/sops /usr/local/bin/
RUN sops --version

COPY --from=mikefarah/yq:4.53.3@sha256:11a1f0b604b13dbbdc662260d8db6f644b22d8553122a25c1b5b2e8713ca6977 /usr/bin/yq /usr/local/bin/
RUN yq --version

# renovate: datasource=github-releases depName=go-task/task
ARG TASK_VERSION=v3.51.1
RUN curl -fsSLO "https://github.com/go-task/task/releases/download/$TASK_VERSION/task_{linux_amd64.tar.gz,checksums.txt}" && \
    sha256sum -c --strict --ignore-missing task_checksums.txt && \
    tar -xvzf task_linux_amd64.tar.gz && \
    mv task /usr/local/bin/ && \
    rm -rf /tmp/*

# renovate: datasource=github-releases depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.8.4
RUN curl -fsSL -o /usr/local/bin/virtctl https://github.com/kubevirt/kubevirt/releases/download/$VIRTCTL_VERSION/virtctl-$VIRTCTL_VERSION-linux-amd64 && chmod +x /usr/local/bin/virtctl

# renovate: datasource=github-releases depName=helm/helm
ARG HELM_VERSION=v4.2.2
RUN curl -fsSLO "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz{,.sha256}" && \
    sha256sum -c <(echo "$(cat helm-${HELM_VERSION}-linux-amd64.tar.gz.sha256)  helm-${HELM_VERSION}-linux-amd64.tar.gz") && \
    tar -xzf helm-${HELM_VERSION}-linux-amd64.tar.gz --strip-components=1 && \
    mv helm /usr/local/bin/ && \
    rm -rf /tmp/*

# renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
ARG KUBECTL_VERSION=v1.36.2
RUN curl -fsSLO "https://dl.k8s.io/$KUBECTL_VERSION/bin/linux/amd64/kubectl{,.sig,.cert}" && \
    cosign verify-blob kubectl \
      --certificate kubectl.cert \
      --signature kubectl.sig \
      --certificate-identity krel-staging@k8s-releng-prod.iam.gserviceaccount.com \
      --certificate-oidc-issuer https://accounts.google.com && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    rm -rf /tmp/*

# renovate: datasource=github-releases depName=evilmartians/lefthook
ARG LEFTHOOK_VERSION=v2.1.9
RUN curl -fsSLO "https://github.com/evilmartians/lefthook/releases/download/${LEFTHOOK_VERSION}/lefthook_${LEFTHOOK_VERSION#v}_amd64.deb" && \
    dpkg -i lefthook_${LEFTHOOK_VERSION#v}_amd64.deb && \
    rm lefthook_${LEFTHOOK_VERSION#v}_amd64.deb

# renovate: datasource=github-releases depName=google/yamlfmt
ARG YAMLFMT_VERSION=v0.21.0
RUN curl -fsSLO "https://github.com/google/yamlfmt/releases/download/${YAMLFMT_VERSION}/yamlfmt_${YAMLFMT_VERSION#v}_Linux_x86_64.tar.gz" && \
    tar -xzf yamlfmt_*.tar.gz yamlfmt && \
    mv yamlfmt /usr/local/bin/ && \
    rm -rf /tmp/*

RUN echo 'source /usr/share/bash-completion/bash_completion' >> ~/.bashrc && \
    echo 'source <(kubectl completion bash)' >> ~/.bashrc && \
    echo 'alias k=kubectl' >> ~/.bashrc && \
    echo 'complete -o default -F __start_kubectl k' >> ~/.bashrc && \
    echo 'eval "$(direnv hook bash)"' >> ~/.bashrc && \
    helm plugin install --verify=false https://github.com/databus23/helm-diff

# renovate: datasource=pypi depName=vaultctl
ARG VAULTCTL_VERSION=0.2.3
RUN uv tool install vaultctl==${VAULTCTL_VERSION} && \
    uv python update-shell && \
    uv cache clean
