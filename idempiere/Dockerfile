# Multi-stage build: compile the Baobab OSGi extension bundles, then stage them into
# the pinned iDempiere runtime image. This is self-contained -- `docker build -f
# idempiere/Dockerfile .` needs no separate `mvn package` step first, since generic
# tooling (including this repository's own foundation/vulnerability-scan workflow)
# invokes `docker build` directly with no knowledge of a Maven prerequisite.
#
# Build context is the repository root (see compose.yaml: context: ., dockerfile:
# idempiere/Dockerfile), so COPY sources below are rooted at the repo root, not at
# this directory.
ARG IDEMPIERE_IMAGE=idempiereofficial/idempiere:13-release

FROM maven:3-eclipse-temurin-26 AS extensions-builder
WORKDIR /build
COPY idempiere/extensions/ idempiere/extensions/
RUN mvn -q -B -f idempiere/extensions package -DskipTests

FROM ${IDEMPIERE_IMAGE}
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/baobab-platform/baobab-erp" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

# Pick up upstream Ubuntu security patches the pinned base image itself may be
# behind on (e.g. openssl). This patches OS packages only; it does not touch
# iDempiere or its bundled plugin jars, so it isn't a fork under ADR-ERP-004.
USER root
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# Confirmed against idempiere/idempiere-docker's 13-release Dockerfile: IDEMPIERE_HOME
# is /opt/idempiere, IDEMPIERE_PLUGINS_HOME is $IDEMPIERE_HOME/plugins, and the image
# already creates and runs as a non-root "idempiere" user owning that tree.
ARG IDEMPIERE_HOME=/opt/idempiere
ARG IDEMPIERE_PLUGINS_DIR=${IDEMPIERE_HOME}/plugins

COPY --from=extensions-builder --chown=idempiere:idempiere /build/idempiere/extensions/org.nabhold.baobab.erp.integration/target/org.nabhold.baobab.erp.integration-*.jar ${IDEMPIERE_PLUGINS_DIR}/
COPY --from=extensions-builder --chown=idempiere:idempiere /build/idempiere/extensions/org.nabhold.baobab.erp.context/target/org.nabhold.baobab.erp.context-*.jar ${IDEMPIERE_PLUGINS_DIR}/
COPY --from=extensions-builder --chown=idempiere:idempiere /build/idempiere/extensions/org.nabhold.baobab.erp.mapping/target/org.nabhold.baobab.erp.mapping-*.jar ${IDEMPIERE_PLUGINS_DIR}/
COPY --from=extensions-builder --chown=idempiere:idempiere /build/idempiere/extensions/org.nabhold.baobab.erp.events/target/org.nabhold.baobab.erp.events-*.jar ${IDEMPIERE_PLUGINS_DIR}/

# Optional: install the third-party com.trekglobal.idempiere.rest.api plugin if a
# pre-built p2 repository for it has been placed at idempiere/vendor/rest-api-p2/ --
# see idempiere/rest-api/README.md for what belongs there and how to produce it (this
# repository does not build it: doing so needs network access to either a p2 mirror or
# a full source build of iDempiere core that this build environment does not have, per
# architecture/conformance.yaml against ADR-ERP-005/ADR-ERP-013). The install itself
# uses iDempiere's own, already-shipped update-prd.sh -- confirmed present in the
# pinned image, not assumed -- so it needs no extra network access of its own. Empty by
# default (its tracked, checked-in state), in which case this step is a clean no-op.
USER idempiere
COPY --chown=idempiere:idempiere idempiere/vendor/rest-api-p2/ /tmp/rest-api-p2/
RUN if [ -f /tmp/rest-api-p2/content.xml ] || [ -f /tmp/rest-api-p2/content.jar ]; then \
        echo "Installing com.trekglobal.idempiere.rest.api from /tmp/rest-api-p2" && \
        "${IDEMPIERE_HOME}/update-prd.sh" /tmp/rest-api-p2 com.trekglobal.idempiere.rest.api; \
    else \
        echo "No pre-built REST API p2 repository at idempiere/vendor/rest-api-p2/; skipping install (see idempiere/rest-api/README.md)"; \
    fi && \
    rm -rf /tmp/rest-api-p2
