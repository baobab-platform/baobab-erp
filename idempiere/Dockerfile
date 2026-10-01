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

# Jackson override for the iDempiere runtime (ADR-ERP-004 section 5: emergency
# security mitigation of a bundled third-party library; not a fork of iDempiere core).
#   owner:    @baobab-platform/platform-engineering
#   reason:   the pinned iDempiere image bundles Jackson 2.15.4, whose
#             jackson-databind carries HIGH CVE-2026-91776 and CVE-2026-91777;
#             the 2.15 line has no fix (fixed in 2.18.11, 2.21.7, 2.22.3)
#   upstream: idempiereofficial/idempiere:13-release (idempiere-docker); no
#             upstream issue is filed yet -- file one and link it here
#   affected: idempiereofficial/idempiere:13-release, Jackson 2.15.4 bundles
#   removal:  delete this override (and its final-stage swap) once the pinned
#             iDempiere image bundles jackson-databind >= 2.18.11
#   tests:    the final-stage guard fails the build if the base image stops
#             shipping exactly these 2.15.4 bundles; the Foundation container
#             scan (Trivy) must pass
# 2.18.11 is the smallest fixed line. databind 2.18 needs jackson-core and
# jackson-annotations 2.18, so the family moves together, verified against pinned
# SHA-256 digests (cross-checked with Maven Central's published SHA-1, SHA-256 and
# SHA-512). jackson-datatype-joda stays at 2.15.4: its 2.18 line requires
# joda-time [2.12,3) and the image ships joda-time 2.10.14, so an upgraded bundle
# would not resolve. Nothing in the image depends on it, and the 2.15.4 module
# still resolves against the 2.18 core and databind.
RUN set -eu; mkdir -p /build/jackson; cd /build/jackson; \
    m=https://repo1.maven.org/maven2/com/fasterxml/jackson; v=2.18.11; \
    printf '%s\n' \
      "core jackson-annotations 9eab0d36da981645392427eedcb087e13be542488e37f935723dc0be50d18a53" \
      "core jackson-core 825fa72dfb9e2f8a642322f1390dbac22c30d15ebd6dc6b3772158821ee124eb" \
      "core jackson-databind 075ad94a76c3edf83e1972dc26f476361eb6b9d0e260d93fc11105509bc79cab" \
      "dataformat jackson-dataformat-xml 08ad14c8b335fd8cba6b46188a7a0071d328e81a5a545f46c6d0b333c3843694" \
      "datatype jackson-datatype-guava 3eed4eefff6a765f87b5280cb3d6335bbc97fd12930ab39703bcc8f781c80c05" \
      "datatype jackson-datatype-json-org 948e7b5b6adb3c4469a53ee2c4e7e80f28be6652428a3d1f5fa6287e005f3e86" \
      "jaxrs jackson-jaxrs-base 7ac14feba8c41f36d31c8e4f249de8a02971054a4dcc5c8529f9d0131bad2f4b" \
      "jaxrs jackson-jaxrs-json-provider 347118c93c9c9d202f71d635a9fc33bc822c65f2be7acd7c1309adfaf47e2697" \
      "jaxrs jackson-jaxrs-xml-provider bda4536646472899d6e4d5d465f98fd5bc3b586d89f6a74278f69f5f1825af5f" \
      "module jackson-module-jaxb-annotations 6ef536c210df2d5ba2ece053567702eee714a8543b36b1c3dcc430073b12d065" \
      "module jackson-module-jsonSchema a00a4680a9b4b060cecb7895c88ce7e020e56aa5a494098d6d325d25547eefd7" \
    | while read -r g a sum; do \
        f="com.fasterxml.jackson.${g}.${a}_${v}.jar"; \
        curl -fsSL --retry 5 --retry-all-errors -o "$f" "$m/${g}/${a}/${v}/${a}-${v}.jar"; \
        printf '%s  %s\n' "$sum" "$f" | sha256sum --check --strict; \
      done; \
    [ "$(ls /build/jackson/*.jar | wc -l)" = 11 ]

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

# Swap in the patched Jackson bundles (see extensions-builder), the same way as
# Bouncy Castle above: replace each 2.15.4 jar and rewrite its bundles.info entry.
# The guard fails the build if the base image stops shipping exactly one 2.15.4
# bundle and one matching bundles.info entry for each of them, and afterwards
# only jackson-datatype-joda may remain at 2.15.4.
COPY --from=extensions-builder /build/jackson/ /tmp/jackson/
RUN set -eu; \
    info="${IDEMPIERE_HOME}/configuration/org.eclipse.equinox.simpleconfigurator/bundles.info"; \
    old=2.15.4; lines=$(wc -l < "$info"); \
    for new in /tmp/jackson/*.jar; do \
      file=$(basename "$new"); n=${file%_*}; ver=${file##*_}; ver=${ver%.jar}; \
      oldjar="${IDEMPIERE_PLUGINS_DIR}/${n}_${old}.jar"; \
      [ -f "$oldjar" ] || { echo "expected ${n} ${old} bundle" >&2; exit 1; }; \
      [ "$(awk -F, -v n="$n" -v o="$old" '$1==n && $2==o' "$info" | wc -l)" = 1 ] || { echo "bundles.info has no single ${n} ${old} entry" >&2; exit 1; }; \
      rm -f "$oldjar"; \
      install -o idempiere -g idempiere -m 0644 "$new" "${IDEMPIERE_PLUGINS_DIR}/"; \
      awk -F, -v OFS=, -v n="$n" -v o="$old" -v v="$ver" -v f="plugins/${file}" '$1==n && $2==o {$2=v; $3=f} {print}' "$info" > /tmp/bundles.info.new; \
      cat /tmp/bundles.info.new > "$info"; rm -f /tmp/bundles.info.new; \
      [ "$(awk -F, -v n="$n" -v v="$ver" -v f="plugins/${file}" '$1==n && $2==v && $3==f' "$info" | wc -l)" = 1 ]; \
    done; \
    [ "$(wc -l < "$info")" = "$lines" ]; \
    left=$(awk -F, -v o="$old" 'index($1,"com.fasterxml.jackson.")==1 && $2==o {print $1}' "$info"); \
    [ "$left" = "com.fasterxml.jackson.datatype.jackson-datatype-joda" ] || { echo "unexpected Jackson ${old} bundles left: ${left}" >&2; exit 1; }; \
    rm -rf /tmp/jackson

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
