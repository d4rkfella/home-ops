FROM python:3.11-alpine3.21 AS builder

ARG AWS_CLI_VERSION=2.22.35

RUN apk add --no-cache git \
        unzip \
        groff \
        build-base \
        libffi-dev \
        cmake

RUN mkdir /aws && \
    git clone --single-branch --depth 1 -b ${AWS_CLI_VERSION} https://github.com/aws/aws-cli.git /aws && \
    cd /aws && \
    python -m venv venv && \
    . venv/bin/activate && \
    pip install --upgrade pip setuptools && \
    ./scripts/installers/make-exe

RUN unzip /aws/dist/awscli-exe.zip && \
    ./aws/install --bin-dir /aws-cli-bin

# Reduce image size: remove autocomplete and examples
RUN rm -rf \
    /usr/local/aws-cli/v2/current/dist/aws_completer \
    /usr/local/aws-cli/v2/current/dist/awscli/data/ac.index \
    /usr/local/aws-cli/v2/current/dist/awscli/examples && \
    find /usr/local/aws-cli/v2/current/dist/awscli/data -name completions-1*.json -delete && \
    find /usr/local/aws-cli/v2/current/dist/awscli/botocore/data -name examples-1.json -delete


FROM alpine:edge@sha256:115729ec5cb049ba6359c3ab005ac742012d92bbaa5b8bc1a878f1e8f62c0cb8

ARG USERNAME=vscode
ARG USER_UID=2100
ARG USER_GID=$USER_UID
# renovate: depName=fluxcd/flux2
ARG FLUX_VERSION=v2.4.0
# renovate: depName=getsops/sops
ARG SOPS_VERSION=v3.9.4
# renovate: depName=siderolabs/kubelet
ARG KUBECTL_VERSION=v1.32.0
# renovate: depName=helmfile/helmfile
ARG HELMFILE_VERSION=v0.170.1
# renovate: depName=helm/helm
ARG HELM_VERSION=v3.17.0
# renovate: depName=go-task/task
ARG TASK_VERSION=v3.41.0
# renovate: depName=siderolabs/talos
ARG TALOSCTL_VERSION=v1.9.2
# renovate: depName=kubevirt/kubevirt
ARG VIRTCTL_VERSION=v1.4.0

ENV LANG="C.UTF-8"
ENV EDITOR=/usr/bin/nano

COPY --from=hashicorp/vault:1.18@sha256:8f1ba670da547c6af67be55609bd285c3ee3d8b73f88021adbfc43c82ca409e8 /bin/vault /usr/local/bin/vault
RUN vault --version

COPY --from=builder /usr/local/aws-cli /usr/local/aws-cli
COPY --from=builder /aws-cli-bin/ /usr/local/bin/
RUN aws --version

COPY --from=alpine/helm:3.17.0@sha256:6e751770fffffb091a931103108c67a61ee622950a3087dec44a5e2fe7860e41 /usr/bin/helm /usr/local/bin/helm
RUN helm version
 
COPY --from=fluxcd/flux-cli:v2.4.0@sha256:a9cb966cddc1a0c56dc0d57dda485d9477dd397f8b45f222717b24663471fd1f /usr/local/bin/flux /usr/local/bin/flux
RUN flux --version

COPY --from=ghcr.io/siderolabs/talosctl:v1.9.2@sha256:94f040316809b5ee6a20bb77b81bf61ded7d7ad9f397344dc02ac79b25bb671c /talosctl /usr/local/bin/talosctl
RUN talosctl version --client

COPY --from=ghcr.io/getsops/sops:v3.9.4-alpine-amd64@sha256:0fe7f11db354b659098a39440384b544a653216870a5ec0ec5fc170105144d37 /usr/local/bin/sops /usr/local/bin/sops
RUN sops --version

COPY --from=ghcr.io/helmfile/helmfile:v0.170.0@sha256:148416f84878f1b58e61e8f6b6e94937bda41c91dce935545b34aae4f03caf2a /usr/local/bin/helmfile /usr/local/bin/helmfile
RUN helmfile --version

COPY --from=k8s.gcr.io/kubectl:v1.32.1 /bin/kubectl /usr/local/bin/kubectl
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
    unzip && \
    rm -rf /var/cache/apk/* && \
    addgroup -g $USER_GID $USERNAME && \
    adduser -u $USER_UID -G $USERNAME -s /bin/sh -D $USERNAME && \
    echo 'alias k=kubectl' >> /home/$USERNAME/.bashrc && \
    echo 'complete -o default -F __start_kubectl k' >> /home/$USERNAME/.bashrc && \
    echo 'eval "$(direnv hook bash)"' >> /home/$USERNAME/.bashrc && \
    curl -fsSL https://taskfile.dev/install.sh | bash -s -- -d $TASK_VERSION -b /usr/local/bin && \
    curl -fsSLO https://github.com/kubevirt/kubevirt/releases/download/$VIRTCTL_VERSION/virtctl-$VIRTCTL_VERSION-linux-amd64 && \
    mv ./virtctl-$VIRTCTL_VERSION-linux-amd64 /usr/local/bin/virtctl && \
    helm plugin install https://github.com/databus23/helm-diff && \
    chown -R root:root /usr/local/bin && chmod -R 755 /usr/local/bin && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME && chmod -R 750 /home/$USERNAME && \
    kubectl completion bash | tee /etc/bash_completion.d/kubectl > /dev/null && \
    rm -rf /root/.cache /tmp/*

WORKDIR /project

USER $USERNAME

ENTRYPOINT [ "/bin/bash", "-c" ]
CMD [ "bash" ]
