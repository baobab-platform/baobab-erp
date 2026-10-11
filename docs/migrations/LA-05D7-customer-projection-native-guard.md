# LA-05D7 — protect customer inbox → iDempiere C_BPartner mutation

**Authority:** ADR-BCP-026, ADR-BCP-027 Package 4 (LA-05). This completes native ERP event-worker bypass closure after LA-05D4 invoice, LA-05D5 direct order-to-cash service, LA-05D6 Trade order inbox.

**The bypass:** `customers.projection_execution._execute` directly calls `engine.create_record("C_BPartner")` and `engine.update_record("C_BPartner")` upon receipt of `trade.customer.projected`, without routing through the protected service. An inbound event's signature, tenant ID or legacy legal entity is insufficient legal actor authority to create accounting master data.

**Implementable controls:**
1. A separately approved `CustomerNativeAuthority` binds an exact CP-issued runtime context, current Organisation/tenant, **ACCOUNTING_ENTITY** mandate, activity, market, operation-specific source customer ID, provider-registered capability and native readiness.
2. In staging/production or an unknown environment, the event worker must inject a **separate** `customer_authority_for(claim)`. Any absent/failed authority lookup becomes `LEGAL_ACTOR_PENDING`; denied CP/documentary/provider decisions become `LEGAL_ACTOR_DENIED`. No native update, create, adopt or outbound master-data event occurs in those cases.
3. A successful protected operation uses the existing `perform_governed_native_action` to check current CP mandate twice, current documentary negative veto twice, iDempiere provider readiness and exact actor/tenant/action/resource before creating a temporary execution marker. There is no shared customer/order permit. The marker is reset after this one mutation.
4. No default production authority is wired; the process is **blocked** until operator-owned authenticated IAM/CP/ERP capability wiring is provisioned. The test fixture uses explicit `BAOBAB_DEPLOYMENT_ENV=test` for legacy fake engine behaviour.
5. PostgreSQL integration tests prove fail-closed staging for unapproved partner creation, plus a synthetic separately scoped CP-authorised customer projection. No actual verified company, CIPC issuer, PSP or native ERP certification is claimed.

**External operational gates:** live workload identity, current CP mandate and documentary token-backed transport, canonical capability declaration for customer master-data, verified AD_Client/AD_Org and iDempiere ERP rights, real provider failure/recovery, signed audit and protected multi-tenant staging tests. These remain separate; neither synthetic CI nor a self-declared parent/tenant may satisfy them.

No Package 5–8 or EA v2.1 work was started.
