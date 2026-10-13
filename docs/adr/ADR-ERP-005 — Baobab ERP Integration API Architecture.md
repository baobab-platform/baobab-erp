# ADR-ERP-005 — Baobab ERP Integration API Architecture

**Status:** Accepted  
**Decision class:** ERP / API / Integration / Contracts / Security / Interoperability  
**Scope:** `nabhold/baobab-erp`, `nabhold/baobab-cp`, `nabhold/shared`, consuming Baobab engines and digital estates  
**Parent ADRs:** ADR-ERP-001, ADR-ERP-002, ADR-ERP-003, ADR-ERP-004  
**Date:** 2026-09-02

---

# 1. Decision

The Baobab ERP Engine SHALL expose a versioned, contract-first integration API representing **ERP business capabilities**, not iDempiere database structures.

The public/internal platform contract SHALL therefore expose operations such as:

```text
purchase orders
supplier invoices
goods receipts
payments
business partners
inventory queries
accounting-status queries
```

rather than:

```text
C_Order
C_Invoice
C_Payment
M_InOut
C_BPartner
M_Product
AD_Client
AD_Org
```

The API SHALL sit behind the Baobab ERP Anti-Corruption Layer established in ADR-ERP-004.

Conceptually:

```text
Consumer
   │
   ▼
Baobab API Gateway / Service Boundary
   │
   ▼
Baobab ERP API
   │
   ▼
Context + Authorization
   │
   ▼
Canonical Mapping
   │
   ▼
ERP Application Service
   │
   ▼
iDempiere Process / Model
```

The governing principle is:

> **Consumers request ERP capabilities; they do not remotely operate iDempiere tables.**

---

# 2. Contract authority

Machine-readable ERP HTTP contracts SHALL be defined using OpenAPI.

The baseline SHALL be:

```text
OpenAPI 3.1.1
```

OpenAPI 3.1.1 provides a language-independent description of HTTP APIs and is suitable for documentation, client generation, server validation and contract testing.

The contract itself SHOULD reside under:

```text
nabhold/shared
```

where it represents an organisation-wide canonical contract.

The ERP repository SHALL implement that contract.

---

# 3. Contract ownership principle

The ownership relationship SHALL be:

```text
nabhold/shared
      │
      ├── canonical schemas
      ├── OpenAPI contracts
      ├── error taxonomy
      ├── Context definitions
      └── common identifiers

nabhold/baobab-erp
      │
      └── implementation
```

The ERP implementation SHALL NOT independently redefine canonical types already governed by `nabhold/shared`.

---

# 4. Contract-first development

A new external ERP capability SHOULD proceed:

```text
business requirement
       ↓
canonical resource semantics
       ↓
OpenAPI contract
       ↓
contract review
       ↓
application service
       ↓
iDempiere adapter
       ↓
implementation
```

not:

```text
write Java endpoint
       ↓
inspect whatever JSON appeared
       ↓
declare that the API
```

---

# 5. API boundary

Baobab SHALL distinguish:

```text
Canonical ERP API
```

from:

```text
Native iDempiere API
```

The canonical ERP API is the supported Baobab integration boundary.

Native iDempiere interfaces are implementation mechanisms.

Consumers SHALL NOT rely on native iDempiere endpoint stability.

---

# 6. API classes

The ERP Engine SHALL support three logical API classes:

```text
Command API
Query API
Administrative API
```

They SHALL have different security and operational expectations.

---

# 7. Command API

The Command API changes ERP state.

Examples:

```http
POST /erp/v1/purchase-orders
POST /erp/v1/purchase-orders/{id}/complete

POST /erp/v1/supplier-invoices
POST /erp/v1/supplier-invoices/{id}/post

POST /erp/v1/goods-receipts

POST /erp/v1/payments
POST /erp/v1/payments/{id}/allocate
```

Commands express business intent.

---

# 8. Query API

The Query API retrieves ERP state.

Examples:

```http
GET /erp/v1/purchase-orders/{id}
GET /erp/v1/supplier-invoices/{id}

GET /erp/v1/business-partners
GET /erp/v1/inventory

GET /erp/v1/account-balances
```

Query endpoints SHALL not introduce hidden mutations.

---

# 9. Administrative API

Administrative operations include:

```text
tenant provisioning
mapping diagnostics
reconciliation
engine health
integration diagnostics
controlled replay
```

These SHALL NOT share ordinary business authorization merely because they use HTTP.

Administrative APIs SHALL normally use separate routes, scopes and identities.

---

# 10. Resource-oriented URLs

API URLs SHALL use canonical business terminology.

Preferred:

```http
/erp/v1/purchase-orders
/erp/v1/supplier-invoices
/erp/v1/business-partners
```

Rejected:

```http
/erp/v1/c_order
/erp/v1/c_invoice
/erp/v1/c_bpartner
```

---

# 11. Versioning

Major API versions SHALL appear in the path:

```http
/erp/v1/...
```

A breaking contract change SHALL produce:

```http
/erp/v2/...
```

Minor additive evolution SHOULD normally occur without changing the major URL version.

---

# 12. What constitutes a breaking change

Examples include:

```text
removing a field
changing field semantics
changing identifier meaning
changing requiredness incompatibly
changing enum meaning incompatibly
changing monetary representation
changing successful response semantics
```

These require deliberate compatibility management.

---

# 13. Additive evolution

Normally non-breaking:

```text
adding optional response fields
adding new endpoints
adding optional query parameters
adding new event types
```

Consumers SHOULD be tolerant of unknown response fields.

---

# 14. API lifecycle

An API version SHOULD support:

```text
experimental
active
deprecated
retired
```

Deprecation SHALL precede removal.

---

# 15. Context is mandatory

Every tenant-scoped ERP request SHALL execute inside a resolved Baobab `Context`.

Relevant dimensions include:

```text
tenant_id
legal_entity_id
market_id
digital_estate_id where applicable
capability_id
engine_instance_id
principal
```

The consumer SHALL NOT directly select `AD_Client_ID`.

---

# 16. Trusted versus claimed Context

Request metadata MAY contain contextual claims.

Those claims are not automatically authoritative.

The trusted pipeline SHALL be:

```text
authenticated identity
      ↓
request context claims
      ↓
Control Plane / trusted Context validation
      ↓
CapabilityBinding
      ↓
EngineInstance
      ↓
Mapping
      ↓
native Client / Organization
```

---

# 17. Context headers

Where Context is transported through HTTP headers, Baobab SHOULD standardise names.

Conceptually:

```http
Baobab-Tenant-Id: <uuid>
Baobab-Legal-Entity-Id: <uuid>
Baobab-Market-Id: <uuid>
Baobab-Correlation-Id: <uuid>
```

However:

> Header presence is not authorization.

The values SHALL be authenticated/validated against the requesting principal.

---

# 18. Future signed Context

A future trusted gateway MAY issue a short-lived signed Context token.

Such token MAY contain:

```text
tenant
legal entity
market
capability
principal
expiry
audience
```

The ERP Engine SHALL verify signature, issuer, audience and expiry.

Unsigned consumer-generated Context tokens are prohibited.

---

# 19. Authentication

Machine-to-machine ERP integration SHALL use approved service authentication.

Permitted architecture may include:

```text
OAuth 2.x service credentials
signed workload identity
mTLS
cloud-native workload identity
```

depending on platform security standards.

Passwords tied to human ERP accounts SHALL NOT be the normal Baobab service-authentication mechanism.

---

# 20. Authorization

Authentication answers:

> Who is calling?

Authorization SHALL additionally determine:

```text
which Tenant?
which LegalEntity?
which Capability?
which operation?
which Market?
which resource?
```

---

# 21. Capability authorization

Scopes SHOULD resemble business capabilities.

Examples:

```text
erp.purchase-orders.read
erp.purchase-orders.write
erp.purchase-orders.complete

erp.supplier-invoices.read
erp.supplier-invoices.create
erp.supplier-invoices.post

erp.payments.read
erp.payments.create
erp.inventory.read
```

Avoid generic:

```text
erp.admin
```

for ordinary integrations.

---

# 22. Defense in depth

Authorization SHALL occur at multiple boundaries:

```text
gateway authorization
      +
Baobab ERP authorization
      +
resolved tenant/client enforcement
      +
native iDempiere security
```

Failure of one control SHALL not automatically expose another tenant.

---

# 23. Resource ownership

Every tenant-scoped resource lookup SHALL verify that the resource belongs to the resolved Context.

Thus:

```http
GET /erp/v1/supplier-invoices/{uuid}
```

does not mean:

> Fetch this UUID globally.

It means:

> Fetch this UUID within my authorised ERP Context.

---

# 24. Canonical identifiers

External identifiers SHALL use canonical Baobab IDs.

Preferred:

```json
{
  "id": "019...",
  "supplier_id": "019..."
}
```

Native iDempiere IDs SHALL remain internal.

---

# 25. External references

Where administrators genuinely need native-reference information, it MAY appear in controlled diagnostic responses:

```json
{
  "external_reference": {
    "engine": "idempiere",
    "type": "C_Invoice",
    "id": "1000421"
  }
}
```

Such references SHALL not become normal application identifiers.

---

# 26. Canonical entity lookup

ERP APIs SHOULD accept canonical IDs and resolve native mappings internally.

Example:

```http
POST /erp/v1/supplier-invoices
```

with:

```json
{
  "supplier_id": "<canonical-party-id>"
}
```

rather than requiring:

```json
{
  "c_bpartner_id": 1000123
}
```

---

# 27. Missing mapping

If a required canonical-to-native mapping does not exist:

```text
ERP_MAPPING_NOT_FOUND
```

SHALL be returned.

The command SHALL NOT silently create an unrelated mapping unless creation is explicitly part of that command's semantics.

---

# 28. Money representation

Money SHALL NOT use binary floating-point values.

Preferred representation:

```json
{
  "amount": "1250.50",
  "currency": "ZAR"
}
```

The amount SHALL be a decimal string or canonical decimal type described precisely in OpenAPI.

---

# 29. Currency codes

Canonical APIs SHALL represent currency with ISO 4217-style currency codes.

Examples:

```text
ZAR
UGX
KES
USD
EUR
```

Native `C_Currency_ID` SHALL remain internal.

---

# 30. Currency is explicit

A monetary amount SHALL not rely on ambient tenant currency where ambiguity exists.

This is insufficient:

```json
{
  "amount": "1000.00"
}
```

Preferred:

```json
{
  "amount": "1000.00",
  "currency": "UGX"
}
```

---

# 31. Different currency concepts

The API SHALL preserve distinctions among:

```text
document currency
accounting currency
price-list currency
settlement currency
reporting currency
```

when relevant.

It SHALL not collapse all into a single “tenant currency.”

---

# 32. Exchange-rate data

Where an API exposes exchange information it SHALL identify:

```text
source currency
target currency
rate
effective time/date
rate type
authority where relevant
```

External FX observations SHALL not automatically alter ERP accounting rates.

---

# 33. Quantity representation

Quantities SHALL use decimal-safe representation appropriate to the ERP domain.

Units of measure SHALL be explicit when ambiguous.

Example:

```json
{
  "quantity": "250.000",
  "uom": "KG"
}
```

---

# 34. Temporal representation

Timestamp fields SHALL use RFC 3339-compatible date-time strings in canonical contracts.

Examples:

```text
occurred_at
created_at
updated_at
posted_at
```

Timezone offsets SHALL not be silently discarded.

---

# 35. Dates versus timestamps

Pure business dates SHALL remain dates:

```text
document_date
accounting_date
due_date
```

Example:

```json
{
  "accounting_date": "2026-09-02"
}
```

They SHALL not be artificially converted to midnight UTC timestamps.

---

# 36. Accounting Date

`accounting_date` SHALL remain distinct from:

```text
created_at
document_date
posted_at
```

because the date affecting the general ledger has distinct business meaning.

---

# 37. Request correlation

Every request SHALL have a correlation identifier.

If a valid correlation ID is supplied by a trusted upstream caller, it SHOULD be propagated.

Otherwise ERP SHALL generate one.

Responses SHALL return it.

---

# 38. Idempotency

Retriable commands that create or irreversibly transition business resources SHALL support an idempotency key.

Recommended header:

```http
Idempotency-Key: <opaque-value>
```

The key SHALL be scoped at least by:

```text
Tenant
operation
```

---

# 39. Idempotent create

Example:

```http
POST /erp/v1/supplier-invoices
Idempotency-Key: 793...
```

If the first request succeeds but its response is lost, repeating the request SHALL return the existing result rather than creating a duplicate invoice.

---

# 40. Idempotency fingerprint

ERP SHOULD retain a fingerprint of the effective command.

If the same key is reused with materially different content:

```text
IDEMPOTENCY_CONFLICT
```

SHALL be returned.

---

# 41. Idempotency retention

The retention period SHALL be long enough to accommodate realistic retry windows.

Financial command idempotency SHOULD not use a trivially short expiration.

---

# 42. Optimistic concurrency

Where concurrent updates are relevant, resources SHOULD expose a revision/version.

Possible mechanisms include:

```text
ETag
version field
If-Match
```

The contract SHALL not use last-write-wins blindly for financially significant mutable state.

---

# 43. Commands versus CRUD

An ERP lifecycle is not generic CRUD.

For example:

```text
draft invoice
      ↓
validate
      ↓
post
```

SHALL be represented through business transitions.

Do not expose:

```http
PATCH /supplier-invoices/{id}
{
  "status": "posted"
}
```

---

# 44. State transition endpoints

Use:

```http
POST /erp/v1/supplier-invoices/{id}/post
```

or another explicitly defined command.

This allows iDempiere's native processing logic to run.

---

# 45. State machine

Resource contracts SHOULD expose stable canonical states.

Example:

```text
draft
completed
posted
voided
reversed
```

These need not correspond 1:1 with raw iDempiere document-status codes.

---

# 46. Native state translation

The Anti-Corruption Layer SHALL translate native statuses to canonical status.

Consumers SHALL not depend on internal two-character iDempiere codes.

---

# 47. Synchronous versus asynchronous operations

Simple operations MAY return synchronously.

Long-running or externally coordinated operations MAY return:

```http
202 Accepted
```

with an operation resource.

Example:

```json
{
  "operation_id": "<uuid>",
  "status": "pending"
}
```

---

# 48. Operation resource

Canonical asynchronous operations SHOULD support:

```http
GET /erp/v1/operations/{operation_id}
```

with:

```text
pending
running
succeeded
failed
cancelled
```

where cancellation is semantically valid.

---

# 49. `202 Accepted` semantics

Returning `202` SHALL mean:

> The command has been accepted for processing.

It SHALL NOT imply completion.

Consumers requiring completion SHOULD:

```text
poll operation resource
```

or consume:

```text
canonical completion event
```

---

# 50. Event preference

For cross-engine workflows, canonical events SHOULD be preferred over aggressive polling.

Example:

```text
command accepted
       ↓
ERP processes
       ↓
erp.supplier-invoice.posted.v1
```

---

# 51. Webhooks

Generic webhooks SHALL NOT replace Baobab's canonical event architecture.

Webhooks MAY be provided for external integrations that cannot consume Baobab's event transport.

They SHALL be treated as delivery adapters.

---

# 52. Webhook event semantics

Webhook payloads SHOULD use the same canonical event envelope where possible.

Thus:

```text
event contract
```

remains consistent regardless of transport.

---

# 53. Webhook signing

External webhooks SHALL be authenticated, normally through signed payloads or equivalent approved mechanisms.

Consumers SHALL be able to detect replay.

---

# 54. Webhook retries

Delivery SHALL use bounded retries.

HTTP `2xx` SHALL generally acknowledge successful delivery.

Failures SHALL become observable.

---

# 55. Pagination

Collection endpoints SHALL use one consistent pagination model.

For large/changing ERP datasets, cursor-based pagination SHOULD be preferred.

Example:

```http
GET /erp/v1/supplier-invoices?limit=100&cursor=...
```

---

# 56. Pagination response

Example:

```json
{
  "items": [],
  "page": {
    "next_cursor": "...",
    "has_more": true
  }
}
```

---

# 57. Offset pagination

Offset pagination MAY be permitted for small administrative datasets.

It SHOULD NOT be the default for large transactional datasets where inserts can cause unstable page boundaries.

---

# 58. Maximum page size

Every collection SHALL define a maximum page size.

Clients SHALL not request:

```text
all transactions ever
```

through one API request.

---

# 59. Filtering

Filters SHALL use canonical field semantics.

Example:

```http
GET /erp/v1/supplier-invoices?status=posted&currency=ZAR
```

Do not expose arbitrary SQL-like filters from iDempiere.

---

# 60. Filter allowlist

Only documented filter parameters SHALL be accepted.

The API SHALL NOT expose a generic database-expression language simply because the native ERP API supports powerful filtering.

---

# 61. Sorting

Documented sort fields SHALL be allowlisted.

Example:

```http
?sort=-document_date
```

Unsupported sort fields SHOULD produce validation errors.

---

# 62. Search

Free-text search MAY be provided for suitable resources.

It SHALL have bounded semantics and SHALL not become an unrestricted query interface over ERP tables.

---

# 63. Sparse fields

Selective field projection MAY be supported in later versions.

It SHALL NOT expose native columns dynamically.

---

# 64. Relationships

Canonical resources MAY include relationships using canonical IDs.

Example:

```json
{
  "supplier": {
    "id": "<canonical-party-id>"
  }
}
```

Avoid embedding entire related ERP records by default.

---

# 65. Expansion

Explicit expansion MAY be supported:

```http
?include=lines
```

but only for documented relationships.

The API SHALL control query complexity.

---

# 66. Purchase order contract

A purchase order SHOULD conceptually expose:

```text
id
tenant_id where appropriate
legal_entity_id
supplier_id
order_number
document_date
currency
status
lines
totals
created_at
updated_at
```

Native ERP implementation details remain hidden.

---

# 67. Supplier invoice contract

A supplier invoice SHOULD conceptually expose:

```text
id
supplier_id
invoice_number
document_date
accounting_date
currency
status
amounts
lines
purchase_order references
created_at
posted_at
```

---

# 68. Goods receipt contract

A goods receipt SHOULD expose canonical:

```text
receipt_id
supplier
warehouse/location
receipt_date
received lines
purchase-order references
status
```

not raw `M_InOut` structure.

---

# 69. Payment contract

A payment SHOULD clearly distinguish:

```text
payment amount
currency
payment date
counterparty
direction
allocation
status
```

Sensitive payment credentials SHALL never be exposed.

---

# 70. Business Partner contract

Canonical Party identity SHALL be preferred over forcing external consumers to adopt ERP's Business Partner identity.

ERP-specific attributes MAY appear in an ERP representation.

---

# 71. Product references

The ERP API SHALL use canonical product IDs where a product has platform identity.

This supports mappings such as:

```text
Canonical Product
    ├── Medusa Product
    └── iDempiere M_Product
```

without exposing either engine's identifier to the other.

---

# 72. Unknown canonical entity

If ERP receives a valid canonical entity with no ERP representation, the result depends on the command.

It MAY:

```text
create ERP representation
```

only if that operation explicitly owns synchronisation/provisioning semantics.

Otherwise:

```text
ERP_MAPPING_NOT_FOUND
```

---

# 73. Error standard

Error representations SHALL follow RFC 9457 Problem Details.

RFC 9457 defines a standard machine-readable error object using `application/problem+json` and obsoletes RFC 7807.

---

# 74. Core Problem Details fields

Responses SHOULD use:

```json
{
  "type": "https://api.baobab.example/problems/erp-accounting-period-closed",
  "title": "Accounting period is closed",
  "status": 409,
  "detail": "The invoice cannot be posted in the requested accounting period.",
  "instance": "...",
  "code": "ERP_ACCOUNTING_PERIOD_CLOSED",
  "correlation_id": "<uuid>"
}
```

Baobab-specific members such as `code` and `correlation_id` MAY be RFC 9457 extension members. RFC 9457 explicitly permits problem-type-specific extension members.

---

# 75. Error taxonomy

Stable codes SHALL include classes such as:

```text
ERP_MAPPING_NOT_FOUND
ERP_MAPPING_AMBIGUOUS
ERP_CONTEXT_INVALID
ERP_CONTEXT_MISMATCH
ERP_ACCESS_DENIED

ERP_VALIDATION_FAILED
ERP_RESOURCE_NOT_FOUND
ERP_STATE_CONFLICT
ERP_ACCOUNTING_PERIOD_CLOSED

ERP_IDEMPOTENCY_CONFLICT

ERP_ENGINE_UNAVAILABLE
ERP_DEPENDENCY_UNAVAILABLE
ERP_OPERATION_FAILED
```

---

# 76. HTTP status discipline

Examples:

```text
400 malformed request
401 unauthenticated
403 authenticated but unauthorized
404 resource absent in authorised scope
409 business/concurrency/state conflict
422 semantically invalid command where adopted consistently
429 throttled
500 unexpected server failure
503 temporary engine/dependency unavailable
```

The precise mapping SHALL be organisation-wide and consistent.

---

# 77. Security-sensitive 404

Where revealing that another tenant's resource exists would leak information, the API MAY return:

```http
404 Not Found
```

rather than exposing cross-tenant existence via `403`.

---

# 78. Validation errors

Validation Problem Details MAY include structured field errors.

Conceptually:

```json
{
  "code": "ERP_VALIDATION_FAILED",
  "errors": [
    {
      "pointer": "/lines/0/quantity",
      "code": "VALUE_REQUIRED"
    }
  ]
}
```

RFC 9457 permits extensions to the standard object for such API-specific information.

---

# 79. No raw native errors

The API SHALL NOT expose:

```text
Java stack traces
SQL statements
table names
database identifiers
OSGi internals
native authentication diagnostics
```

to ordinary clients.

---

# 80. Rate limiting

Rate limits SHALL support scope by:

```text
service identity
tenant
capability
endpoint class
```

Shared EngineInstances SHALL particularly protect against noisy consumers.

---

# 81. Rate-limit responses

Rate-limit exhaustion SHALL return:

```http
429 Too Many Requests
```

with suitable retry metadata where safe.

---

# 82. Timeouts

Every external request SHALL have bounded execution time.

ERP APIs SHALL NOT retain requests indefinitely while a downstream operation stalls.

---

# 83. Client cancellation

Where technically possible, cancelled HTTP requests SHOULD terminate unnecessary work.

However committed ERP transactions SHALL not be rolled back merely because the client disconnected after commit.

---

# 84. Retry semantics

Consumers MAY automatically retry:

```text
safe GET requests
transiently failed idempotent commands
```

They SHALL NOT blindly retry non-idempotent financial creates without an idempotency key.

---

# 85. Circuit breaking

Consumers/gateways SHOULD use circuit breaking for sustained ERP failures.

Circuit state SHOULD be scoped sufficiently to avoid one tenant unnecessarily disabling every tenant where possible.

---

# 86. Cacheability

Financial transactional resources SHALL not be publicly cached by default.

Read-only/reference resources MAY use controlled caching where semantics permit.

Authentication/tenant Context SHALL form part of cache safety.

---

# 87. ETag

Read resources MAY expose:

```http
ETag
```

for caching and/or optimistic concurrency.

ETags SHALL not leak sensitive implementation information.

---

# 88. API gateway

The canonical ERP API SHOULD be mediated through the platform's approved gateway boundary.

The gateway MAY provide:

```text
TLS termination
authentication
rate limiting
routing
request-size control
WAF policies
observability
```

It SHALL not contain ERP business logic.

---

# 89. Gateway versus Control Plane

The gateway routes network traffic.

The Control Plane resolves canonical capability topology.

These are different responsibilities.

---

# 90. Request-size limits

Endpoints SHALL define bounded payload limits.

Bulk imports SHALL use explicit bulk/import mechanisms rather than accepting arbitrarily large ordinary requests.

---

# 91. Bulk operations

Bulk ERP commands SHALL not merely accept a gigantic array through the single-resource endpoint.

Where needed, provide:

```text
bulk job
import resource
asynchronous operation
```

with per-item result reporting.

---

# 92. Partial success

Bulk APIs SHALL define partial-success semantics explicitly.

They SHALL not leave consumers guessing whether:

```text
all
some
none
```

were committed.

---

# 93. Atomic bulk operations

Atomicity across an entire bulk request SHALL only be promised where the ERP transaction model genuinely supports and requires it.

Otherwise per-item transaction semantics SHALL be explicit.

---

# 94. Audit metadata

Mutating operations SHALL capture appropriate actor information.

Examples:

```text
principal
service identity
correlation ID
source estate/system
```

This SHALL flow into native and/or platform audit where appropriate.

---

# 95. Source system

Commands MAY carry an authenticated source identifier such as:

```text
Trade Engine
Digital Estate
operator workflow
```

but source SHALL not replace principal identity or tenant Context.

---

# 96. MedusaJS integration boundary

The Trade Engine MAY call ERP only for approved capabilities.

Examples:

```text
retrieve ERP-relevant account state
create/confirm ERP financial representation
query availability where ERP is authoritative
```

But direct synchronous coupling SHOULD remain limited.

Order lifecycle integration SHOULD predominantly use canonical events where asynchronous consistency is acceptable.

---

# 97. Medusa SHALL not use native ERP IDs

Prohibited:

```text
Medusa order metadata:
    idempiere_invoice_id = 1000341
```

as the primary relationship.

Preferred:

```text
Canonical Invoice ID
```

with Control Plane mapping to native references.

---

# 98. Payload integration boundary

Payload CMS SHOULD normally have no direct ERP command authority.

Where content requires ERP-derived facts, use:

```text
approved read projection
API
canonical event projection
```

rather than native database access.

---

# 99. Digital Estate integration boundary

Customer-facing Digital Estates SHOULD consume the narrowest relevant capability.

They SHALL not receive generic access to ERP because the owning legal entity has ERP enabled.

Example:

```text
customer portal:
    invoice.read
```

does not imply:

```text
general-ledger.write
```

---

# 100. Internal versus external consumers

The same canonical model MAY support both internal and external APIs.

However external partner exposure SHALL normally use a narrower contract and additional gateway controls.

Internal APIs are not automatically safe to expose publicly.

---

# 101. API audience

Security tokens SHOULD include appropriate audience restrictions.

An identity intended for:

```text
Trade Engine → ERP
```

SHALL not automatically be valid for:

```text
ERP administrative API
```

---

# 102. OpenAPI structure

Recommended organisation:

```text
contracts/
└── erp/
    └── http/
        └── v1/
            ├── openapi.yaml
            ├── schemas/
            ├── parameters/
            ├── responses/
            └── examples/
```

under the canonical contracts repository.

---

# 103. Reusable schemas

Common schemas SHOULD include:

```text
UUID
Money
CurrencyCode
Date
DateTime
Problem
PaginationCursor
ResourceReference
CanonicalContext
```

These SHOULD be shared across engines where semantics are genuinely identical.

---

# 104. Do not over-generalise contracts

A single generic:

```text
BusinessDocument
```

SHALL not replace distinct:

```text
PurchaseOrder
SupplierInvoice
GoodsReceipt
Payment
```

where business semantics differ.

Canonicalisation does not mean erasing domain meaning.

---

# 105. API examples

OpenAPI contracts SHALL include representative examples.

Examples SHALL cover:

```text
happy path
validation error
authorization failure
mapping failure
idempotent replay
state conflict
multi-currency operation
```

---

# 106. Contract validation

CI SHALL validate:

```text
OpenAPI syntax
schema references
examples
breaking changes
implementation compatibility
```

---

# 107. Breaking-change detection

Pull requests modifying ERP contracts SHOULD run automated compatibility checks against the active released contract.

Unexpected breaking changes SHALL fail CI.

---

# 108. Generated clients

Consumers MAY generate clients from OpenAPI.

Generated clients SHALL not become the sole source of contract truth.

The OpenAPI document remains authoritative.

---

# 109. Server-side validation

The implementation SHOULD validate incoming payloads against equivalent schema constraints.

The server SHALL not assume generated clients guarantee valid input.

---

# 110. Consumer-driven contract tests

Important engine integrations MAY add consumer-driven compatibility tests.

Examples:

```text
Trade Engine → ERP
Control Plane → ERP
reconciliation service → ERP
```

These SHALL complement, not replace, the canonical OpenAPI contract.

---

# 111. API telemetry

Every endpoint SHALL provide metrics sufficient to monitor:

```text
request count
latency
success/failure
status class
rate limiting
authorization failures
idempotent replays
```

Tenant ID SHOULD not indiscriminately become a high-cardinality metric label.

---

# 112. Sensitive logging

Bodies SHALL not be logged indiscriminately.

Particularly sensitive:

```text
financial data
bank details
personal information
credentials
tokens
```

Log redaction SHALL be standard.

---

# 113. Trace context

Distributed trace context SHOULD propagate through:

```text
gateway
ERP API
application service
outbox publisher
event consumer
```

where observability infrastructure supports it.

---

# 114. API health endpoints

Health endpoints SHOULD be distinct from business APIs.

Example:

```http
/health/live
/health/ready
```

They SHALL expose no unnecessary tenant or infrastructure secrets.

---

# 115. Readiness

Readiness SHOULD reflect the EngineInstance's ability to perform required business operations.

Relevant checks MAY include:

```text
database connectivity
critical bundle status
mapping/context subsystem availability
```

---

# 116. API documentation

Human-readable API documentation MAY be generated from OpenAPI.

Production documentation SHALL distinguish:

```text
public partner APIs
internal platform APIs
administrative APIs
```

---

# 117. No generated native CRUD documentation as platform API

Documentation generated from iDempiere's generic model interface SHALL not be advertised as the Baobab ERP platform contract.

---

# 118. API deprecation

Deprecated operations SHOULD expose appropriate documentation and, where useful, standard HTTP deprecation signalling.

Consumers SHALL receive an actionable migration path.

---

# 119. API retirement

Before retirement:

```text
usage telemetry
consumer inventory
replacement availability
migration communication
```

SHALL be assessed.

---

# 120. Canonical API independence

A change from:

```text
iDempiere version N
```

to:

```text
iDempiere version N+1
```

SHALL not automatically alter the external API.

Likewise eventual ERP replacement should preserve compatible canonical contracts where the business semantics remain.

---

# 121. ERP replacement test

The architecture SHOULD pass this thought experiment:

> Could Baobab replace iDempiere without forcing Medusa, Payload and Digital Estates to rewrite all of their ERP integration semantics?

If the answer is no, native implementation details have leaked through the boundary.

---

# 122. Rejected alternative — expose iDempiere REST directly

**Rejected.**

It exposes native model/table/process semantics and makes iDempiere itself the organisation-wide API.

---

# 123. Rejected alternative — generic table CRUD gateway

**Rejected.**

ERP processes are business state machines, not generic records.

---

# 124. Rejected alternative — native IDs as API IDs

**Rejected.**

They are EngineInstance-specific and prevent transparent migration.

---

# 125. Rejected alternative — tenant selected by `AD_Client_ID`

**Rejected.**

The native Client is resolved from authenticated canonical Context.

---

# 126. Rejected alternative — currency inferred globally

**Rejected.**

Baobab is explicitly multi-market and multi-currency.

Monetary context must remain explicit.

---

# 127. Rejected alternative — floating-point money

**Rejected.**

Financial values require decimal-safe semantics.

---

# 128. Rejected alternative — custom proprietary error envelope

**Rejected.**

RFC 9457 already provides a standard extensible Problem Details format for HTTP APIs.

---

# 129. Rejected alternative — events only, no API

**Rejected.**

Some ERP capabilities require immediate authoritative responses and query semantics.

Baobab uses APIs and events according to interaction characteristics.

---

# 130. Rejected alternative — APIs only, no events

**Rejected.**

It would cause excessive synchronous coupling and polling between engines.

---

# 131. Rejected alternative — webhook as internal event bus

**Rejected.**

Webhooks are useful adapters for external consumers, not the canonical internal event architecture.

---

# 132. Rejected alternative — unbounded generic filtering

**Rejected.**

It exposes persistence internals, creates security risk and makes performance unpredictable.

---

# 133. Rejected alternative — one API token per company with unrestricted ERP permissions

**Rejected.**

Authorization SHALL be capability and operation specific.

---

# 134. Non-negotiable invariants

```text
INV-ERP-API-001
The Baobab ERP API exposes canonical business capabilities, not iDempiere tables.

INV-ERP-API-002
Native iDempiere REST is not the canonical platform contract.

INV-ERP-API-003
OpenAPI defines the HTTP contract.

INV-ERP-API-004
Canonical contracts are organisation-owned, not implementation-owned.

INV-ERP-API-005
External APIs use canonical IDs.

INV-ERP-API-006
AD_Client_ID and AD_Org_ID are never caller-controlled tenant authority.

INV-ERP-API-007
Every tenant-scoped request executes under validated Context.

INV-ERP-API-008
Authentication does not substitute for tenant authorization.

INV-ERP-API-009
Financial lifecycle transitions are business commands, not arbitrary status patches.

INV-ERP-API-010
Money uses decimal-safe representation.

INV-ERP-API-011
Currency is explicit wherever monetary ambiguity exists.

INV-ERP-API-012
Business dates remain distinct from timestamps.

INV-ERP-API-013
Accounting Date remains semantically distinct from document and creation dates.

INV-ERP-API-014
Retriable financial creates support idempotency.

INV-ERP-API-015
Idempotency keys are tenant/operation scoped.

INV-ERP-API-016
RFC 9457 Problem Details is the HTTP error representation.

INV-ERP-API-017
Native stack traces and SQL are not exposed externally.

INV-ERP-API-018
Collection endpoints are bounded and paginated.

INV-ERP-API-019
Generic native query languages are not exposed externally.

INV-ERP-API-020
Long-running operations do not pretend synchronous completion.

INV-ERP-API-021
Canonical events complement APIs rather than duplicate them indiscriminately.

INV-ERP-API-022
Webhooks are delivery adapters, not the internal canonical event architecture.

INV-ERP-API-023
Medusa cannot depend on iDempiere identifiers or tables.

INV-ERP-API-024
Payload cannot depend on iDempiere identifiers or tables.

INV-ERP-API-025
Digital Estates receive only explicitly bound ERP capabilities.

INV-ERP-API-026
API gateway infrastructure does not own ERP business logic.

INV-ERP-API-027
API version evolution is independent of upstream iDempiere release numbering.

INV-ERP-API-028
Contract changes are compatibility-tested.

INV-ERP-API-029
Canonical API behaviour survives EngineInstance relocation.

INV-ERP-API-030
The API remains replaceable with another ERP implementation without changing canonical identity.
```

---

# 135. Initial API surface

The initial production vertical slice SHOULD remain deliberately narrow.

Recommended initial resources:

```text
business-partners
products/references where ERP ownership requires them
purchase-orders
goods-receipts
supplier-invoices
payments
operations
```

Do not expose the whole ERP simply because iDempiere contains the functionality.

---

# 136. Initial command surface

Recommended:

```http
POST /erp/v1/purchase-orders
POST /erp/v1/purchase-orders/{id}/complete

POST /erp/v1/goods-receipts

POST /erp/v1/supplier-invoices
POST /erp/v1/supplier-invoices/{id}/post

POST /erp/v1/payments
```

---

# 137. Initial query surface

Recommended:

```http
GET /erp/v1/purchase-orders/{id}
GET /erp/v1/goods-receipts/{id}
GET /erp/v1/supplier-invoices/{id}
GET /erp/v1/payments/{id}

GET /erp/v1/business-partners/{id}
```

Collections SHALL be added only where a real consumer needs them.

---

# 138. Example complete command flow

```text
Trade Engine
    │
    │ POST /erp/v1/supplier-invoices
    │ Authorization
    │ Context
    │ Idempotency-Key
    ▼
ERP Gateway
    │
    ▼
Authentication
    │
    ▼
Context Validation
    │
    ▼
Capability Authorization
    │
    ▼
Canonical Mapping
    │
    ├── Tenant → AD_Client
    ├── Party → C_BPartner
    └── Product → M_Product
    │
    ▼
ERP Application Service
    │
    ▼
iDempiere Native Process
    │
    ├── ERP mutation
    └── outbox event
    │
    ▼
COMMIT
    │
    ├─────────────► API Response
    │
    ▼
Outbox Publisher
    │
    ▼
erp.supplier-invoice.posted.v1
```

This represents the intended boundary between synchronous authority and asynchronous propagation.

---

# 139. Multi-market example

The same API request can target:

```text
Tenant       = Thamani
LegalEntity  = Thamani
Market       = Uganda
Currency     = UGX
```

and resolve:

```text
CapabilityBinding
      ↓
ERP-AF-EAST-01
      ↓
AD_Client THAMANI
```

while:

```text
Tenant       = Thamani
Market       = South Africa
Currency     = ZAR
```

could resolve to:

```text
ERP-AF-SOUTH-01
```

without the API consumer selecting either server.

That is the practical value of canonical Context.

---

# 140. Definition of done

ADR-ERP-005 SHALL be considered implemented when:

- [ ] OpenAPI 3.1.1 contract exists for ERP v1.
- [ ] Contract ownership is established under the organisational shared-contract model.
- [ ] Native iDempiere APIs are not advertised as canonical Baobab APIs.
- [ ] URLs contain business-resource terminology.
- [ ] Major API versioning policy exists.
- [ ] Canonical IDs are used externally.
- [ ] Context transport and validation are defined.
- [ ] AD_Client and AD_Org are server-resolved.
- [ ] Capability-level authorization exists.
- [ ] Service authentication is distinct from native human login.
- [ ] Money and currency schemas are standardised.
- [ ] Date and timestamp conventions are standardised.
- [ ] Idempotency is implemented for financial create/transition commands.
- [ ] Problem responses comply with RFC 9457.
- [ ] Stable Baobab error codes exist.
- [ ] Pagination strategy is defined.
- [ ] Filtering and sorting are allowlisted.
- [ ] Long-running operations have operation resources.
- [ ] API and canonical event interactions are documented.
- [ ] Webhook behaviour is explicitly secondary to canonical events.
- [ ] API rate limits exist.
- [ ] Logging redacts sensitive data.
- [ ] Correlation IDs propagate end-to-end.
- [ ] OpenAPI compatibility checks run in CI.
- [ ] Consumer integration tests exist.
- [ ] Medusa integration uses canonical IDs.
- [ ] Digital Estates cannot access unrestricted ERP APIs.
- [ ] EngineInstance relocation requires no consumer endpoint rewrite.
- [ ] No iDempiere primary key is part of a required external contract.

---

# 141. Final architecture

```text
                CONSUMING SYSTEM

       Medusa / Estate / Service / Partner
                       │
                       │ canonical HTTP
                       ▼
                API GATEWAY
                       │
              auth / throttling
                       │
                       ▼
                BAOBAB ERP API
                       │
              ┌────────┴────────┐
              │                 │
           Context          Authorization
              │                 │
              └────────┬────────┘
                       ▼
              Mapping Resolver
                       │
                       ▼
             Application Service
                       │
                       ▼
                iDempiere
                       │
               Local Transaction
                │             │
                ▼             ▼
             ERP State      Outbox
                              │
                              ▼
                        Canonical Event
```

---

# 142. Governing statement

The ERP API SHALL enforce this distinction:

```text
CANONICAL WORLD

Tenant
LegalEntity
Market
Party
Product
PurchaseOrder
SupplierInvoice
Payment
Money
Context

            │
            │ Anti-Corruption Layer
            ▼

iDEMPIERE WORLD

AD_Client
AD_Org
C_BPartner
M_Product
C_Order
C_Invoice
C_Payment
```

The API is not merely a network wrapper around the second world.

It is the contractual boundary protecting the first world from it.

Therefore the definitive rule is:

> **Baobab integrations shall depend on ERP business semantics, never on iDempiere implementation semantics.**

That rule gives the platform three important freedoms simultaneously:

1. iDempiere can evolve and be upgraded independently.
2. tenants can migrate among EngineInstances and regions without changing consumers.
3. iDempiere can eventually be replaced without forcing the rest of Baobab to adopt a new identity model.

That is the level of decoupling expected of the Baobab ERP Engine.
## Implementation follow-up — P0-04A (13 October 2026)

The canonical repository is now `baobab-platform/shared`. ERP consumes the
reviewed immutable lock with generated byte-identical authority schemas in both
Python and native JVM resources. Validators enforce wire shape before separate
current-scope, finance/provider and attribution checks. See the
[maintenance plan](../plans/P0-04A-erp-contract-convergence.md). This note records
implementation progress without rewriting the accepted decision or claiming
protected execution certification.
