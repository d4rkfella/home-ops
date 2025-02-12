FROM alpine:3.21.2

ARG USERNAME=vscode
ARG USER_UID=2100
ARG USER_GID=$USER_UID

# renovate: depName=go-task/task
ARG TASK_VERSION=v3.41.0
# renovate: depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.5.0-beta.0
# renovate: depName=a8m/envsubst
ARG ENVSUBST_VERSION=v1.4.2

ENV LANG="C.UTF-8"
ENV EDITOR=/usr/bin/nano

COPY --from=hashicorp/vault:1.18.4 /bin/vault /usr/local/bin/vault
RUN vault --version

COPY --from=ghcr.io/d4rkfella/aws-cli-alpine:2.22.35 /usr/local/aws-cli/ /usr/local/aws-cli/
COPY --from=ghcr.io/d4rkfella/aws-cli-alpine:2.22.35 /aws-cli-bin/ /usr/local/bin/
RUN aws --version

COPY --from=alpine/helm:3.17.0 /usr/bin/helm /usr/local/bin/helm
RUN helm version

COPY --from=fluxcd/flux-cli:v2.4.0 /usr/local/bin/flux /usr/local/bin/flux
RUN flux --version

COPY --from=ghcr.io/siderolabs/talosctl:v1.9.3 /talosctl /usr/local/bin/talosctl
RUN talosctl version --client

COPY --from=ghcr.io/getsops/sops:v3.9.4 /usr/local/bin/sops /usr/local/bin/sops
RUN sops --version

COPY --from=ghcr.io/helmfile/helmfile:v0.170.1 /usr/local/bin/helmfile /usr/local/bin/helmfile
RUN helmfile --version

COPY --from=registry.k8s.io/kubectl:v1.32.1 /bin/kubectl /usr/local/bin/kubectl
RUN kubectl version --client

WORKDIR /tmp

RUN apk update && \
    apk upgrade && \
    apk add --no-cache \
    coreutils \
    curl \
    jq \
    nano \
    bash \
    bash-completion \
    openssl \
    ca-certificates \
    git \
    github-cli \
    libstdc++ \
    direnv \
    yq \
    docker-cli \
    cosign \
    unzip && \
    addgroup -g $USER_GID $USERNAME && \
    adduser -u $USER_UID -G $USERNAME -s /bin/sh -D $USERNAME && \
    addgroup -g 1001 docker && adduser $USERNAME docker && \
    echo 'alias k=kubectl' >> /home/$USERNAME/.bashrc && \
    echo 'complete -o default -F __start_kubectl k' >> /home/$USERNAME/.bashrc && \
    echo 'eval "$(direnv hook bash)"' >> /home/$USERNAME/.bashrc && \
    curl -fsSLO https://github.com/kubevirt/kubevirt/releases/download/$VIRTCTL_VERSION/virtctl-$VIRTCTL_VERSION-linux-amd64 && \
    mv ./virtctl-$VIRTCTL_VERSION-linux-amd64 /usr/local/bin/virtctl && \
    curl -fsSLO https://github.com/go-task/task/releases/download/$TASK_VERSION/task_{linux_amd64.tar.gz,checksums.txt} && \
    sha256sum --check --strict --ignore-missing task_checksums.txt && \
    tar -xvzf task_linux_amd64.tar.gz && mv ./task /usr/local/bin/task && \
    curl -fsSLO https://github.com/a8m/envsubst/releases/download/$ENVSUBST_VERSION/envsubst-`uname -s`-`uname -m` && \
    mv ./envsubst-`uname -s`-`uname -m` /usr/local/bin/envsubst && \
    chown -R root:root /usr/local/bin && chmod -R 755 /usr/local/bin && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME && chmod -R 700 /home/$USERNAME && \
    kubectl completion bash | tee /etc/bash_completion.d/kubectl > /dev/null && \
    rm -rf /root/.cache /tmp/* /var/cache/apk/*

WORKDIR /project

USER $USERNAME

ENTRYPOINT ["/bin/bash"]
