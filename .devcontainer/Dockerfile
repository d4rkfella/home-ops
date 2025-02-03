FROM alpine:3.21.2@sha256:56fa17d2a7e7f168a043a2712e63aed1f8543aeafdcee47c58dcffe38ed51099

ARG USERNAME=vscode
ARG USER_UID=2100
ARG USER_GID=$USER_UID

# renovate: depName=go-task/task
ARG TASK_VERSION=v3.41.0
# renovate: depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.4.0
# renovate: depName=a8m/envsubst
ARG ENVSUBST_VERSION=v1.4.2

ENV LANG="C.UTF-8"
ENV EDITOR=/usr/bin/nano

COPY --from=hashicorp/vault:1.18.4@sha256:790a848da73ea8260e982e79b1e320e899836a24bf059c1e8484d040623b6b93 /bin/vault /usr/local/bin/vault
RUN vault --version

COPY --from=ghcr.io/d4rkfella/aws-cli-alpine:2.22.35 /usr/local/aws-cli/ /usr/local/aws-cli/
COPY --from=ghcr.io/d4rkfella/aws-cli-alpine:2.22.35 /aws-cli-bin/ /usr/local/bin/
RUN aws --version

COPY --from=alpine/helm:3.17.0@sha256:3171b2d9aed2d6e033f1cf8ae4dc2863a0cef21f167fb4655c15afbe68256432 /usr/bin/helm /usr/local/bin/helm
RUN helm version

COPY --from=fluxcd/flux-cli:v2.4.0@sha256:a9cb966cddc1a0c56dc0d57dda485d9477dd397f8b45f222717b24663471fd1f /usr/local/bin/flux /usr/local/bin/flux
RUN flux --version

COPY --from=ghcr.io/siderolabs/talosctl:v1.9.3 /talosctl /usr/local/bin/talosctl
RUN talosctl version --client

COPY --from=ghcr.io/getsops/sops:v3.9.4@sha256:5861d711e485d01fa9d148654cf267b285f78bc1bf74d9ea208e90be737d2293 /usr/local/bin/sops /usr/local/bin/sops
RUN sops --version

COPY --from=ghcr.io/helmfile/helmfile:v0.170.1@sha256:6f334935f5ee1dc6780bff3a5b781747570b8e0d0abaa7204211ad2be43005a9 /usr/local/bin/helmfile /usr/local/bin/helmfile
RUN helmfile --version

COPY --from=registry.k8s.io/kubectl:v1.32.1@sha256:6ae337221866ae69380cfa08e2b38fa113fd5044cfb5b7a7662f5b0028be23b6 /bin/kubectl /usr/local/bin/kubectl
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

ENTRYPOINT ["/bin/bash", "-i"]
