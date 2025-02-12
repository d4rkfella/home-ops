FROM alpine:3.21.2 AS builder

# renovate: depName=go-task/task
ARG TASK_VERSION=v3.41.0
# renovate: depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.5.0-beta.0
# renovate: depName=a8m/envsubst
ARG ENVSUBST_VERSION=v1.4.2
# renovate: depName=hashicorp/vault
ARG VAULT_VERSION=1.18.4
# renovate: depName=helm/helm
ARG HELM_VERSION=3.17.0
ARG KUBECTL_VERSION=v1.32.1
WORKDIR /tmp

RUN apk update && \
    apk upgrade && \
    apk add --no-cache \
    curl \
    gnupg \
    ca-certificates \
    cosign \
    unzip && \
    curl -fsSLO "https://dl.k8s.io/$KUBECTL_VERSION/bin/linux/amd64/kubectl{,.sig,.cert,.sha256}" && \
    cosign verify-blob kubectl \
      --certificate kubectl.cert \
      --signature kubectl.sig \
      --certificate-identity krel-staging@k8s-releng-prod.iam.gserviceaccount.com \
      --certificate-oidc-issuer https://accounts.google.com && \
    mv kubectl /usr/local/bin/kubectl && \
    curl -fsSLO https://github.com/kubevirt/kubevirt/releases/download/$VIRTCTL_VERSION/virtctl-$VIRTCTL_VERSION-linux-amd64 && \
    mv ./virtctl-$VIRTCTL_VERSION-linux-amd64 /usr/local/bin/virtctl && \
    curl -fsSLO "https://github.com/go-task/task/releases/download/$TASK_VERSION/task_{linux_amd64.tar.gz,checksums.txt}" && \
    sha256sum -c --strict --ignore-missing task_checksums.txt && \
    tar -xvzf task_linux_amd64.tar.gz && mv ./task /usr/local/bin/task && \
    curl -fsSLO https://github.com/a8m/envsubst/releases/download/$ENVSUBST_VERSION/envsubst-`uname -s`-`uname -m` && \
    mv ./envsubst-`uname -s`-`uname -m` /usr/local/bin/envsubst && \
    curl -fsSL https://www.hashicorp.com/.well-known/pgp-key.txt | gpg --import && \
    curl -fsSLO "https://releases.hashicorp.com/vault/$VAULT_VERSION/vault_${VAULT_VERSION}_{linux_amd64.zip,SHA256SUMS,SHA256SUMS.72D7468F.sig}" && \
    gpg --verify ./vault_${VAULT_VERSION}_SHA256SUMS.72D7468F.sig ./vault_${VAULT_VERSION}_SHA256SUMS && \
    sha256sum -c ./vault_${VAULT_VERSION}_SHA256SUMS --ignore-missing && \
    unzip ./vault_${VAULT_VERSION}_linux_amd64.zip && \
    mv ./vault /usr/local/bin/vault && \
    curl -fSsL https://keybase.io/r6by/pgp_keys.asc | gpg --import | gpg --import && \
    curl -fSsLO "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz{,.sha256}" && \
    curl -fSsLO "https://github.com/helm/helm/releases/download/v${HELM_VERSION}/helm-v${HELM_VERSION}-linux-amd64.tar.gz{.asc,.sha256.asc}" && \
    gpg --verify ./helm-v${HELM_VERSION}-linux-amd64.tar.gz.sha256.asc ./helm-v${HELM_VERSION}-linux-amd64.tar.gz.sha256 && \
    gpg --verify ./helm-v${HELM_VERSION}-linux-amd64.tar.gz.asc ./helm-v${HELM_VERSION}-linux-amd64.tar.gz && \
    sha256sum -c <(echo "$(cat helm-v${HELM_VERSION}-linux-amd64.tar.gz.sha256)  helm-v${HELM_VERSION}-linux-amd64.tar.gz") && \
    tar -xzf helm-v${HELM_VERSION}-linux-amd64.tar.gz --strip-components=1 && \
    mv helm /usr/local/bin/helm && \
    chown -R root:root /usr/local/bin && chmod -R 755 /usr/local/bin

COPY --from=ghcr.io/d4rkfella/aws-cli-alpine:2.22.35 /usr/local/aws-cli/ /usr/local/aws-cli/
COPY --from=ghcr.io/d4rkfella/aws-cli-alpine:2.22.35 /aws-cli-bin/ /usr/local/bin/
RUN aws --version

RUN cosign verify ghcr.io/fluxcd/flux-cli:v2.4.0 \
      --certificate-identity-regexp=https://github.com/fluxcd \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com \
      -o text
COPY --from=ghcr.io/fluxcd/flux-cli:v2.4.0 /usr/local/bin/flux /usr/local/bin/flux
RUN flux --version

COPY --from=ghcr.io/siderolabs/talosctl:v1.9.3 /talosctl /usr/local/bin/talosctl
RUN talosctl version --client

RUN cosign verify ghcr.io/getsops/sops:v3.9.4 \
      --certificate-identity-regexp=https://github.com/getsops \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com \
      -o text
COPY --from=ghcr.io/getsops/sops:v3.9.4 /usr/local/bin/sops /usr/local/bin/sops
RUN sops --version

COPY --from=ghcr.io/helmfile/helmfile:v0.171.0 /usr/local/bin/helmfile /usr/local/bin/helmfile
RUN helmfile --version



FROM alpine:3.21.2

ENV LANG="C.UTF-8"
ENV EDITOR=/usr/bin/nano

ARG USERNAME=vscode
ARG USER_UID=2100
ARG USER_GID=$USER_UID

COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/aws-cli/ /usr/local/aws-cli/

RUN apk update && \
    apk upgrade && \
    apk add --no-cache \
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
    docker-cli && \
    addgroup -g $USER_GID $USERNAME && \
    adduser -u $USER_UID -G $USERNAME -s /bin/sh -D $USERNAME && \
    addgroup -g 1001 docker && adduser $USERNAME docker && \
    echo 'alias k=kubectl' >> /home/$USERNAME/.bashrc && \
    echo 'complete -o default -F __start_kubectl k' >> /home/$USERNAME/.bashrc && \
    echo 'eval "$(direnv hook bash)"' >> /home/$USERNAME/.bashrc && \
    kubectl completion bash | tee /etc/bash_completion.d/kubectl > /dev/null

WORKDIR /project

USER $USERNAME

ENTRYPOINT ["/bin/bash"]
