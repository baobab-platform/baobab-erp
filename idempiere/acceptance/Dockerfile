# EA v2.1 Gate D — CI-ONLY acceptance layer. Never published or deployed.
# Adds the Gate D driver bundle on top of the REAL Baobab iDempiere image built
# from idempiere/Dockerfile, so the shipped finance veto runs unmodified.
ARG BASE_IMAGE=baobab-idempiere:ci
ARG JDK_IMAGE=eclipse-temurin:17-jdk
FROM ${BASE_IMAGE} AS base

FROM ${JDK_IMAGE} AS driver
COPY --from=base /opt/idempiere/plugins/ /idempiere-plugins/
COPY idempiere/acceptance/driver /src
RUN mkdir -p /cp /out \
 && cp /idempiere-plugins/org.adempiere.base_*.jar /idempiere-plugins/org.eclipse.osgi_*.jar /cp/ \
 && javac --release 17 -nowarn -cp '/cp/*' -d /out $(find /src/src -name '*.java') \
 && jar cfm /driver.jar /src/MANIFEST.MF -C /out .

FROM base
USER root
COPY --from=driver --chown=idempiere:idempiere /driver.jar /opt/idempiere/plugins/org.nabhold.baobab.erp.acceptance_0.1.0.jar
RUN echo "org.nabhold.baobab.erp.acceptance,0.1.0,plugins/org.nabhold.baobab.erp.acceptance_0.1.0.jar,5,true" \
      >> /opt/idempiere/configuration/org.eclipse.equinox.simpleconfigurator/bundles.info \
 && install -d -m 0770 -o idempiere -g idempiere /opt/idempiere/.baobab /opt/idempiere/.baobab/gate-d
USER idempiere
