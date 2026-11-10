# Temporary native messaging security adaptation

Owner: ERP engineering. Governing ADR-ERP-004 section 5 emergency security
mitigation; this does not fork iDempiere core, replace RabbitMQ or activate an
ERP business capability. Remove the whole adaptation when the reviewed upstream
image supplies a compatible fixed native dependency family.

## Observed problem and exact inputs

Foundation run `41913138744` reports HIGH CVE-2026-50734 and CVE-2026-53917
in the native ActiveMQ client 5.16.7. Apache's original advisories identify
fixed 5.19.8/6.2.7 lines:

- https://activemq.apache.org/security-advisories.data/CVE-2026-50734-announcement.txt
- https://activemq.apache.org/security-advisories.data/CVE-2026-53917-announcement.txt

The public inventory run `41940241513` independently read the actual 13-release
bundle registry, manifests and vendor JAR bytes. The current 5.x maintenance
release 5.19.12 requires `javax.jms [2.0,3)` and `org.slf4j [2.0,3)`. The native
image supplies SLF4J 2.0.17 but only the older JMS 1.1 API. A one-JAR swap would
leave an unresolved or inconsistent runtime. The native image contains no
ActiveMQ broker bundle; none is installed by this repair.

| Vendor archive | Version | Pinned SHA-256 |
| --- | --- | --- |
| activemq-client | 5.19.12 | `d433eb32bfda4c3ec20fcf4dfb8cd2b256fb3fde52f14f16aebdf99822840770` |
| activemq-jaas | 5.19.12 | `10953cccc30fbd281c91223898974322fc518c39f2887e4bbe4e1683008445f0` |
| activemq-kahadb-store | 5.19.12 | `02ce2410091653e23c0603f52a958612b1a1f77ebf6706acb875907f0d38d9ae` |
| activemq-openwire-legacy | 5.19.12 | `fa7dccbcc2bdc3089c8c5a762498aa66241055bf97317b3f901e471a618f4874` |
| jakarta.jms-api | 2.0.3 | `5940937cb1095764a0039dae147395e37528a0575e2366f4dd20713b7785044a` |

The inventory checked Maven Central's published SHA-1 sidecars (stronger
sidecars were unavailable for these releases), then independently computed the
SHA-256 values above. Every build requires these exact SHA-256 values before
adapting anything. A missing or changed vendor archive fails the build.

## Supported OSGi adaptation and class-space checks

`PrepareNativeMessaging.java` keeps each complete vendor archive byte-for-byte
inside its wrapper, preserving original signatures, metadata and licences. It
preserves the four native symbolic names and uses ordinary OSGi host fragments
for the three sidecars. The native dependency family shares utility packages;
separate wires can hide part of those packages. The host/fragment class space
contains all four original archives. No class is rewritten.

The official client's external import ranges and export `uses` constraints
remain intact. Only imports of packages physically owned by this fixed family
are removed, matching the native target's no-self-import policy. Wrapper
exports are derived from actual class packages. Other external package imports
retain the upstream wrappers' optional policy, with mandatory JMS 2/SLF4J 2
imports where used. This does not certify native JAAS, KahaDB persistence or
legacy-broker operation. JMS 2.0.3 exports **javax.jms**, not jakarta.jms. Its
separate versioned OSGi capability leaves the existing legacy JMS capability
available; consumers must resolve one consistent class space.

Docker guards require the exact four previous native files/registry entries,
preserve their start levels, and refuse any old 5.16.7 archive left behind.
They add precisely the new JMS API entry; no CVE exception, severity reduction
or core manifest patch is introduced. Re-audit an upstream change instead of
loosening those guards.

The CI-only `NativeMessagingCompatibility` probe runs inside the actual
started iDempiere OSGi framework before Gate D/ERP-A readiness. It requires the
exact fixed family and attached fragments, verifies that native core and
client share the identical JMS `Message` class and actual JMS 2 capability,
constructs the real connection factory without connecting, and performs a real
OpenWire text/property roundtrip. It sends no network message, creates no
business record and grants no authority. The native finance veto remains
unchanged by the probe.

## Validation and removal

Local Java 17 packaging/integrity checks and a real disposable Equinox/JMS 2
OpenWire roundtrip pass. These are dependency checks, not native iDempiere
acceptance. All 417 Python unit tests and 82 executed Maven unit tests pass
locally; 39 PostgreSQL-gated Java tests are skipped locally and still require
the real PostgreSQL 17 jobs.
Final-source image scan, actual core/client OSGi probe, native Gate D/ERP-A,
Trade event/recovery/revocation and independent exported evidence must pass
before the new image is considered qualified. L4-OPS-01 and protected release
authority remain blocked.

## Separate setup bootstrap — 5 November repair

The image vulnerability scan at `b42e6b29` passes, but native Gate D and ERP-A
exit during initial setup. The pinned public runtime layer
`sha256:31096b19226e4754e06666e6749ab7681b2630e33dffb0469fa294530f0eaa15`
was independently downloaded and hash-verified before inspecting its actual
plugins and configurations. The setup application has its own explicit
`setup/configuration/config.ini` bundle list; it does not consume the main
runtime `bundles.info`. Its old JMS entry did not install the new JMS 2 API.
The Docker repair now adds the capability to both bootstraps with exact old
configuration guards and a single new setup entry.

A local test using the **actual image's Equinox 3.18.500 and actual setup
plugin set** observes: original stock profile resolves; fixed client without
JMS 2 refuses resolution; fixed profile with the new JMS 2 entry resolves and
native core/client see the identical JMS class. This is dependency/bootstrap
resolution, not database or business acceptance. Actual full CI must rerun.

Gitleaks also matched the **public** JMS archive checksum beside the artifact
name `jakarta.jms-api`. Current source separates the digest constant from that
name. One exact historical commit/path/line fingerprint is recorded with its
public provenance; full-history scanning and every detection rule remain on.
This does not suppress a credential, a future match or a vulnerability finding.
