# Governed provider support publication

Authority: ADR-SHARED-017 (capability catalogue and provider declaration), ADR-ERP-020 (conformance). This procedure prepares canonical
registration documents for `baobab-erp.idempiere`; it neither registers nor activates a provider (ERP-CAP-07).

## What ERP declares, and what that is not

`.baobab/capability-provider.yaml` states which canonical capabilities this engine's provider implements, with evidence in this repository.
It is **implementation evidence only**. It is not certification (EA-09), activation, a binding, a grant, health, tenant entitlement or
routing; those belong to the Control Plane and are established only by Control Plane runtime evidence, never by this file or by anything
generated from it. `IMPLEMENTED` is also the implementation axis only: today nothing has run against a live iDempiere
(`architecture/conformance.yaml`).

## Construction preflight

Use a clean Shared checkout at the exact `contracts.lock.yaml` commit (CI's `shared-conformance` job already has one):

```sh
python3 scripts/provider_publication.py --shared-checkout .shared-contracts
python3 scripts/provider_publication.py --shared-checkout .shared-contracts --require-registrable
```

The first command validates the catalogue and the declaration at the pin and reports what would be registered and what is excluded. The
second is the publication gate: exit 2 means a provider has no `IMPLEMENTED` canonical support. Exit 1 is invalid input, an unclean or
mismatched Shared checkout, or a declaration that fails validation. Only Shared's own generator emits the `EngineRegistration`, always
`DRAFT`; ERP keeps no schema of its own. `PARTIAL` and planned support never enter a generated document, and an empty list is not readiness.
A report marked `source_dirty` is local construction evidence and must not be used as a release receipt.

The same checks run as tests (`tests/conformance/test_provider_publication.py`) so a declaration that stops validating, a `PARTIAL` capability
that leaks into registration, or evidence that points at a file that does not exist fails the pull request.

Optional `--registration-export reviewed-registrations.json` compares a JSON array of previously reviewed `DRAFT` `EngineRegistration`
documents with what the declaration generates. A missing, additional, substituted or changed registration is drift (exit 2); an invalid,
duplicate or foreign document is exit 1. These are registration documents, not live `CapabilityProvider` resources: an `ACTIVE` resource is
not a valid export. The tool does not contact the Control Plane and says nothing about the export's freshness, live drift, binding
eligibility, health, certification or runtime readiness.

## Current state

| Capability | Declared | Registered as DRAFT |
|---|---|---|
| `inventory.availability.query` | `IMPLEMENTED` (contract major 1) | yes |
| `finance.order-consequence.process` | `PARTIAL`: the post-placement lifecycle (shipment, invoice, accounting) is not driven from canonical events, and nothing has run live | no |

Do not change `PARTIAL` to `IMPLEMENTED` to obtain a registration document. Promote it when the lifecycle stages are connected and proven;
the test `test_promoting_a_capability_to_implemented_is_what_publishes_it` shows the effect.

## What remains for registry convergence (owned elsewhere)

After construction eligibility, Control Plane owners must supply real provider and engine-instance ids, approved configuration and
security-domain references, the exact artifact digest and revision, scoped runtime profiles and governed binding inputs, through the Control
Plane's existing registration and changeset mechanisms. Registering `DRAFT` support does not authorise activation, grants, binding or
certification. Read the current authoritative Control Plane projection and resolution before dispatch; never substitute this offline report
for it or cache it as readiness. Live acceptance additionally needs independent maker/checker approval and a real consumer, which depends on
a live iDempiere run (ERP-CAP-03).
