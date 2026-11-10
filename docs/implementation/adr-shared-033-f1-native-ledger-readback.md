# ADR-SHARED-033 F1 — native ledger fact readback increment

**Status:** ENGINEERING PARTIAL / not a capability-provider declaration.
**Architecture acceptance:** Shared PR #450 (proposed merge). **Shared F1 wire:** DRAFT/EXPERIMENTAL.
**Component:** `idempiere/extensions/org.nabhold.baobab.erp.finance/.../NativeLedgerFacts.java`.

## What this implements

A bounded **read-only** native JDBC ledger fact probe, for use only after a future resource server has independently resolved an exact current CP/IAM Finance operation permission and ERP-owned legal-entity/accounting-book scope. It checks current native placement and active Client/Organisation, active bookkeeping schema and currency, current approved FinanceBaseline, historical governed-root attribution (including matching documents through the same `baobab_native.governed_root` rule used at the native COMMIT fence), non-autocommit repeatable-read/serializable isolation and explicit period/as-of. It returns immutable data from `Fact_Acct` without recomputing charges, inventing balances, or permitting posted-row modifications.

The read fails closed on absent/mismatched current permit, wrong tenant/legal entity/organisation/client/org, book currency, withdrawn baseline, missing/ambiguous attribution, weak transaction isolation or a result larger than 1000 rows. **It never returns a truncated financial total.** It does not use role names, frontend input as authority, fallback tenants or financial-transaction simulation.

## Deliberately not implemented / cannot be claimed

- No HTTP endpoint, IAM scope grant, CP operation-specific finance decision, native provider declaration, binding or EA-09 certification. `CurrentAuthority` is an abstract mandatory port only; a synthetic test permit does not qualify it.
- No `finance.ledger.read` response adapter, page/snapshot cursor, certified balance calculation, chart rows or verified reporting policy. Those require full F1-P01/P07/P08/P09 and current finance authority.
- No journal CREATE/SUBMIT/APPROVE/POST/REVERSE through native iDempiere. The existing synchronous native posting veto is retained; it must never be bypassed by custom inserts.
- No `finance.statement.read`, cash movement, live Tax approval, F2 receivable or F3 consolidation.
- The native fixture is a **minimal synthetic PG model** and not evidence of real iDempiere accounting correctness. Gate D and independent full owner qualification still apply.

## Next connected increment

Implement a purpose-specific, current CP finance read decision that attests tenant/legal entity/book/market and delegated principal, with a distinct accepted IAM resource-server scope. Bind a canonical F1 request adapter to this component, with server-created scope and immutable response/snapshot semantics; run real JVM + PG17 on actual native iDempiere; qualify finance approval and F1-P01…F1-P11 before marking a provider IMPLEMENTED. Staging/production and CP bindings remain blocked pending their independent gates.

## PostgreSQL Gate B evidence extension

The existing historical 39 native JDBC test cases remain intact. The F1 readback adds **one** synthetic PostgreSQL regression, bringing this JVM class to **40 executed cases** in CI on both Java 17 and Java 21. CI's explicit surefire count checks now assert 40; this does not reclassify the former 39-case DEV-09 evidence or qualify an IAM/CP finance grant, operational F1 feature, or protected environment.

## Image-build security correction (2026-11-10)

A final-head image-build workflow failed because the Ubuntu Noble `base-files` archive download timed out (an external mirror availability failure; not a native ledger-test failure). The upstream Dockerfile deliberately had `Acquire::Retries=0` as mitigation for [USN-8996-1](https://ubuntu.com/security/notices/USN-8996-1) / CVE-2026-109518: enabling retries on insecure APT HTTP before patched APT risks unverified package installation. Rather than bypassing that control, all configured APT source files are upgraded from HTTP to HTTPS **before** bounded retries; an insecure residual source fails the build. APT's patched `apt` and `libapt-pkg6.0t64` versions are still mandatory before any later APT actions. This change is build reliability/security hygiene, not a financial capability qualification.
