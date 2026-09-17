"""Release-1 ZuriBeans legal-entity policy.

Zuribeans_ZA and Zuribeans_UG are distinct canonical LegalEntities. Market identity
must never be used as a substitute for LegalEntity identity.
"""
ZURIBEANS_ZA = "Zuribeans_ZA"
ZURIBEANS_UG = "Zuribeans_UG"
SUPPORTED = frozenset({ZURIBEANS_ZA, ZURIBEANS_UG})

def require_supported_legal_entity(code: str) -> str:
    if code not in SUPPORTED:
        raise ValueError(f"unsupported ZuriBeans Release-1 legal entity: {code}")
    return code
