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

COPY --from=hashicorp/vault:1.18.3@sha256:8f1ba670da547c6af67be55609bd285c3ee3d8b73f88021adbfc43c82ca409e8 /bin/vault /usr/local/bin/vault
RUN vault --version

COPY --from=ghcr.io/d4rkfella/vault-backup:latest@sha256:4632f425536f50b0d25776c275a2f773ea451a34d29355753d6b861cee9284a0 /usr/local/aws-cli /usr/local/aws-cli
RUN ln -s /usr/local/aws-cli/v2/current/bin/aws /usr/local/bin/aws \
    && ln -s /usr/local/aws-cli/v2/current/bin/aws_completer /usr/local/bin/aws_completer
RUN aws --version

COPY --from=alpine/helm:3.17.0@sha256:6e751770fffffb091a931103108c67a61ee622950a3087dec44a5e2fe7860e41 /usr/bin/helm /usr/local/bin/helm
RUN helm version

COPY --from=fluxcd/flux-cli:v2.4.0@sha256:a9cb966cddc1a0c56dc0d57dda485d9477dd397f8b45f222717b24663471fd1f /usr/local/bin/flux /usr/local/bin/flux
RUN flux --version

COPY --from=ghcr.io/siderolabs/talosctl:v1.9.3@sha256:d1d324131e46d915ab16a24aba8e5aabd3361c0749f78fb2cf16703eafae8a2f /talosctl /usr/local/bin/talosctl
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

CMD [ "/bin/bash", "-i" ]
