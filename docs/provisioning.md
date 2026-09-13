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
