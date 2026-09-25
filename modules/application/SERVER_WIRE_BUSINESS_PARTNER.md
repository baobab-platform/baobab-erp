# Wire `POST /business-partners/project` into `server.py`

ADR-ERP-021. Apply these three edits to `modules/application/server.py`.

## 1. Imports (after `integration.idempiere_client`)

```python
from application.business_partner_http import execute_project
from integration.business_partner_adapter import BusinessPartnerProjectionError
from provisioning.master_data_mapping import PostgresMasterDataMappingStore
```

## 2. `_WORKLOAD_REQUIRED_SCOPES`

```python
"/business-partners/project": "erp:integrate",
```

## 3. `_route_post` handlers dict

```python
"/business-partners/project": self._handle_project_business_partner,
```

## 4. Handler method (next to other `_handle_*` POST handlers)

```python
def _handle_project_business_partner(self, body: dict) -> None:
    """ADR-ERP-021 — readiness-gated Business Partner projection."""
    required_ctx = ("tenant_id", "entity_id")
    missing_ctx = [n for n in required_ctx if n not in body]
    if missing_ctx:
        self._send_json(400, {"error": f"missing required fields: {', '.join(missing_ctx)}"})
        return

    with psycopg.connect(config.database_url) as connection:
        scope = self._resolve_tenant_scope(connection, body)
        if scope is None:
            return
        credentials = config.idempiere_credentials_by_ad_client.get(scope.ad_client_id)
        if credentials is None:
            self._send_json(
                503,
                {
                    "error": (
                        "iDempiere client is not configured for this AD_Client; "
                        "Business Partner projection is unavailable"
                    )
                },
            )
            return
        client = RestIdempiereClient(credentials)
        mappings = PostgresMasterDataMappingStore(connection)
        project_body = {**body, "legal_entity_id": body["entity_id"]}
        try:
            result = execute_project(project_body, client=client, mappings=mappings)
        except BusinessPartnerProjectionError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except IdempiereClientError as exc:
            self._send_json(503, {"error": str(exc)})
            return

    self._send_json(200, result)
```

Request body (estate):

```json
{
  "tenant_id": "…",
  "entity_id": "…",
  "engine_instance_id": "erp-zuribeans",
  "canonical_organisation_id": "…",
  "display_name": "…",
  "readiness_status": "READY",
  "roles": ["supplier"],
  "billing_country": "UG"
}
```

Auth: workload bearer with `erp:integrate`. Response: Shared `business_partner` projection (`erp_*` id only).
