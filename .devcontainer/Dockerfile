FROM ubuntu:resolute-20261105.1@sha256:66b8084a0d45bd4877992bd38e04b51bfa99bd57293364cb6391fb674771846e

WORKDIR /tmp
SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND="noninteractive" \
    LANG="C.UTF-8" \
    EDITOR=/usr/bin/nano

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg xz-utils unzip \
        jq nano bash bash-completion git direnv tigervnc-viewer \
        xdg-utils gum && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/siderolabs/talosctl:v1.14.6@sha256:82c9a9985fc7292a222e680414c65955ac0566db588b84d88f620b05d16b1d5b /talosctl /usr/local/bin/
RUN talosctl version --client

COPY --from=ghcr.io/fluxcd/flux-cli:v2.10.0@sha256:1a5178b1770052d6e88ab1c7c8434c5ac9bca8a8ab984dcaf6b9df31814ce9f2 /usr/local/bin/flux /usr/local/bin/
RUN flux --version

COPY --from=ghcr.io/casey/just:1.59.0@sha256:014cbe6e6de678864004e2fd8b0405f77ce43b20b225e816feb330f2fb575c01 /just /usr/local/bin/
RUN just --version

COPY --from=ghcr.io/postfinance/topf:v0.6.2@sha256:745b33c5f900df7cd9885557a037fcc5471b167b1fc20046385639112e3e6deb /usr/local/bin/topf /usr/local/bin/
RUN topf --version

COPY --from=ghcr.io/openbao/openbao:2.7.2@sha256:5046911075e137e154ce49ab051502f4ec7cf367d484ae4a4dce665d9b90561f /usr/bin/bao /usr/local/bin/
RUN bao --version

COPY --from=ghcr.io/sigstore/cosign/cosign:v3.1.4@sha256:0f06154836d2de34f887a5c273506d52ca43edaa1d9e53e6510fa78a48f69c2d /ko-app/cosign /usr/local/bin/
RUN cosign version

COPY --from=ghcr.io/helmfile/helmfile:v1.8.4@sha256:ccaa1854dffc789617e13dde016144e7e164016933e7d20ec6786c6f8a342681 /usr/local/bin/helmfile /usr/local/bin/
RUN helmfile --version

COPY --from=ghcr.io/astral-sh/uv:0.13.8-trixie@sha256:49f68aaf4290a1eb438d913d51033007eb5fac1e3add6ca8d1d161426ddac798 /usr/local/bin/uv* /usr/local/bin/
RUN uv self version && uvx --version

COPY --from=ghcr.io/getsops/sops:v3.13.3@sha256:857f5a151ac0b2bfc55c1e4e5581d66fb8e268e4d106b38e74191f3bac9d58ea /usr/local/bin/sops /usr/local/bin/
RUN sops --version

COPY --from=mikefarah/yq:4.54.3@sha256:7834187596ad56fd5a81436114e0b0b9dd54c91bb43946d1f7145b2be5f9c3d2 /usr/bin/yq /usr/local/bin/
RUN yq --version

# renovate: datasource=github-releases depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.9.1
RUN curl -fsSL -o /usr/local/bin/virtctl https://github.com/kubevirt/kubevirt/releases/download/$VIRTCTL_VERSION/virtctl-$VIRTCTL_VERSION-linux-amd64 && chmod +x /usr/local/bin/virtctl

# renovate: datasource=github-releases depName=helm/helm
ARG HELM_VERSION=v4.3.2
RUN curl -fsSLO "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz{,.sha256}" && \
    sha256sum -c <(echo "$(cat helm-${HELM_VERSION}-linux-amd64.tar.gz.sha256)  helm-${HELM_VERSION}-linux-amd64.tar.gz") && \
    tar -xzf helm-${HELM_VERSION}-linux-amd64.tar.gz --strip-components=1 && \
    mv helm /usr/local/bin/ && \
    rm -rf /tmp/*

# renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
ARG KUBECTL_VERSION=v1.37.2
RUN curl -fsSLO "https://dl.k8s.io/$KUBECTL_VERSION/bin/linux/amd64/kubectl{,.sig,.cert}" && \
    cosign verify-blob kubectl \
      --certificate kubectl.cert \
      --signature kubectl.sig \
      --certificate-identity krel-staging@k8s-releng-prod.iam.gserviceaccount.com \
      --certificate-oidc-issuer https://accounts.google.com && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    rm -rf /tmp/*

# renovate: datasource=github-releases depName=evilmartians/lefthook
ARG LEFTHOOK_VERSION=v2.2.2
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


RUN uv python update-shell && \
    uv cache clean
