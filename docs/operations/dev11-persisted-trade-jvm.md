# Same persisted Trade event -> real native ERP/JVM qualification

Status: implementation candidate; final-source runtime evidence is required.
EA-DEV DEV-07/09/11/14; ADR-SHARED-018/042/043 and ADR-ERP-006/016/022.
The existing ERP-A disposable development stack owns the execution. No staging,
production, provider activation or L4-OPS-01 acceptance is granted.

## Exact executable source composition

| Source | Executed revision / rule |
| --- | --- |
| Trade | `f2c88d4a70486abe0e44c642f22feaaf8bc18c6c` |
| Trade native buyer parent (#189) | `2b4c7c929801d47d1215771f6071c2704ddd38ec`, verified ancestor |
| Trade broker parent (#188) | `55659409a7e4787c0d70a69d4c1301f13d7fc219`, verified ancestor |
| ERP | Exact PR head checked out by the owning Actions job; `ERP_COMMIT` independently read from Git |
| Infrastructure observer/collector | `65931ab9892b829b0e0b1ca23c53199ba1216e8b` |
| CP | `6fee9fe9537409df428a2e3dd7b8f78ff8d1d456` |
| IAM | `fae32b20187b2201e6070c382f563e170773e692` |

Every companion is checked out by full SHA and its actual Git HEAD checked.
The joined receipt records the executed five-source tuple. Both Trade parents
must be ancestors of the actual checkout. Missing private-repository access,
missing source or failed native execution fails; no dependency is skipped as
successful.

The root is ERP's qualification job. It invokes Trade's existing source script
and confirmed publisher plus its own current consumer/JVM. It does NOT invoke
Trade's separate component workflow or import that workflow's separately
pinned ERP checkout. This gives an acyclic **execution dependency** and a
concrete source tuple without inventing mutually recursive repository SHAs.
The separately pinned broker-component run remains a distinct profile. Older
component receipts are never relabelled as current same-event evidence.
Infrastructure's existing eight-owner acceptance verifier is unchanged; this
new bounded profile does not waive its current-source or custody requirements.

## One immutable event through the existing owners

1. ERP's fixture owner resolves its actual native GardenWorld customer,
   product and unit, and supplies synthetic scope coordinates privately.
2. The composed Trade source uses the existing Medusa outbox module, locking,
   integer valuation kernel, pinned ERP schema and official OTLP exporter.
   It returns IDs of three actually persisted immutable envelopes: positive,
   lost-native-result/recovery and revocation negative. No buyer permission
   or native Medusa order is manufactured.
3. The ERP orchestrator reads those exact stored envelopes in a read-only
   PostgreSQL 17 snapshot. It does not regenerate their ID, payload,
   idempotency, correlation or traceparent. Trade's original origin observer
   must still report `NATIVE_ORDER_ABSENT` for this synthetic profile.
4. The existing Trade-owned confirmed publisher dispatches only the selected
   existing outbox ID from another process. Real RabbitMQ delivers into the
   separate ERP receiver and durable inbox. No direct consumer callback or
   fabricated native result stands in for transport.
5. ERP obtains current real Hydra/CP/documentary/native authority and invokes
   the protected actual JVM. The full Trade ID uses the immutable native UUID
   recovery mapping. Native ID settlement, execution, ERP consequence, outbox
   and inbox outcome commit together. Lost-result recovery must adopt the
   same original order; live revocation must create none.
6. Independent native and CP/JVM observers must pass. A separate read-only
   two-database join then requires the exact source event ID, full original
   payload, correlation, traceparent and native UUID/business effect.
7. Infrastructure's independently sourced observer queries actual exported
   Jaeger spans from Trade, publisher and ERP. A stored traceparent or a
   source-only graph cannot satisfy this step. Existing cleanup includes every
   optional Trade database/Redis/Collector/Jaeger and broker service.

## Evidence and claims

The safe original artifacts are `dev11-trade-jvm-joined.json`,
`dev11-trade-jvm-unknown-joined.json`, `dev11-trade-jvm-exported.json`, the
existing native-effect/CP-JVM/recovery receipts, and independent cleanup.
Raw event/tenant/native/trace IDs, source packets, broker credentials, runtime
logs and private handoff files stay in the disposable run directory and are
removed. A failed join removes a prior success receipt before evaluating.

A successful run establishes same-event actual outbox/broker/ERP/native-JVM
component integration and exported component lineage on synthetic business
inputs. It does not establish a genuine non-draft buyer-authorised Medusa
commitment, full authenticated BFF/IAM/CP/Trade lineage, native financial
posting, the independent eight-owner custody join, or L4-OPS-01. All artifacts
retain `l4_ops_01=BLOCKED`. The genuine CAA-06b buyer event must later traverse
this same publisher/consumer path without a second messaging framework.


## Current image security gate

The Foundation scan at `41907701145` reports two HIGH findings in the upstream
bundled ActiveMQ client 5.16.7: CVE-2026-50734 and CVE-2026-53917. Apache's
[50734 advisory](https://activemq.apache.org/security-advisories.data/CVE-2026-50734-announcement.txt)
and [53917 advisory](https://activemq.apache.org/security-advisories.data/CVE-2026-53917-announcement.txt)
identify fixed 5.19.8/6.2.7 lines. This is a separate merge blocker; no scan
exception, severity reduction or unqualified OSGi replacement is introduced.
The integration proof must not be described as an approved release image.

## 5 November 2026 — physical UUID join correction

Run `41913135994` at `c2084bee` passed independent real native-order
and CP/JVM lineage checks, then failed at the same-event database join with
`uuid = text`. It is a failed qualification, despite the positive worker
and independent native observations. The physical iDempiere system column is
UUID in this fixture; the explicitly supported string-column variant remains
valid too. All native UUID joins and duplicate/recovery/revocation counts now
compare both coordinates as their complete textual UUID representation.
Neither canonical identifiers nor authority/business comparisons change.

The trace observer also removes a previous receipt before running, suppresses
private subprocess arguments on timeout or process errors, and refuses after
the same bounded retry budget. A failed or missing export cannot retain an
earlier success. Final-source real PostgreSQL 17/JVM re-execution is required.

The public dependency inventory workflow reads the base image's actual OSGi
registry/manifests and verifies candidate vendor checksums from Maven Central.
It reports exact SHA-256 values for a reviewed fixed bundle family and JMS
API. This inventory does not mutate the runtime, suppress CVEs or qualify a
replacement; the final image must still pass the container scan, OSGi startup
and actual native business/recovery tests. The local execution environment was
unavailable on 5 November; new changes require actual owning Actions checks.


## Native dependency repair and strict authority time precision

The [native messaging repair](../../idempiere/dependency-overrides/README.md)
replaces the complete installed ActiveMQ family with checksum-pinned 5.19.12
archives and adds the required versioned JMS 2 API. A CI-only actual OSGi
class-space/OpenWire probe now precedes native readiness. Final image scanning
and native integration remain mandatory; neither a source change nor the
public dependency inventory closes the prior CVEs.

Run `41940241463` at `261549cc` passed the real native effect readback but
refused CP/JVM lineage. Its old generic refusal did not establish which
comparison failed. The observer now reports only closed failure categories,
with every existing comparison retained. Source review separately found that
JDBC can round nanosecond expiry up when writing PostgreSQL's microsecond
precision. Native attribution now floors expiry to microseconds, so persistence
cannot extend CP's exact authority ceiling. Tests keep even a one-microsecond
overrun refused; no clock tolerance is added. A fresh actual run must establish
whether the current source passes; the earlier failure is never relabelled.

At `b42e6b29` the container CVE scan passes, but actual native bootstrap fails
before source-event execution. Public image/configuration inspection and actual
Equinox resolution identify the separate setup JVM's missing JMS 2 bundle.
The repair registers it there as well as in the ordinary runtime. A historical
public checksum false positive is handled at its exact fingerprint; secret and
vulnerability scanning remain enabled. This failed candidate supplies no
same-event business or exported-lineage acceptance.

## Ubuntu APT security update

Foundation run `41958462556` reported CVE-2026-109518 for both APT
binary packages at `2.8.4ubuntu0.1`. Ubuntu's published Noble advisory
identifies that version as fixed. The later `2191ad8d` purge attempt was
refused by the base image's essential package safeguard. The runtime
retains both packages and the build disables APT download retries until
the security upgrade has run. It requires both package versions to be
at or above the vendor's fixed version and prints the installed versions
for scan reconciliation.

Run the full image scan and native workflows against the same revision.
If the scanner still disagrees with the Ubuntu advisory, record both
results and investigate the scanner's vulnerability data. The scan gate
continues to apply.

[Ubuntu security notice USN-8996-1](https://ubuntu.com/security/notices/USN-8996-1)
