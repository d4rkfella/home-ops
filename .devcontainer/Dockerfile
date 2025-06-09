FROM alpine:3.22.0 AS build

# renovate: datasource=github-releases depName=go-task/task
ARG TASK_VERSION=v3.44.0
# renovate: datasource=github-releases depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.5.1
# renovate: datasource=github-releases depName=a8m/envsubst
ARG ENVSUBST_VERSION=v1.4.3
# renovate: datasource=github-releases depName=hashicorp/vault
ARG VAULT_VERSION=v1.19.5
# renovate: datasource=github-releases depName=helm/helm
ARG HELM_VERSION=v3.18.2
# renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
ARG KUBECTL_VERSION=v1.33.1
# renovate: datasource=github-releases depName=getsops/sops
ARG SOPS_VERSION=v3.10.2
# renovate: datasource=github-releases depName=fluxcd/flux2
ARG FLUX_VERSION=v2.6.1
ARG KUBECTL_EXPLORE_VERSION=v0.12.0
ARG FZF_VERSION=v0.62.0

ARG TALOS_VERSION=v1.9.5

WORKDIR /tmp

RUN apk add --no-cache \
        curl \
        ca-certificates \
        coreutils \
        expect \
        cosign \
        gnupg \
        unzip && \
    #Download and verify kubectl binary
    curl -fsSLO "https://dl.k8s.io/$KUBECTL_VERSION/bin/linux/amd64/kubectl{,.sig,.cert}" && \
    cosign verify-blob kubectl \
      --certificate kubectl.cert \
      --signature kubectl.sig \
      --certificate-identity krel-staging@k8s-releng-prod.iam.gserviceaccount.com \
      --certificate-oidc-issuer https://accounts.google.com && \
    mv kubectl /usr/local/bin/kubectl && \
    #Download and verify flux-cli binary
    curl -fsSLO "https://github.com/fluxcd/flux2/releases/download/${FLUX_VERSION}/flux_${FLUX_VERSION#v}_{linux_amd64.tar.gz,checksums.txt,checksums.txt.pem,checksums.txt.sig}" && \
    cosign verify-blob flux_${FLUX_VERSION#v}_checksums.txt \
      --certificate flux_${FLUX_VERSION#v}_checksums.txt.pem \
      --signature flux_${FLUX_VERSION#v}_checksums.txt.sig \
      --certificate-identity-regexp=https://github.com/fluxcd \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com && \
    sha256sum -c --strict flux_${FLUX_VERSION#v}_checksums.txt --ignore-missing && \
    tar -xzf flux_${FLUX_VERSION#v}_linux_amd64.tar.gz && \
    mv flux /usr/local/bin/flux && \
    #Download and verify sops binary
    curl -fsSLO "https://github.com/getsops/sops/releases/download/${SOPS_VERSION}/sops-${SOPS_VERSION}{.linux.amd64,.checksums.txt,.checksums.pem,.checksums.sig}" && \
    cosign verify-blob sops-${SOPS_VERSION}.checksums.txt \
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
    #Download envsubst binary
    curl -fsSL -o /usr/local/bin/envsubst https://github.com/a8m/envsubst/releases/download/$ENVSUBST_VERSION/envsubst-`uname -s`-`uname -m` && \
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
    wget -O- "https://github.com/keisku/kubectl-explore/releases/download/${KUBECTL_EXPLORE_VERSION}/kubectl-explore_${KUBECTL_EXPLORE_VERSION}_linux_amd64.tar.gz" | tar -xzf - -C /usr/local/bin && \
    wget -O- "https://github.com/junegunn/fzf/releases/download/${FZF_VERSION}/fzf-${FZF_VERSION#v}-linux_amd64.tar.gz" | tar -xzf - -C /usr/local/bin && \
    wget -O /usr/local/bin/fzf-tmux https://raw.githubusercontent.com/junegunn/fzf/master/bin/fzf-tmux && chmod +x /usr/local/bin/fzf-tmux && \
    #Set permissions
    chmod +x /usr/local/bin/*

COPY --from=ghcr.io/siderolabs/talosctl:v1.10.2 /talosctl /usr/local/bin/talosctl
RUN talosctl version --client

COPY --from=ghcr.io/d4rkfella/vault-backup:1.0.0@sha256:c87eca415eb3a05bfd699c6989bfc4e882e5df0d2092a23ffac709ff01682e2f /usr/bin/vault-backup /usr/local/bin/vault-backup
RUN vault-backup --version

COPY --from=ghcr.io/helmfile/helmfile:v1.1.1 /usr/local/bin/helmfile /usr/local/bin/helmfile
RUN helmfile --version


FROM alpine:3.22.0

ENV LANG="C.UTF-8"
ENV EDITOR=/usr/bin/nano

ARG USERNAME=vscode
ARG USER_UID=2100
ARG USER_GID=$USER_UID

COPY --from=build /usr/local/bin/ /usr/local/bin/

RUN apk add --no-cache \
        curl \
        jq \
        nano \
        bash \
        bash-completion \
        ca-certificates \
        git \
        github-cli \
        libstdc++ \
        direnv \
        yq \
        gnupg \
        docker-cli \
        buildkit \
        python3 \
        py3-pip \
        binutils \
        xclip \
        tmux \
        ncurses \
        vim \
        fzf-vim \
        cosign && \
    addgroup -g $USER_GID $USERNAME && \
    adduser -u $USER_UID -G $USERNAME -s /bin/sh -D $USERNAME && \
    addgroup -g 1001 docker && adduser $USERNAME docker && \
    echo 'alias k=kubectl' >> /home/$USERNAME/.bashrc && \
    echo 'complete -o default -F __start_kubectl k' >> /home/$USERNAME/.bashrc && \
    echo 'eval "$(direnv hook bash)"' >> /home/$USERNAME/.bashrc && \
    kubectl completion bash | tee /etc/bash_completion.d/kubectl > /dev/null && \
    helm plugin install https://github.com/databus23/helm-diff
    WORKDIR /project

USER $USERNAME

ENTRYPOINT ["/bin/bash"]
