# DEV-11 native order recovery mapping

Status: implemented behind the explicit operator profile `native-uuid-v1`;
real JVM qualification at the final source remains mandatory. EA-DEV
DEV-07/09/11, ADR-ERP-006/007/016/022. No checkout or protected deployment
activation follows from this change.

## Identity and ownership

A Trade order ID can exceed the 20-character native `C_Order.POReference`.
It must never be truncated, squeezed into a shorter hash, or replaced in the
canonical event. `POReference` is a business reference, not a canonical-ID
store. iDempiere exposes the standard `C_Order_UU` through its generated
[Order model interface](https://jenkins-artifacts.idempiere.org/javadocdev/org/compiere/model/I_C_Order.html).

ERP migration `0026_order_native_reference.sql` stores the FULL Trade order ID,
tenant, legal entity, target engine/company/Organisation, order version,
canonical payload digest, original source event and a server-generated native
UUID. This private recovery intent is not a CP grant or a replacement for a
canonical entity, ExternalReference or CP Mapping. The existing
`order_execution` record retains the complete order-to-native-ID and exact
source-event join after execution.

Before any JVM mutation the order's existing session advisory lock serializes
intent allocation. The intent commits independently so it survives a remote
JVM commit whose reply is lost. A changed scope, version or business digest
cannot reuse it. A new intent whose UUID already exists natively is refused;
creation is marked durably before the engine call. A retry can adopt only
a previously attempted UUID with matching native company, customer, currency
and every original line fact. Multiple matches or foreign facts never select
an arbitrary order. No mutable event payload selects the native UUID.

Native ID settlement commits WITH execution, ERP consequence, consequence
outbox and fenced inbox settlement. Failed settlement leaves an allocated
intent for reconciliation, not a successful ERP business outcome. Immutable
SQL history prevents reference redirection, deletion, truncation or rebinding.
The profile has no automatic conversion of already-executed legacy orders;
missing historical mappings require explicit reconciliation.

## Authority and native interface

The same original full order ID remains CP's consequential operation reference.
Current CP legal actor, documentary, native placement and finance/JVM vetoes
remain mandatory. Native REST egress accepts a UUID only when the private
resolved reference, exact governed action marker, tenant/legal actor and
native company all match; an arbitrary UUID or a mixed `POReference` payload
denies. The existing one-use exact-request guard is unchanged.

The real disposable JVM adapter verifies the physical UUID/string type, full
36-character capacity and a live exact native unique index for `C_Order_UU`
before writing. Its system UUID coordinate is distinct from POReference: the
legacy business-field path still requires BOTH its AD_Column and physical
width limits, and neither limit is increased. The acceptance driver calls the actual native
`MOrder.setC_Order_UU`; it does not mutate native tables with Python SQL. Its
readback/adoption checks retain all native business comparisons. The production
REST transport remains independently subject to provider qualification.

## Qualification and maintenance

The ERP-A real-engine drill now uses unshortened, Medusa-shaped order IDs
longer than 20 characters under the explicit profile. Independent native and
CP/JVM observers query the immutable full-key mapping and actual native UUID.
The native effect observer also verifies the original event ID and full payload
digest. Redelivery and committed-result-loss recovery must retain one order;
live CP revocation must create none. The SQL intent is not an ERP success.

Unit fixtures test scope/fact refusal, long-key preservation, missing native
metadata, absent egress binding and changed source digest. They do not prove
JVM execution. Keep the final-source real PostgreSQL 17/JVM artifacts and
cleanup receipts. Full buyer-authorised Medusa origin, same-event exported
lineage and Infrastructure's independent L4 join remain separate gates.


## Same-event runtime diagnosis and telemetry resolution

Run `41907699984` at `fb01e89` observed actual Trade source/outbox publication,
real ERP admission and current CP/documentary/provider checks, then refused
inside native creation with `ENGINE_UNAVAILABLE`. It did not qualify a native
business effect. The initial adapter applied the business-reference dictionary
width convention to the system UUID coordinate. UUID-specific physical type,
capacity, exact unique-key checks and closed diagnostics now distinguish that
boundary without changing any native authority or business-fact comparison.
The next actual runtime must confirm the protected JVM effect and recovery.

The same run exposed an incompatible orphan OTel exporter after installing
latest ERP dependencies and then downgrading only the Trade SDK set. A fresh
single resolver transaction now installs ERP plus the existing frozen Trade
requirements together, followed by mandatory `pip check`. The fresh local
pinned environment reports no broken requirements. Source/child failures also
retain only closed stages, suppressing private command arguments on timeout
or file errors. Unit negatives preserve the JVM veto even with a valid UUID
schema. Final-source runtime and independent originals remain required.


The native index checks use PostgreSQL 17's
[pg_index catalogue](https://www.postgresql.org/docs/17/catalog-pg-index.html):
unique, valid, ready and live, with one exact non-expression key and no partial
predicate. The current local pinned environment passes 414 unit tests and
`pip check`; the actual Actions PostgreSQL 17/JVM proof remains mandatory.


The UUID profile requires the provider's independent full-business readback
port before any lookup or write. Both a newly returned native ID and an
adopted ID must pass that comparison; a transport returning an integer alone
cannot settle success. Older events retain `STALE_VERSION` without reserving
a new intent, newer versions retain `AMENDMENT_UNSUPPORTED`, and equal-version
replays require the immutable scope and payload digest to match.


Run `41910924583` at `698a5e9` reached actual native creation with the UUID
schema verified and an `EXECUTED` inbox outcome. The independent effect
observer refused, so the overall run FAILED and neither mapping nor joined
qualification was accepted. Closed observer categories now identify the exact
failed check or database error class without exporting private SQL or child
command arguments. Native UUID readback projects textual identity consistently
for both physically supported native UUID and string columns. All original
company, business, CP attribution and consequence checks remain required.
