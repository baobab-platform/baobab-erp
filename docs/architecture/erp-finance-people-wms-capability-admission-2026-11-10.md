# ERP F1, People and WMS capability admission — 10 November 2026

**Status: implementation governance / admission preparation. No new live service or tenant binding.**

Governing documents: accepted Shared ADR-SHARED-017, ADR-SHARED-033 (F1/F2/F3), ADR-SHARED-045 (People), and accepted ERP ADR-ERP-023/024 (People/WMS). Shared is the capability vocabulary authority, ERP is a candidate executor/adapter owner, and CP/IAM is the runtime legal-actor, entitlement, provider-choice and binding authority.

## Three separate meanings

| Capability group | Canonical contract | ERP declaration | CP action now |
| --- | --- | --- | --- |
| Finance F1 (ledger, journal, statement) | Shared finance/v1 DRAFT/EXPERIMENTAL | CONTRACTED planning only; **no** native finance provider support | Catalogue the keys but refuse tenant binding/route without independent F1-P01–P11, IAM/CP book grant, accountant approval and EA-09 |
| Finance F2 six keys | ADR-033 approved census, no contracts | PROPOSED; no provider | Do not catalogue as capabilities or grant |
| Finance F3 three keys | ADR-033 approved census, no contracts | PROPOSED; no provider | Do not catalogue as capabilities or grant; consolidation accountant policy mandatory |
| People four workforce/payroll keys | Shared people/v1 DRAFT/EXPERIMENTAL | CONTRACTED; BYOP independent; **no** provider | Catalogue only, protect employer-specific provider selection, legal/employer/statutory qualification |
| WMS two custody/warehouse-operation keys | Shared #452 merged (`1004d390`): DRAFT/EXPERIMENTAL canonical v1 | CONTRACTED planned only; no executor preselected | CP catalogue sync registers DRAFT vocabulary; WMS-00…WMS-12 and independent provider admission before binding |
| Existing inventory availability | Shared ERP v1 | IMPLEMENTED on source axis | Existing CP governed activation remains independent |
| Existing order consequence | Shared ERP v1 | PARTIAL | Never promote to IMPLEMENTED by finance namespace census |

## Required connected enablement path

1. Canonical Shared contract and exact version are on main; re-pin ERP/CP locks.
2. ERP builds the actual canonical endpoint/adapter/native operation and verifies real legal-entity/accounting/warehouse scope, including revoked and mismatched negatives.
3. Only then move **individual** operations from planned capabilities to provider `support`, with real evidence paths. No blanket family promotion.
4. ERP publishes a DRAFT generated EngineRegistration and independent repository-signed evidence. A provider-support declaration is not an activation decision.
5. CP catalogue sync verifies Shared owner/version/digest; governed registration creates DRAFT provider support for proven operations. CP/EA-09 verifies approved release, real health, scope, provider-neutral incumbent choice and registration provenance.
6. Separate maker/checker provider activation and tenant-specific binding/grant/readback under IAM/CP authority; positive and negative connected tests, replay/revocation, evidence custody and protected deployment approvals.

**Do not mistake a canonical catalogue entry, generated registration, source tests or a CP UI switch for native operational execution.** A missing CP/IAM legal actor, enabled provider, current book/warehouse/employer scope, native evidence, signer or finance accounting policy blocks execution.
