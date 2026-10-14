# LA-05D9 — Native iDempiere IAM/CP authority and immutable financial attribution

## Implemented

Synchronous `ModelValidationEngine` before-change and before-document handlers already veto protected finance operations. This increment installs a JVM `CpNativeFinancialAuthority` service using client-credentials issued by IAM, then CP-owned /v1/platform-context/resolve for the same IAM workload, followed by exact operation-scoped /internal/legal-actor/v1/assess and negative-only /internal/documentary/v1/restrictions/assess.

The native source supplies ONLY an independently established AD_Client/AD_Org -> tenant/operating Organisation/market/expected actor context; CP mints its own runtime Context identifier for the token subject and checks all current lifecycle facts. Legal mandate/primary-actor current authority and documentary clearance are both revalidated before a permit; company/period/tax/readiness remains a separate native engine service, never conferred by CP. A denied or stale CP assessment, unavailable provider, mismatched mandate, missing current Context, or inactive IAM results in a veto.

On successful **positive** authorization, `NativeFinanceAttribution` writes CP-mandate and evidence references, tenant/Organisation/legal actor, native transaction name, exact document record/client/org/action and a correlation UUID into `baobab_native.finance_authority_attribution` on the SAME iDempiere native JDBC transaction. It does not commit, rollback, or close that connection; the transaction coordinator owns commit. A failure to append denies native mutation. The table rejects UPDATE/DELETE even where SQL grants are broader, and separate DB grants should refuse both.

**Migration:** `db/migrations/0025_native_finance_attribution.sql` is included in the existing `db/migrate.sh` deployment image, applied before the iDempiere Compose service starts. Production migration must target the **same iDempiere database** used by native transactions; do not apply to an unrelated Baobab application database. Compose health cannot pass until the native finance listener PID marker has been written.

## Deliberately not accepted

The OSGi ports `NativeFinancialContextSource` and `NativeFinanceReadiness` have no certified provider implementations on main and no protected account secrets. They must be bound by platform-internal verified services, not JVM flags, incoming HTTP headers or document fields. Until installed, production protected financial mutations are denied. CP currently gates legal assessment outside production and IAM token scopes must be admitted by the canonical registry. The iDempiere native transaction reflection binding, ModelValidationEngine coverage for each UI/scheduler/import posting route, direct DB bypass controls, real posting journal reconciliation and actual protected AWS acceptance require native staging proof. CI is synthetic, not legal/accounting certification.

## Required acceptance

1. Supply trusted client/org-to-runtime Organisation and ERP finance-readiness OSGi providers backed by authoritative records.
2. Issue workload IAM scopes `context:resolve`, `legal-actor:assess`, `documentary:restriction-assess` explicitly, including active canonical-workload registry approvals.
3. Apply the migration to native iDempiere PostgreSQL; verify commit and rollback of attribution and native finance mutation atomically.
4. Test revoked mandate, documentary hold, foreign tenant, incorrect market, inactive tax/period baseline, UI import/batch and direct SQL bypass.
5. Prove installed OSGi bundles ACTIVE, Equinox integration dependency resolved, health marker bound to JVM PID, and protected staging IAM/CP event evidence.

## P0-04A follow-up (13 October 2026)

Python and JVM consumers now enforce exact pinned Shared wire schemas, including
closed fields and formats, before existing current operation/actor, negative veto
and readiness checks. The native client bounds retained bytes and the complete
response deadline; malformed or unavailable facts cannot reach attribution.
This convergence grants no workload admission or protected execution support.
See the [contract-convergence maintenance plan](../plans/P0-04A-erp-contract-convergence.md).

## P0-04B ERP follow-up (14 October 2026)

The two trusted ports now have platform-owned providers backed by governed tables
(`PlacementContextSource`, `BaselineFinanceReadiness`), and the authority calls the
ADR-SHARED-034 posting-authority resolver instead of the bare legal assessment.
Attribution records CP decision, mandate lineage, placement and Finance baseline, and
`db/native-migrations` adds the database COMMIT fence. Required acceptance items 1 and 3
are implemented and proven on PostgreSQL (Gate B); a real iDempiere run (Gate D), IAM
admission and real placements/mandates remain open. See ADR-ERP-022 and
[the P0-04B ERP plan](../plans/P0-04B-ERP-posting-authority.md).
