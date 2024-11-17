FROM alpine:3.20@sha256:1e42bbe2508154c9126d48c2b8a75420c3544343bf86fd041fb7527e017a4b4a

WORKDIR /tmp

RUN apk add --no-cache \
    coreutils \
    curl \
    cosign \
    jq \
    nano \
    bash \
    openssl \
    ca-certificates \
    git \
    github-cli \
    unzip && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256" && \
    echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check --strict && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl && \
    curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 && \
    chmod 700 get_helm.sh && \
    ./get_helm.sh && \
    curl -LO https://github.com/getsops/sops/releases/download/v3.9.1/sops-v3.9.1.linux.amd64 && \
    curl -LO https://github.com/getsops/sops/releases/download/v3.9.1/sops-v3.9.1.checksums.txt && \
    curl -LO https://github.com/getsops/sops/releases/download/v3.9.1/sops-v3.9.1.checksums.pem && \
    curl -LO https://github.com/getsops/sops/releases/download/v3.9.1/sops-v3.9.1.checksums.sig && \
    cosign verify-blob sops-v3.9.1.checksums.txt \
      --certificate sops-v3.9.1.checksums.pem \
      --signature sops-v3.9.1.checksums.sig \
      --certificate-identity-regexp=https://github.com/getsops \
      --certificate-oidc-issuer=https://token.actions.githubusercontent.com && \
    grep "sops-v3.9.1.linux.amd64" sops-v3.9.1.checksums.txt > checksum-linux-amd64.txt && \
    echo "$(cat checksum-linux-amd64.txt)  sops-v3.9.1.linux.amd64" | sha256sum --check --strict && \
    mv sops-v3.9.1.linux.amd64 /usr/local/bin/sops && \
    chmod +x /usr/local/bin/sops

USER nobody:nogroup

WORKDIR /project
VOLUME ["/project"]

CMD ["/bin/sh"]