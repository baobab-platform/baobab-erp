# LA-05D5 — Close native ERP order-to-cash legacy bypasses

**Authority:** Accepted ADR-BCP-026 and ADR-BCP-027 Package 4 / LA-05. Extends merged LA-05D4 invoice-posting guard (ERP PR #83), LA-05C Trade checkout and LA-05E Payments candidate PEP.

## Boundary

| Native legacy entry point | Mutation that is denied directly in staging/production |
|---|---|
| `create_sales_order` | iDempiere C_Order creation and mapping |
| `complete_sales_order` | native order acceptance process, ERP outbox |
| `create_shipment` | iDempiere M_InOut creation and mapping |
| `complete_shipment` | native shipment completion and outbox |
| `create_customer_invoice` | iDempiere C_Invoice creation, draft issuer attribution |
| `post_customer_invoice` | retained LA-05D4 issuer posting guard |
| `create_payment` | iDempiere C_Payment creation |
| `complete_payment` | native payment accounting completion |
| `allocate_payment` | native payment-to-invoice allocation and accounting outbox |

**No** endpoint/request may pass a `governed=true` flag to circumvent this rule. Missing or unknown `BAOBAB_DEPLOYMENT_ENV` is protected by default. The only legacy compatibility settings are `development` and `test` unless `BAOBAB_REQUIRE_LEGAL_ACTOR_GATE=true`, which overrides both.

### Governed action composition

`NativeActionPolicy` describes the exact, **approved and pinned** provider capability and activity for each supported native action. This code does not invent new canonical Shared capability keys. The operator-owned composition root MUST inject an approved policy mapping from the live provider declaration; absent binding denies.

`perform_governed_native_action` requires:
- Canonical `LegalActorOperation` from a CP-issued authenticated runtime context, exact tenant, Organisation, expected responsible legal person, role/activity/market, capability and operation resource reference.
- The **correct** role family for each action: `CONTRACTING_PARTY` for order/shipment, `INVOICE_ISSUER` for invoice creation, `ACCOUNTING_ENTITY` for payment accounting.
- Current CP legal actor assessor with independent evidence and mandate, a separate iDempiere provider readiness assessor, and documentary restrictions checked before and after native readiness. The CP decision is re-read at the last point of use.
- A temporary in-process per-action marker with the exact tenant, legal actor, operation type and document reference. Nested or cross-tenant uses are denied; the permit is revoked on scope exit, including exceptions.

This internal execution token is a **defence in depth** for trusted ERP code, not an IAM bearer credential or an authorisation substitute. Protected IAM ingress, operation-specific API routes and independently certified iDempiere/PSP readiness remain staging acceptance dependencies.

### Execution safety

- No direct legacy native operation may mutate mapping, iDempiere or outbox under a protected runtime.
- Even with a CP-approved legal actor, the independent provider and documentary gates can deny.
- No synchronous per-tenant DEFAULT or Nabhold parent/subsidiary mapping can authorise another tenant or action.
- Synthetic unit tests prove the bypass guards for eight non-invoice actions, role and resource isolation, stale authority, documentary holds and contextual revocation; LA-05D4 already covers invoice posting.

### Remaining operational proof

1. Register and approve exact canonical capability keys for each action with Shared's provider-support policy; wire trusted action policies and native adapters into engine composition.
2. Demonstrate IAM-issued resource-audience tokens and current CP mandate/hold assessments under actual staging actors; negative tests for cross-tenant/issuer/currency/market/PSP/provider outages.
3. Validate end-to-end iDempiere transaction/outbox consistency and recoverability, including invoices, payments and legacy batch handlers outside this module.
4. Preserve historic posted document issuer attribution; never rewrite prior invoice, liability or tax evidence due to later founding incorporation or market exit.

**Package boundary:** This closes the listed native O2C call entry points in code. It is *not* a blanket production readiness/support claim and does not begin Packages 5–8 or EA v2.1.
