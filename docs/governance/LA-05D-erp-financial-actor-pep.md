# LA-05D — iDempiere legal actor PEP acceptance seam

**Authority:** ADR-BCP-027 LA-05, Shared PR #261 and CP legal actor assessment PR #299.

This increment adds a pure, tested **opt-in** boundary `modules/order_to_cash/legal_actor_gate.py` to execute a financial command only after **fresh CP legal-actor assessment** and **separate ERP native readiness**:

- `LegalActorOperation` explicitly carries the CP-minted, workload-principal-owned RUNTIME `context_id`, canonical operating Organisation, tenant, role, activity, ISO country market, capability and operation reference; the expected LegalEntity is separately verified and must match CP's answer.
- `LegalActorAssessor.assess` is the CP transport port: it passes *no* tenant, legal actor, mandate, reviewer or evaluation time; the CP contract derives these from the trusted context and verifies current mandate evidence and PRIMARY Organisation.
- `LegalActorProviderReadiness.ensure_legal_actor_usable` must independently prove the verified entity/role maps to **this** iDempiere client/organisation, approved Finance baseline, posting period, permissions and statutory capability. An absence, timeout or deny MUST block the operation.
- `perform_governed_financial_action` calls the CP assessor on each request and each retry before the native `execute` callback; rejects stale, non-authorizing or mismatched responses (including evidence and effective time) and any absent provider.
- Existing ERP `TenantScope.legal_entity_id`, AD_Client_ID/AD_Org_ID and legacy DEFAULT compatibility mappings are not legal-actor proof.

**Acceptance limitation:** this is an integration seam, **NOT YET production invoice enforcement**. The live `modules/order_to_cash/service.py` command methods and `modules/order_to_cash/inbox_execution.py` still need to inject the actual authenticated CP client, owner-bound context issuer and iDempiere financial eligibility adapter before they can be certified under LA-05D. No existing routes are claimed guarded merely because the port exists. The previous unaudited order.placed event does not independently authorize an invoice issuer.

Payment settlement and Trade Docs document issuance are separate PEPs. No Nabhold group company role is automatically inferred.
