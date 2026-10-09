# LA-05D2 — authenticated ERP Control Plane legal-actor assessment client

Companion to the merged LA-05D financial command PEP (ERP #78).

`HttpControlPlaneLegalActorAssessor` implements the `LegalActorAssessor` port with an authenticated workload-token provider for `POST /internal/legal-actor/v1/assess`. It accepts exactly the Shared LA-05A operation request keys, never tenant, Organisation or responsible LegalEntity selection. It transmits no cacheable bearer authority; imposes bounded timeouts/response lengths and rejects non-TLS origins except local development. CP derives current runtime principal ownership, PRIMARY operating Organisation, actor verification and mandate.

The token issuer must explicitly grant the `legal-actor:assess` scope to **the same canonical ERP workload that owns the context ID** (along with `context:resolve`); the scope remains unassigned in IAM until governed staging admission. Unauthorized/error/revoked/unavailable responses fail closed.

**Not a production roll-out:** `modules/order_to_cash/service.py` and the Trade order inbox still require execution-path integration and an independently certified iDempiere financial provider-readiness adapter. Merely installing this HTTP client does not prevent direct native posting. Staging proof, finance configuration and audience verification remain required before LA-05D ACCEPTED.
