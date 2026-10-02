from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    """An authenticated caller of the Baobab ERP integration boundary.

    Authentication itself (credential verification, token issuance) is not this
    module's concern; it belongs to the approved platform identity provider. This
    module only carries the already-authenticated principal and its narrow role set
    into the application layer, per ADR-ERP-010.
    """

    principal: str
    roles: frozenset[str]
    tenant_id: str | None = None
    """The resolved tenant claim, when the token carries one. Authoritative: a request-supplied
    tenant_id must never override it (contracts/erp/v1/openapi.yaml, workloadOidc)."""

    def has_role(self, role: str) -> bool:
        return role in self.roles
