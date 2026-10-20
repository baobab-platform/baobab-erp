# PostgreSQL 17 adoption and PostgreSQL 16-to-17 migration runbook

**Scope:** baobab-platform/baobab-erp, iDempiere 13, Baobab application schema and native financial enforcement.
**Policy:** ADR-ERP-023; ADR-ERP-008/009/010/011/012/013/020/022.
**Baseline date:** 20 October 2026.
**Readiness:** Source configurations target PostgreSQL 17. **No existing cluster has been migrated or certified by this document.**

## 1. Safety-critical distinction

Changing the Docker image from PostgreSQL 16 to 17 changes the executable, **not** an existing on-disk cluster. PostgreSQL major-version data directories are not interchangeable. Existing named Compose volumes and AWS/EBS/RDS storage must not be mounted directly into a different major server.

Do not run 'docker compose down -v', delete the existing volume, initialize a fresh empty instance at the original data path, or silently discard data to 'fix' an image mismatch. If PostgreSQL 17 reports that the existing cluster is incompatible, **stop and use this migration procedure**.

PostgreSQL 17 is the standard for **new disposable CI/developer clusters** only after source convergence. Any persistent 16 instance has an explicit, separately reviewed migration and cutover.

Official references:
- https://www.postgresql.org/docs/17/upgrading.html
- https://www.postgresql.org/docs/17/pgupgrade.html
- https://www.postgresql.org/docs/17/release-17.html
- https://docs.idempiere.org/docs/basic-installation/installing-for-development/manual-install/install-development-prerequisites

## 2. Inventory and authorisation

Before touching a persistent cluster record:
- environment, owning account, engine instance, exact PostgreSQL minor and image digest;
- cluster size, role list, databases, tablespaces, collation/encoding, installed extensions, custom native C modules, current replicas and logical slots;
- snapshot identifiers, PITR/WAL-archive availability, key management and test of restoring into an isolated environment;
- current iDempiere 13 digest, native finance posting veto, Baobab schema migration state, outstanding jobs, outbox/inbox and pending pay-runs;
- data protection, lawful retention, maintenance window, RPO/RTO, escalation owner, sign-off and rollback authority.

Freeze all writes from iDempiere, baobab-app, workers, dispatch, integrations and scheduled jobs **before the final consistent backup/cutover**. Record that the cluster has no active unsafe writers.

## 3. Supported migration approaches

**Preferred for small or early-stage installations: logical dump/restore** to a separate fresh PostgreSQL 17 cluster, preserving the PostgreSQL 16 original intact.

1. From the live 16 server, create a consistent logical backup using a compatible 'pg_dump' client. Include global objects/roles ('pg_dumpall --globals-only'), each required database ('pg_dump -Fc'), extensions and instance configuration (not stored in SQL dumps).
2. Store backups encrypted in a durable location with access control. Verify nonzero sizes, exit codes, checksums and **a complete test restore** into an isolated 17 server.
3. Provision an explicitly new 17 data directory/volume; never bind-mount the old 16 data directory.
4. Restore roles/globals using a reviewed procedure and databases using 'pg_restore' with the required ownership, extensions and ACLs; address conflicts and collations explicitly. Check the actual server version using 'SHOW server_version_num' (170000 <= value < 180000).
5. Run approved Baobab database migrations, data consistency checks, native iDempiere acceptance, tenant separation checks and reconciliation.
6. Keep the 16 cluster shut down but intact until retention/cutover approval; never automatically point the new server at the old physical volume.

**Alternative for qualified DBA:** use PostgreSQL 17 'pg_upgrade' with old and new binaries and dedicated clusters. Run 'pg_upgrade --check' before write cutover. Ensure plugin binary compatibility, collations, extension libraries, 2Pack migrations and rollback strategy. 'pg_upgrade --link' risks irreversible reuse of old cluster storage; do not select it without an independently reviewed backup and recovery plan.

Managed database upgrades (such as RDS) require a service-specific upgrade/change procedure and engine compatibility evidence. This runbook is not an instruction to issue an AWS production upgrade.

## 4. Developer/Codespaces guidance

- A **new disposable** environment may use 'postgres:17-alpine' directly and create a new empty cluster.
- A Codespace with a pre-existing PostgreSQL 16 volume requires an affirmative choice: migrate/copy the data to a new PG17 volume, or deliberately discard disposable test data **after confirming it contains no required records**.
- Compose retains the existing logical volume name to avoid pretending that creation of a new database is data migration. An incompatible 16 volume should fail visibly under PostgreSQL 17; this is intentional.
- Never use volume deletion as an automated post-create or CI recovery step.
- Developers may use a fresh test database for synthetic fixtures; never restore personal payroll data into Codespaces or CI.

## 5. Qualification checklist

A PostgreSQL 17 migration passes only after all of the following have recorded evidence:

1. Major version verified from the server (not merely image tag); approved minor and immutable image digest recorded.
2. iDempiere 13 installed, boots cleanly, and database dictionary and migration version checks complete.
3. ERP and Baobab native schemas, roles, privileges, extensions, financial baseline and native posting veto verified.
4. Exact AD_Client/AD_Org and canonical CP mapping preserved; cross-tenant read/write negative tests pass.
5. Row counts, referential checks, key UUID/sequence inventories and agreed finance/accounting totals reconcile to baseline.
6. Provisioning, signed context resolution, native financial veto, order-to-cash, inbox/outbox/retry and reconciliation E2E tests pass.
7. Backup and recovery rehearsal succeeds; restore procedure documented and operations on-call accepts it.
8. No synthetic test, merged PR or this runbook is treated as Gate D/E certification. Protected staging and independent EA-09/CP activation are still mandatory.

## 6. Rollback

If cutover fails **before new writes**, shut down the 17 services and restore the previously accepted 16 service routing to its **unchanged** 16 data volume. Verify DNS/secrets, replay routing, read consistency and audit before reopening writes.

If any committed 17 writes occurred, the old 16 cluster is no longer an identical authoritative copy. **Do not** simply repoint clients to the old cluster. Reconcile, replay or reverse affected transactions under an incident and finance-approved recovery plan, preserving durable event idempotency and legal/accounting history.

For major production environments, define maximum allowed divergence and failure-handling thresholds before cutover.

## 7. Sources and ownership

The ERP repository owns its PG17 image/development/CI baseline and implementation evidence. Infrastructure owns deployed server/volume lifecycle. Control Plane owns EngineInstance eligibility and capability activation. Finance and security must independently accept payroll/ERP data integrity, payment and tenant-boundary evidence.

The compatibility matrix shall additionally test each approved CDSoftware component and People country pack against the **exact** iDempiere 13, Java 17 and PostgreSQL 17 versions, including native UUID behavior and SQL/Jasper report parameter handling.
