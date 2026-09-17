# ZuriBeans ERP activation runbook
Run separately for Zuribeans_ZA and Zuribeans_UG. READY is evidence, not an implicit production activation.
Required evidence: authoritative CP assignment; successful native iDempiere provisioning; certified localisation; warehouse mappings; master-data reconciliation; procurement, sales, inventory and FX golden paths; final reconciliation.
Golden tests must run against a real provisioned test iDempiere instance. Do not replace them with mocks for release evidence.
Exercise both legal entities independently and prove that market roles are capabilities rather than hard-coded Uganda-source/South-Africa-sell assumptions.
Production ACTIVE remains a governed action after the ActivationReport is ready and all external approvals required by accepted ADRs are present.
