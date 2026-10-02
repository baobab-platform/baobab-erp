#!/usr/bin/env bash
# Evidence for the nested jackson-core finding (CVE-2026-89425) in an iDempiere base image.
#   scripts/probe-idempiere-image.sh <image-ref> <out-dir>
# Reports: resolved digest, how the Hazelcast service bundle carries jackson-core, whether it
# is auto-started, and which bundles import from it. Needs registry egress (CI).
set -eu
image=$1; out=$2; mkdir -p "$out"
docker pull -q "$image" >/dev/null
digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$image")
cid=$(docker create "$image"); trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT
{
  echo "image: $image"; echo "digest: $digest"
  docker cp "$cid:/opt/idempiere/plugins" "$out/plugins" 2>/dev/null
  docker cp "$cid:/opt/idempiere/configuration/org.eclipse.equinox.simpleconfigurator/bundles.info" "$out/bundles.info"
  hz=$(ls "$out"/plugins/org.idempiere.hazelcast.service_*.jar | head -1)
  echo "hazelcast bundle: $(basename "$hz")"
  echo "--- jackson inside it"; unzip -l "$hz" | grep -iE 'jackson|\.jar$' || echo "(no nested jars listed)"
  unzip -p "$hz" META-INF/MANIFEST.MF | tr -d '\r' | sed ':a;N;$!ba;s/\n //g' | grep -E '^(Bundle-SymbolicName|Bundle-ClassPath|Import-Package|Require-Bundle|Embed)' | cut -c1-600
  echo "--- jackson-core in the nested hazelcast.jar (maven metadata and shaded packages)"
  mkdir -p "$out/nested" && unzip -q -o "$hz" lib/hazelcast.jar -d "$out/nested"
  unzip -l "$out/nested/lib/hazelcast.jar" | grep -iE 'jackson.*(pom\.properties|JsonFactory\.class)' | head -10 || true
  unzip -p "$out/nested/lib/hazelcast.jar" 'META-INF/maven/com.hazelcast/hazelcast/pom.properties' 2>/dev/null | grep -E '^(version|artifactId)=' || true
  unzip -l "$out/nested/lib/hazelcast.jar" | grep -ciE 'shaded.*jackson' | sed 's/^/shaded jackson entries: /' || true
  echo "--- jackson-core versions found anywhere else in plugins"
  for j in "$out"/plugins/*.jar; do unzip -p "$j" META-INF/maven/com.fasterxml.jackson.core/jackson-core/pom.properties 2>/dev/null | sed -n "s|^version=|  $(basename "$j"): |p" || true; done
  echo "--- bundles.info entry (start level / autostart)"; grep -E '^org\.idempiere\.hazelcast' "$out/bundles.info" || true
  echo "--- bundles that name the hazelcast service bundle or its packages"
  for j in "$out"/plugins/*.jar; do
    if unzip -p "$j" META-INF/MANIFEST.MF 2>/dev/null | tr -d '\r' | sed ':a;N;$!ba;s/\n //g' | grep -Eq '^(Require-Bundle|Import-Package):.*org\.idempiere\.hazelcast'; then echo "  $(basename "$j")"; fi || true
  done
} | tee "$out/probe.txt"
rm -rf "$out/plugins" "$out/nested"
