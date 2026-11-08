#!/usr/bin/env bash
# BP-04 disposable proof only. Not part of db/migrate.sh or production boot.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${DATABASE_URL:?Set DATABASE_URL for a disposable PostgreSQL 17 database}"
if [[ "${BAOBAB_PEOPLE_EXPERIMENTAL:-}" != "1" ]]; then
  echo "Refusing Baobab People experimental migration without explicit opt-in" >&2
  exit 1
fi
if [[ ! "${BAOBAB_ENVIRONMENT:-}" =~ ^(test|development|integration)$ ]]; then
  echo "Refusing Baobab People experimental migration in protected environment" >&2
  exit 1
fi
if [[ "$(psql "${DATABASE_URL}" -X -v ON_ERROR_STOP=1 -tAc 'SHOW server_version_num')" != 17???? ]]; then
  echo "Baobab People BP-04 requires PostgreSQL major 17" >&2
  exit 1
fi
for script in "${repo_root}"/db/people-migrations/P*.sql; do
  file="people/$(basename "${script}")"
  if [[ "$(psql "${DATABASE_URL}" -X -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM baobab.schema_migrations WHERE filename = '${file}'")" = "1" ]]; then
    echo "skip ${file}"
    continue
  fi
  psql "${DATABASE_URL}" -X -v ON_ERROR_STOP=1 --single-transaction \
    -f "${script}" \
    -c "INSERT INTO baobab.schema_migrations(filename) VALUES ('${file}')"
done

# Independently verify actual enabled native DB safeguards, even on repeated
# invocations where all migration tracking rows already exist.
missing=$(psql "${DATABASE_URL}" -X -v ON_ERROR_STOP=1 -tA \
  -f "${repo_root}/db/check-people-experimental.sql")
if [[ "${missing}" != "0" ]]; then
  echo "BAOBAB_PEOPLE_DENIED: missing/disabled experimental PostgreSQL People safeguards" >&2
  exit 1
fi
echo "BP-04 native PostgreSQL 17 proposal guards: PASS"
