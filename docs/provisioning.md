# Provisioning

Per ADR-ERP-019, onboarding a legal entity is never reduced to creating an `AD_Client`.
`modules/provisioning.lifecycle.LegalEntityLifecycleState` models the required gates:

```text
REQUESTED
   → ISOLATION_PROFILE_SELECTED
   → ENGINE_INSTANCE_ASSIGNED
   → ACCOUNTING_CONFIGURED
   → ACTIVE
   ⇄ SUSPENDED
   → DECOMMISSIONING
   → DECOMMISSIONED (terminal)
```

`transition()` enforces the allowed edges and raises
`InvalidLifecycleTransitionError` on any attempt to skip a gate (for example, moving
straight from `REQUESTED` to `ACTIVE` without an assigned `EngineInstance` and configured
accounting). See `tests/unit/test_provisioning_lifecycle.py`.

## Proposed South African accounting actor for ZuriBeans (10 October 2026)

The accepted architectural direction is **ZuriBeans as a separate operating Organisation and CP tenant; NABHOLD GROUP AFRICA (Pty) Ltd (`NABHOLD`) as the *proposed*, not yet approved, responsible ZA legal person**. An unincorporated ZuriBeans must not acquire a fabricated iDempiere legal company or ERP Finance baseline. Accounting dimensions can distinguish ZuriBeans activity *inside the authorised legal entity*, but an ERP AD_Client/AD_Org mapping, corporate parent relationship, or trading style is not itself a legal-actor mandate.

The `config/provisioning/zuribeans.*.example.json` fixtures now show `NABHOLD` only as a pending ZA candidate with distinct role-specific decisions. The same fixtures explicitly block UG until a separately evidenced market-specific legal actor and provider/regulatory determination exists. Localisation records are candidates, not certified processes.

**No live ERP posting or finance baseline may be created by these examples.** Before any ZA posting, an independent legal/finance authority must verify Nabhold and establish a current `OperatingLegalActorMandate` for the exact role, activity, market and dates; the ERP provider must also verify a Finance-approved baseline, native mapping, accounting period and statutory capability. `INVOICE_ISSUER`, `ACCOUNTING_ENTITY`, `CONTRACTING_PARTY` and `SELLER_OF_RECORD` are separate responsibilities; none follows from another. The existing `order_to_cash.legal_actor_gate` remains an **opt-in adapter** until wired to every material iDempiere command path and certified.

Preserve historic transactions and their original identity maps. Do not rewrite previously posted legal attribution, and do not automatically use Nabhold for Uganda.

## ZuriBeans provisioning foundation

`modules/provisioning` now contains the first executable desired-state provisioning
slice required by the ZuriBeans go-live masterplan:

```text
Control Plane assignment
        ↓
validated ERPProvisioningRequest
        ↓
deterministic PLAN
        ↓
idempotent APPLY through an ERP adapter
        ↓
RECONCILE / readiness checks
        ↓
READY (activation remains a separate governed action)
```

The service deliberately does not select an `IsolationProfile`, `EngineInstance` or
`CapabilityBinding`. Those remain Control Plane decisions. It requires their canonical
IDs as inputs, rejects placeholders, persists operation and step evidence, and skips
completed steps on retry.

The production template is at
`config/provisioning/zuribeans.production.template.json`. It is intentionally not a
seed file. Its legal name, registration, finance approval, tax/localisation profiles,
warehouse codes and canonical IDs must be replaced with verified, approved values.
The Uganda and South Africa entries express market participation capabilities, not an
assumption that a separate legal entity exists in each country.

### Remaining activation dependencies

- Control Plane must supply authoritative Context, EngineInstance,
  IsolationProfile and ERP CapabilityBinding IDs.
- Finance must approve the legal-entity accounting baseline.
- Uganda and South Africa localisation profiles must be technically, legally and
  financially certified.
- A concrete `ProvisioningAdapter` must use the live iDempiere REST plugin and
  approved iDempiere processes/configuration packages.
- Canonical tenant/entity mappings and Release-1 master data must reconcile.
- The sell-side, buy-side and internal-trade golden paths must pass before ACTIVE.

No production activation should be inferred from a `READY` database row alone.
