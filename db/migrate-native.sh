#!/usr/bin/env bash
# Applies db/native-migrations/*.sql once each to the iDempiere database,
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
  psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 -f "${migration}"
  psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 -c \
    "INSERT INTO baobab.schema_migrations (filename) VALUES ('${filename}')"
done
