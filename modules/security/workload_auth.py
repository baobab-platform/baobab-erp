from typing import Protocol

import jwt

from identity.service import ServiceIdentity
from mapping import identifiers


class TokenValidationError(Exception):
    """Raised for any bearer token that must not be trusted."""


class SigningKeyResolver(Protocol):
    """Resolves the public key a token's signature was produced with. A real
    implementation fetches Baobab IAM's JWKS (security.jwks.JwksSigningKeyResolver);
    tests supply a fixed key.
    """

    def resolve(self, token: str) -> str | bytes: ...


def verify_workload_token(
    authorization_header: str | None,
    *,
    issuer: str,
    audience: str,
    key_resolver: SigningKeyResolver,
) -> ServiceIdentity:
    """Validate a Baobab IAM-issued workload bearer token, or raise
    TokenValidationError. Never guesses: a missing header, bad signature, wrong
    issuer/audience, expired token, or a token whose actor_type isn't "workload" are
    all rejected identically from the caller's point of view (application/server.py
    maps every case to a 401), so this never distinguishes "malformed" from
    "untrusted" in a way that would help an attacker calibrate an attempt.

    Replaces the network-level-trust-only gap on /context/resolve* and
    /mapping/resolve* (ADR-0014 §111, ADR-ERP-010).
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise TokenValidationError("Missing bearer token")
    token = authorization_header.removeprefix("Bearer ").strip()
    if not token:
        raise TokenValidationError("Missing bearer token")

    try:
        signing_key = key_resolver.resolve(token)
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
        )
    except jwt.PyJWTError as exc:
        raise TokenValidationError(f"Invalid token: {exc}") from exc

    if claims.get("actor_type") != "workload":
        raise TokenValidationError("Token is not a workload credential")

    principal = claims.get("azp") or claims.get("sub")
    if not principal:
        raise TokenValidationError("Token has no azp/sub principal")

    scope = claims.get("scope", "")
    roles = frozenset(scope.split()) if scope else frozenset()
    tenant_claim = claims.get("tenant_id")
    if tenant_claim is not None:
        try:
            identifiers.tenant_id(tenant_claim)
        except identifiers.IdentifierError as exc:
            raise TokenValidationError("Token tenant_id claim is not a canonical tenant identifier") from exc
    return ServiceIdentity(principal=principal, roles=roles, tenant_id=tenant_claim)
