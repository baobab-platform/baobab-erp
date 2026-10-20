# Database

iDempiere and the Baobab application-service layer share one PostgreSQL instance in the
initial foundation deployment, in separate schemas: iDempiere owns its own schema
(`adempiere`, per its own installer), and Baobab-owned state lives in the `baobab` schema
defined here. Neither engine's code reads or writes the other's schema directly — the
services in `modules/` are the only code that touches `baobab.*`, and only iDempiere
touches its own tables (ADR-ERP-001).

```bash
export DATABASE_URL=postgresql://user:pass@host:5432/idempiere
./db/migrate.sh
```

`db/migrations/*.sql` are applied once each, in filename order, tracked in
`baobab.schema_migrations`. `db/seed/` is intentionally empty; see its README.


## PostgreSQL 17 major-version migration

New ERP database instances and integration fixtures use PostgreSQL 17 (ADR-ERP-023).
Existing PostgreSQL 16 physical volumes cannot be attached to a 17 server: follow
[the controlled backup, migration and rollback runbook](../docs/operations/postgresql-17-upgrade.md)
before changing a persistent cluster. Do not delete volumes or auto-create an empty
replacement database in an attempt to fix a startup error.
