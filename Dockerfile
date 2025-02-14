FROM docker.io/library/python:3.12-alpine AS build

ARG VERSION=v1.5.1

ENV \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CRYPTOGRAPHY_DONT_BUILD_RUST=1 \
    UMASK="0002" \
    TZ="Etc/UTC" \
    BAZARR__PORT=6767 \
    BAZARR_PACKAGE_AUTHOR=d4rkfella \
    BAZARR_PACKAGE_VERSION=${VERSION} \
    BAZARR_VERSION=${VERSION}

WORKDIR /app

RUN apk add --no-cache \
        bash \
        ca-certificates \
        catatonit \
        coreutils \
        ffmpeg \
        jo \
        jq \
        libxml2 \
        libxslt \
        mediainfo \
        nano \
        trurl \
        tzdata \
        unzip \
        libpq \
        curl \
        py3-pip \
        build-base \
        cargo \
        libffi-dev \
        libpq-dev \
        libxml2-dev \
        libxslt-dev \
    && curl -fsSL -o /tmp/app.zip "https://github.com/morpheus65535/bazarr/releases/download/${VERSION}/bazarr.zip" \
    && unzip -q /tmp/app.zip -d /app/bin \
    && rm -rf /app/bin/bin \
    && python3 -m venv /venv \
    && /venv/bin/pip install --upgrade pip

RUN /venv/bin/pip install --no-cache-dir --find-links https://wheel-index.linuxserver.io/alpine-3.21/ \
    --requirement /app/bin/requirements.txt \
    --requirement /app/bin/postgres-requirements.txt

RUN /venv/bin/pip install pyinstaller && \
    /venv/bin/pyinstaller --onefile /app/bin/bazarr.py && \
    ldd /app/dist/bazarr

FROM scratch

COPY --from=build /app/dist/bazarr /app/bin/bazarr
COPY --from=build /usr/bin/catatonit /usr/bin/catatonit
COPY --from=build /usr/share/zoneinfo /usr/share/zoneinfo
COPY --from=ghcr.io/linuxserver/unrar:latest /usr/bin/unrar-alpine /usr/bin/unrar

USER 65532:65532

WORKDIR /app

VOLUME ["/config"]

ENTRYPOINT ["/app/bin/bazarr", "--no-update", "--config", "/config", "--port", "${BAZARR__PORT}"]

LABEL org.opencontainers.image.source="https://github.com/morpheus65535/bazarr"
