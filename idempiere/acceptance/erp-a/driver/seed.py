"""ERP-A harness seeding of the REAL Control Plane: tenant, market, the
baobab-erp engine instance and its binding, and the legal-actor mandate the
ERP posting-authority resolver decides from.

CP is seeded through its own admin API wherever one exists (tenant bootstrap
and activation, market create and four-eyes activation, mandate propose,
decide and activate by three distinct humans, mandate revocation). Where CP
has no admin API the row is inserted directly and recorded as SYNTHETIC in the
evidence:
  - the human identities (IAM user provisioning),
  - the legal-entity verification (an independent legal registry),
  - the tenant's market assignment (tenant provisioning),
  - the baobab-erp engine instance and its capability binding.
(Adapted from the Payments Gate D1 harness, baobab-payments acceptance/gate-d1.)
"""
from __future__ import annotations

import time
import uuid

from erpalib import CP, ISSUER, Compose, call, key

ISS = "https://iam.gated.test/realms/baobab"
LEGAL_ENTITY = "LE-ERPAUS"
MARKET = "US"
CURRENCY = "USD"
ADMIN_SCOPES = ["tenant:bootstrap", "tenant:write", "market:write", "market:approve",
                "legal-actor-mandate:propose", "legal-actor-mandate:decide",
                "legal-actor-mandate:activate", "legal-actor-mandate:terminate"]
# ADR-SHARED-037: the five purchase-side and vendor-payment recording classes.
PURCHASE = {"roles": ["CONTRACTING_PARTY", "ACCOUNTING_ENTITY"],
            "activities": ["PURCHASE_ORDER_COMMITMENT", "GOODS_RECEIPT", "VENDOR_INVOICE_RECORDING",
                           "VENDOR_PAYMENT_RECORDING", "PAYABLES_ALLOCATION"]}
# A narrower mandate: commitments and receipts only, no payables recording.
CONTRACTING_ONLY = {"roles": ["CONTRACTING_PARTY"],
                    "activities": ["PURCHASE_ORDER_COMMITMENT", "GOODS_RECEIPT"]}


def must(response, *ok: int):
    if response.status not in ok:
        raise RuntimeError(f"unexpected answer {response!r}")
    return response.body


def human_token(subject: str) -> str:
    return must(call("POST", ISSUER + "/_mint", {
        "subject": subject, "audience": "baobab-control-plane-admin", "scopes": ADMIN_SCOPES,
        "actor_type": "human", "roles": ["cp:platform-admin"]}), 200)["access_token"]


class ControlPlane:
    def __init__(self, compose: Compose, evidence):
        self.c, self.evidence = compose, evidence
        self.maker, self.checker, self.operator = (str(uuid.uuid4()) for _ in range(3))

    def sql(self, statement: str, label: str):
        self.evidence.note("synthetic-cp-seed", {"label": label})
        return self.c.sql("cpdb", "controlplane", "controlplane", statement)

    def scalar(self, statement: str) -> str:
        return self.c.scalar("cpdb", "controlplane", "controlplane", statement)

    def admin(self, method: str, path: str, who: str, body=None, headers=None, ok=(200, 201, 202)):
        h = {"Authorization": "Bearer " + human_token(who), **(headers or {})}
        return must(call(method, CP + path, body, h), *ok)

    def seed(self) -> dict:
        humans = ", ".join(f"('{p}','human','ACTIVE')" for p in (self.maker, self.checker, self.operator))
        links = ", ".join(f"('{p}','{ISS}','{p}','ACTIVE')" for p in (self.maker, self.checker, self.operator))
        self.sql(f"INSERT INTO identity.principal (principal_id, actor_type, status) VALUES {humans};"
                 f"INSERT INTO identity.external_identity (principal_id, issuer, subject, status) VALUES {links}",
                 "three human administrators (IAM user provisioning)")

        registration = self.admin("POST", "/v1/tenants/bootstrap-registrations", self.maker, {
            "legal_entity_id": LEGAL_ENTITY, "display_name": "ERP-A Synthetic Buyer Inc",
            "isolation_strategy": "row_level_security", "residency_region": "us-east-1",
            "bootstrap_reason": "EA-R03 ERP-A synthetic buyer for engine-local purchase-side acceptance",
            "evidence_reference": "erp-a/synthetic-registration"},
            {"Idempotency-Key": key()})
        self.tenant = registration["tenant_id"]
        self.organisation = ""
        for _ in range(60):
            self.organisation = self.scalar(
                "SELECT organisation_id FROM registry.tenant_organisation_mapping "
                f"WHERE tenant_id='{self.tenant}' AND mapping_role='PRIMARY_ORGANISATION' AND status='ACTIVE'")
            if self.organisation:
                break
            time.sleep(1)
        if not self.organisation:
            raise RuntimeError(f"tenant registration did not complete: {registration}")
        self.admin("POST", f"/v1/tenants/{self.tenant}/activate", self.maker)

        frm = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        created = call("POST", CP + "/v1/markets", {
            "canonical_key": "us.gate.erpa", "name": "United States (ERP-A)", "owner_tenant_id": self.tenant,
            "market_type": "MARKETPLACE", "default_country": MARKET, "default_currency": CURRENCY,
            "default_locale": "en-US", "timezone": "America/New_York", "effective_from": frm},
            {"Authorization": "Bearer " + human_token(self.maker), "Idempotency-Key": key()})
        must(created, 201)
        market_id = created.body["market_id"]
        self.admin("POST", f"/v1/markets/{market_id}/activate", self.checker, {},
                   {"If-Match": created.headers.get("etag", '"1"')})
        self.sql(f"""INSERT INTO market.market_assignment (tenant_id, market_id, status, source, policy_version,
                       effective_from)
                     SELECT '{self.tenant}', m.market_id, 'ACTIVE', 'PROVISIONING', '1', now() - interval '1 hour'
                       FROM market.market m WHERE m.code = '{MARKET}' AND m.is_active;
                     INSERT INTO market.market_participation_capability (market_assignment_id, capability)
                     SELECT market_assignment_id, 'PROCUREMENT' FROM market.market_assignment WHERE tenant_id='{self.tenant}'""",
                 "tenant market assignment (tenant provisioning has no admin API)")

        self.sql(f"""UPDATE registry.legal_entity_profile
                        SET verification_state='VERIFIED', legal_status='ACTIVE',
                            source_authority='synthetic-independent-legal-registry',
                            evidence_references='["erp-a/synthetic-legal-registry"]'::jsonb,
                            verified_by='{self.checker}', verified_at=clock_timestamp() - interval '1 minute',
                            updated_at=clock_timestamp()
                      WHERE legal_entity_id='{LEGAL_ENTITY}'""",
                 "legal-entity verification (an independent legal registry)")

        self.engine_instance = self.scalar(f"""
            WITH e AS (
              INSERT INTO topology.engine (code, name) VALUES ('baobab-erp', 'Baobab ERP')
              ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name RETURNING engine_id),
            i AS (
              INSERT INTO topology.engine_instance (engine_id, region, environment, status)
              SELECT engine_id, 'us-east-1', 'integration', 'ACTIVE' FROM e
              RETURNING engine_instance_id, engine_id, engine_instance_key),
            c AS (
              INSERT INTO capability.capability (code, name) VALUES ('erp.erp-a', 'ERP-A finance recording')
              RETURNING capability_id),
            s AS (INSERT INTO capability.capability_scope (tenant_id) VALUES ('{self.tenant}') RETURNING scope_id),
            p AS (
              INSERT INTO capability.capability_provider (provider_key, name, provider_type, engine_id, status)
              SELECT 'erp-a.erp', 'ERP-A iDempiere', 'BAOBAB_ENGINE', engine_id, 'ACTIVE' FROM e
              RETURNING provider_id),
            b AS (
              INSERT INTO capability.capability_binding (capability_id, engine_instance_id, scope_id, binding_mode,
                  status, contract_version, effective_from, provider_id)
              SELECT c.capability_id, i.engine_instance_id, s.scope_id, 'PRIMARY', 'ACTIVE', '1',
                     now() - interval '1 hour', p.provider_id FROM c, i, s, p)
            SELECT engine_instance_key FROM i""")
        self.evidence.note("synthetic-cp-seed", {"label": "baobab-erp engine instance and binding",
                                                 "engine_instance_key": self.engine_instance})
        self.mandate = self.propose(PURCHASE, "erp-a/mandate-purchase")
        self.evidence.note("cp", {"tenant_id": self.tenant, "organisation_id": self.organisation,
                                  "legal_entity_id": LEGAL_ENTITY, "market_id": market_id,
                                  "mandate_id": self.mandate, "engine_instance_key": self.engine_instance})
        return {"tenant": self.tenant, "organisation": self.organisation, "engine_instance": self.engine_instance,
                "legal_entity": LEGAL_ENTITY, "market": MARKET}

    def propose(self, scope: dict, evidence: str) -> str:
        """Propose (maker), approve (checker) and activate (operator) one mandate.
        capability_scope is omitted: the ERP catalogue's classes name no
        capability key, which matches only an unrestricted mandate."""
        frm = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300))
        proposed = self.admin("POST", "/v2/legal-actor-mandates", self.maker, {
            "tenant_id": self.tenant, "operating_organisation_id": self.organisation,
            "responsible_legal_entity_id": LEGAL_ENTITY, "roles": scope["roles"],
            "activity_scope": scope["activities"], "market_scope": [MARKET],
            "authority_basis_reference": "erp-a/board-resolution", "evidence_references": [evidence],
            "effective_from": frm}, {"Idempotency-Key": key()})
        mandate = proposed["mandate_id"]
        self.admin("POST", f"/v2/legal-actor-mandates/{mandate}/decision", self.checker, {
            "decision": "APPROVE", "decision_basis_reference": "erp-a/four-eyes-review",
            "evidence_references": [evidence],
            "legal_actor_verification_reference": "erp-a/synthetic-legal-registry"},
            {"Idempotency-Key": key()})
        self.admin("POST", f"/v2/legal-actor-mandates/{mandate}/activate", self.operator, {
            "action": "ACTIVATE", "authority_basis_reference": "erp-a/activation",
            "evidence_references": [evidence]}, {"Idempotency-Key": key()})
        return mandate

    def revoke(self, mandate: str) -> None:
        self.admin("POST", f"/v2/legal-actor-mandates/{mandate}/terminate", self.operator, {
            "action": "REVOKE", "authority_basis_reference": "erp-a/revocation",
            "evidence_references": ["erp-a/revocation-evidence"]}, {"Idempotency-Key": key()})

    def decisions(self, reference_like: str = "%") -> list[list[str]]:
        """CP's immutable posting-authority decision history (CP #402)."""
        return self.c.sql("cpdb", "controlplane", "controlplane",
                          "SELECT decision_id, operation_class, outcome, operation_reference "
                          "FROM registry.erp_posting_authority_decision "
                          f"WHERE operation_reference LIKE '{reference_like}' ORDER BY evaluated_at")
