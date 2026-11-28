# renovate: datasource=docker depName=quay.io/keycloak/keycloak
ARG KEYCLOAK_VERSION=26.8.2
# renovate: datasource=github-releases depName=cloakwise-io/keycloak-custom-theme
ARG THEME_VERSION=0.2.2

FROM quay.io/keycloak/keycloak:${KEYCLOAK_VERSION} AS builder

ARG THEME_VERSION

ADD --chown=keycloak:keycloak --chmod=644 \
  https://github.com/cloakwise-io/keycloak-custom-theme/releases/download/v${THEME_VERSION}/keycloak-theme-for-kc-all-other-versions.jar \
  /opt/keycloak/providers/keycloak-theme.jar

ENV KC_HEALTH_ENABLED=true
ENV KC_METRICS_ENABLED=true
ENV KC_DB=postgres

RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:${KEYCLOAK_VERSION}

COPY --from=builder /opt/keycloak/ /opt/keycloak/

ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
