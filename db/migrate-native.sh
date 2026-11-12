#!/usr/bin/env bash
# Applies db/native-migrations/*.sql once each, atomically, to the iDempiere database,
# tracked in baobab.schema_migrations as native/<file>. Run AFTER the iDempiere
# seed/upgrade (the adempiere schema must exist) and AFTER db/migrate.sh, and
# BEFORE the iDempiere finance routes are exposed (ADR-ERP-022).
# Requires psql and DATABASE_URL naming the SAME database iDempiere uses.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${DATABASE_URL:?Set DATABASE_URL}"

if [[ "$(psql "${DATABASE_URL}" -tAc "SELECT to_regclass('adempiere.ad_client') IS NOT NULL")" != "t" ]]; then
  echo "error: the iDempiere adempiere schema is missing; seed iDempiere first" >&2
  exit 1
fi
if [[ "$(psql "${DATABASE_URL}" -tAc "SELECT to_regclass('baobab_native.finance_authority_attribution') IS NOT NULL")" != "t" ]]; then
  echo "error: apply db/migrate.sh (0025) to this database first" >&2
  exit 1
fi

for migration in "${repo_root}"/db/native-migrations/*.sql; do
  filename="native/$(basename "${migration}")"
  already_applied=$(psql "${DATABASE_URL}" -tAc \
    "SELECT 1 FROM baobab.schema_migrations WHERE filename = '${filename}'")
  if [[ "${already_applied}" == "1" ]]; then
    echo "skip  ${filename} (already applied)"
    continue
  fi
  echo "apply ${filename}"
  # The migration and its tracking row commit in ONE transaction: a failed or
  # interrupted run leaves neither, so a rerun never meets half-applied DDL.
  psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 --single-transaction \
    -f "${migration}" \
    -c "INSERT INTO baobab.schema_migrations (filename) VALUES ('${filename}')"
done

# A tracking row is not itself evidence that the native security triggers
# remain installed/enabled. This exact native PostgreSQL 17 connection must
# independently observe all mandatory N0010–N0013 controls on EVERY run,
# including idempotent re-execution and when nothing needs migrating.
missing_guards=$(psql "${DATABASE_URL}" -X -v ON_ERROR_STOP=1 -tA \
  -f "${repo_root}/db/check-native-guards.sql")
if [[ ! "${missing_guards}" =~ ^[0-9]+$ || "${missing_guards}" != "0" ]]; then
  echo "error: native finance guard verification failed (missing/disabled controls); refuse readiness" >&2
  exit 1
fi
echo "verify native PostgreSQL 17 financial and legal-actor guards: PASS"
