# DEV-12 native PostgreSQL 17 restore drill

This owner-local phase follows the unchanged ERP-A iDempiere/JVM cases.
It is governed by Accepted Infra-0022 and ERP-022; no operation class,
canonical capability, legal mandate or posting permission is added.

The harness stops its actual JVM, snapshots native tables and trigger/function
ownership, writes a custom-format logical dump inside the owned PostgreSQL
container, and restores it into a generated disposable sibling database. It
preserves owners and grants. It compares actual accounting, orders, invoices,
stock/costing, two-company placement and native attribution state, then executes
an unauthorised native order completion as the restored `adempiere` role.
Success requires `UPDATE 1`, a COMMIT-time native finance refusal and unchanged
native state. A generic SQL error or zero-row update is insufficient.

The dump never becomes a CI artifact. Database/archive removal is attempted on
failure and independently read back before any success receipt is written.
Normal owner-harness teardown remains mandatory and removes the whole disposable
cluster after process death. A failed rerun first removes its stale report/hash.

`dev12-native-restore.json` and its SHA-256 pair are supplemental original
receipts. Existing ERP-A and DEV-09 inventories remain unchanged. The receipt
qualifies only actual native-state logical restoration and the restored SQL
veto when CI executes it. It does not qualify restored JVM operation, schema
upgrade, a physical PostgreSQL major migration, production rollback, RPO/RTO,
cross-engine event replay or live provider/legal acceptance. Those obligations
retain their own engineering or protected gates.

Run through the existing `run-gate-d-erp-a.sh` command; do not run it against
customer databases. It accepts only the existing isolated integration lane and
a nonce-owned `baobab-erp-a-<16 hex>` project. To recover a killed drill, tear
down that exact owned Compose project with the existing harness cleanup and
verify empty resource readback. Never restore over the source database.
