# P0-04A — ERP contract convergence

## Audit and scope (13 October 2026)

The programme owner is CP's `docs/reconciliation/adr026-027-completion-plan-2026-10-12.md`.
Trade's code slice is merged in #145. This is the ERP slice; Payments,
Subscriptions and Trade Docs follow in that order, each in its owning repository.
P0-03 genuine founding/control/mandate acceptance and P0-04B protected native
execution acceptance remain separate.

Audited baselines: ERP initially `b7ee0894e03a6a3ac9af4161838542f47779eecf`,
then `0b412844f01b6a01c924bea438364282edf90d28` after dependency PR review;
Shared `a9c53087d63caa356edf54ec8037ba1713c4827f`; CP
`05cad8e1e0f6594de0b4978edc57b7463068867a`; IAM
`ad7989ca085831303c265f943ef2b97735f911ad`. CP/IAM had no open PRs. Shared's
#290–294 are independent dependency PRs and do not require a contract pin bump.

ERP #89–94 were inspected for diffs, review threads, complete final-head checks
and workflows, and full REST mergeability. All were clean/green and merged:
artifact upload, Python setup, action pinning, Foundation, CodeQL and the Maven
build-stage image. The Java 27 builder change leaves native `--release 17` and
the iDempiere 13 runtime unchanged; artifact checks enforce our class-file target.
No CI waiver or exception extension was introduced.

Historical LA-05D6/7 branches retain preceding or parallel work; their current
main diffs also remove later JVM/attribution guards. Do not merge old bases
wholesale. Current LA-05D9 protection is retained. Native context/readiness
providers and customer/native execution acceptance remain P0-04B work.

## Decisions and primary research

ERP ADR-005 contract ownership and temporal representation, ADR-008 finance
ownership, ADR-010 isolation, ADR-020 sections 57–62 contract assurance, and
CP ADR-BCP-026/027 govern the boundaries. Shared owns wire schemas; ERP owns
native financial readiness and atomic attribution, not legal verification.

Primary implementation references:

- [Python jsonschema resource registries](https://python-jsonschema.readthedocs.io/en/stable/referencing/): fixed packaged resources, no HTTP retrieval.
- [Networknt 2.0.4 source and usage](https://github.com/networknt/json-schema-validator/tree/2.0.4): Draft 2020-12 and explicit format assertions.
- [Networknt OSGi resource-loading issue](https://github.com/networknt/json-schema-validator/issues/1264): bundle-local TCCL during load/validation, always restored.
- [Maven Shade relocation](https://maven.apache.org/plugins/maven-shade-plugin/examples/class-relocation.html) and [service-resource transformation](https://maven.apache.org/plugins/maven-shade-plugin/examples/resource-transformers.html): private dependencies without iDempiere Jackson wiring conflicts.
- [Java 17 response subscribers](https://docs.oracle.com/en/java/javase/17/docs/api/java.net.http/java/net/http/HttpResponse.BodyHandlers.html) and [bounded future waits](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/concurrent/CompletableFuture.html): bounded body retention and a complete-response deadline.

The validator uses Networknt 2.0.4 and the already reviewed Jackson 2.22.3 line,
with private relocation of validator/Jackson/time/logging packages. YAML parsing
is excluded from the JVM dependency; schema bytes are JSON. The public bundle
API exposes JDK types. No core iDempiere code is modified.

## Reviewed pin delta

The pin advances from `9e6e40739914b37465a7aa5ff463797d3c82d1cd` to
`a9c53087d63caa356edf54ec8037ba1713c4827f`. Six previously declared files changed:

| Path | Compatibility assessment |
|---|---|
| `control-plane/v1/openapi.yaml` | Additive CP development; ERP's existing context/assignment operations and independent purpose checks remain. |
| `control-plane/v1/examples/erp-assignment.json` | Synthetic reference data; does not establish a real company or approved plan. |
| `admission/v1/application.schema.json` | Reviewed admission definitions in the assignment reference closure; positive/negative compatibility checked at the exact pin. |
| `erp/v1/finance-baseline.schema.json` | Synthetic baseline example correction; finance ownership and approval requirements remain. |
| `events/v1/signed-delivery.schema.json` | Added ingress metric vocabularies; sender payload/signature rules remain compatible. ERP does not claim CP's metrics. |
| `events/v1/event-registry.yaml` | New owner registrations; existing ERP-produced/consumed events remain checked against the owner. |

The lock now declares the actual legal-actor/documentary consumers, their
transitive reference closure, and workload/scope admission vocabulary. Canonical
stored Context identifiers use the owned domain UUID definition even though the
legacy assessment wire shape admits a general string handle.

## Implementation and maintenance

`sync_authority_contracts.py` reads immutable Git blobs at the exact lock pin,
walks all file references, rejects remote/absolute/undeclared references and
checks entry definitions before writing. It replaces generated directories,
removing obsolete schemas. `--check` compares full bytes and inventory.

The same 17 schemas and hash/entry-point provenance are packaged in:

- Python: `modules/shared_contracts/data/` (explicit wheel package data).
- JVM: integration bundle `src/main/resources/shared-contracts/`.

Nine cached entry validators cover legal and documentary request/response,
context resolve/validation, ERP assignment and the stored-context UUID grammar.
Python uses a closed `referencing.Registry` with format-enforcing production
dependencies. The JVM uses a local-only registry, strict duplicate/UTF-8/trailing
JSON checks and private shaded dependencies. Neither coerces values, removes
unknown fields or fetches a schema at runtime.

Python legal/documentary ports and the consequential financial gates validate
before native provider/mutation calls, including injected assessors. Existing
actor, operation, scope, freshness, negative-only veto and provider checks still
apply. Assignment parsing retains existing closed-member/time/uniqueness
diagnostics and adds canonical scalar validation. Caller-context validation
retains current purpose/plan/owner/time checks. Assignment transport now refuses
redirects and duplicate/oversized facts; legal transport also refuses redirects.

Native `CpNativeFinancialAuthority` validates actual requests and responses.
A bounded subscriber retains at most 16 KiB; the complete HTTP response has an
explicit three-second deadline, cancellation and interrupt restoration. Request
headers alone cannot complete a partial-body fact. Existing native actor/scope,
provider checks, double refresh and same-transaction attribution remain required.

Regeneration and checks (use a clean Shared checkout at the exact pin):

```bash
python -m pip install -e 'modules[conformance]'
python scripts/sync_authority_contracts.py --shared-checkout ../shared
python scripts/sync_authority_contracts.py --shared-checkout ../shared --check
PYTHONPATH=modules python -m unittest discover -s tests/unit -p 'test_*.py'
./mvnw -B -f idempiere/extensions package
python scripts/verify_contract_artifacts.py --jar idempiere/extensions/org.nabhold.baobab.erp.integration/target/org.nabhold.baobab.erp.integration-0.1.0.jar
# Full conformance additionally requires a migrated disposable PostgreSQL database.
PYTHONPATH=modules:tests/conformance BAOBAB_SHARED_PATH=../shared python -m unittest discover -s tests/conformance -p 'test_*.py'
```

Update lock, generated bundles, `uv.lock`, vectors and documentation together.
The wire vectors are synthetic and independently checked by Shared and Python,
then JVM tests and standalone-JAR probes. CI also builds/installs a real wheel
without editable source or conformance extras and checks both artifact byte
inventories. The JAR probe uses a platform-only parent loader with invisible
caller TCCL. This is packaging proof, not full Equinox/native certification.

## Validation and acceptance limits

Local Python unit, offline conformance, security, tenancy, architecture and
available golden checks passed, including format failures, missing/type-invalid
fields, invented grants, finite denials, injected-port rejection and independent
scope/actor/freshness denials. A real standalone wheel passed the wire vectors.
Stale-file regeneration was exercised. The local executor cannot resolve Maven
Central and has a JRE without javac, or a usable database/socket service; hosted
Java/JAR/image/PostgreSQL/HTTP tests are mandatory before merge. Existing missing
legacy golden datasets remain recorded skips; no new skips are introduced.

`baobab-erp-legal-actor-assessor-staging` has all three assessment/context scopes
but remains PROVISIONED. The ACTIVE production workload lacks both private
assessment scopes. This PR activates neither profile and grants no scopes.
Trusted native context/readiness OSGi providers, protected company/finance
baselines, actual issuer/market/maker-checker evidence, native commit/rollback
and UI/import/scheduler/direct-SQL bypass acceptance remain independently open.
Schema-valid synthetic facts cannot satisfy those gates.

Next owning engine: Payments contract convergence, then Subscriptions and Trade Docs.
