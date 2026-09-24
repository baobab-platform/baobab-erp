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

# Bouncy Castle override for the iDempiere runtime. The pinned iDempiere
# image bundles Bouncy Castle 1.81 (OSGi bundles bcprov/bcpkix/bcutil/bcpg/bcmail),
# whose bcprov carries CRITICAL CVE-2026-8763 (name-constraints bypass) and
# HIGH CVE-2026-13506, fixed in 1.85. Fetch the patched bundles here,
# verified against pinned SHA-256 digests (cross-checked with Maven
# Central's published SHA-1); the final stage swaps them in. The whole
# family (bcprov/bcpkix/bcutil/bcpg/bcmail) moves together because bcpg and
# bcmail import bcprov packages with version "[x,x+0.01)".
RUN set -eu; mkdir -p /build/bc; cd /build/bc; \
    m=https://repo1.maven.org/maven2/org/bouncycastle; \
    curl -fsSL -o bcprov_1.85.2.jar "$m/bcprov-jdk18on/1.85.2/bcprov-jdk18on-1.85.2.jar"; \
    curl -fsSL -o bcpkix_1.85.0.jar "$m/bcpkix-jdk18on/1.85/bcpkix-jdk18on-1.85.jar"; \
    curl -fsSL -o bcutil_1.85.0.jar "$m/bcutil-jdk18on/1.85/bcutil-jdk18on-1.85.jar"; \
    curl -fsSL -o bcpg_1.85.0.jar "$m/bcpg-jdk18on/1.85/bcpg-jdk18on-1.85.jar"; \
    curl -fsSL -o bcmail_1.85.0.jar "$m/bcmail-jdk18on/1.85/bcmail-jdk18on-1.85.jar"; \
    printf '%s  %s\n' \
      986b0fb92ec10e0c66b43e036ce0077e6150cfaecd1db9fb92b56672e157afe5 bcprov_1.85.2.jar \
      c9f82b2d4e99c4bbdfccf684e52cc06ea06a0b567bfd0d08f9c5a3f417055996 bcpkix_1.85.0.jar \
      590f55ed5d68529239898a4a5c4f730b6e37f45d1cfa3fbe51f8485abe32c42d bcutil_1.85.0.jar \
      39426367dc247dfaae9b1253457a39298b6b9a6c28a39b908bca829e315323dd bcpg_1.85.0.jar \
      ab87de929f8fb8d515143921580b60b7dcc6507f07939ca345b8ffa07d213837 bcmail_1.85.0.jar \
      | sha256sum --check --strict

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
# Swap in the patched Bouncy Castle bundles (see extensions-builder). The
# image ships no pre-built OSGi cache, so the simpleconfigurator's
# bundles.info alone decides what is installed: replace the five 1.81 jars
# and rewrite their bundles.info entries. The guard fails the build if the
# base image stops shipping exactly these 1.81 bundles, so this override is
# revisited rather than silently misapplied. Remove it once the pinned
# iDempiere image bundles Bouncy Castle >= 1.85.
COPY --from=extensions-builder /build/bc/ /tmp/bc/
RUN set -eu; \
    info="${IDEMPIERE_HOME}/configuration/org.eclipse.equinox.simpleconfigurator/bundles.info"; \
    for n in bcprov bcpkix bcutil bcpg bcmail; do \
      old=$(ls "${IDEMPIERE_PLUGINS_DIR}/${n}_1.81.0"*.jar); \
      [ "$(echo "$old" | wc -l)" = 1 ] || { echo "expected one ${n} 1.81 bundle" >&2; exit 1; }; \
      grep -q "^${n},1\.81\.0" "$info" || { echo "bundles.info has no ${n} 1.81 entry" >&2; exit 1; }; \
      new=$(ls /tmp/bc/${n}_*.jar); ver=$(basename "$new" .jar | sed "s/^${n}_//"); \
      rm -f "$old"; \
      install -o idempiere -g idempiere -m 0644 "$new" "${IDEMPIERE_PLUGINS_DIR}/"; \
      sed -i "s#^${n},1\.81\.0[^,]*,plugins/[^,]*,#${n},${ver},plugins/$(basename "$new"),#" "$info"; \
      grep -q "^${n},${ver},plugins/$(basename "$new")," "$info"; \
    done; \
    rm -rf /tmp/bc

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

# Readiness of the ZK web UI. iDempiere bootstraps OSGi and its database
# connections slowly (and runs setup on first start), so allow a 3-minute
# start period before failures count. Probes the same HTTPS listener and
# curl client that compose.yaml's healthcheck already uses for this image
# (only 8443 is published), with -k for the image's self-signed certificate.
HEALTHCHECK --interval=30s --timeout=10s --start-period=3m --retries=3 \
  CMD curl -kfsS https://127.0.0.1:8443/webui/index.zul >/dev/null || exit 1
