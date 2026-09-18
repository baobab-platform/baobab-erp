#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

python -m compileall -q modules tests

# tests/security/test_workload_auth.py (Gate IAM-10) is the first test outside
# tests/integration to need a third-party dependency (PyJWT, for real RS256
# verification against a generated keypair rather than a hand-rolled check).
# Installing modules/ itself (as ci.yml's core-module-integration job does) is
# unnecessary here and doesn't work: this job's container bind-mounts the
# workspace owned by the host runner's UID, and an editable install needs to
# write an .egg-info directory into that mounted source tree. PYTHONPATH=modules
# already makes modules/'s own packages importable with no install step (every
# existing suite here already relies on exactly that) -- only the third-party
# dependency itself needs installing, from PyPI, and --target a scratch
# directory under /tmp sidesteps needing to know whether this container's user
# can write to its own site-packages, same as it can't write to the mount.
pip install --break-system-packages -q --target /tmp/py-deps "PyJWT[crypto]>=2.8,<3"

PYTHONPATH=modules:/tmp/py-deps python -m unittest discover -s tests/unit -p 'test_*.py'
PYTHONPATH=modules:/tmp/py-deps python -m unittest discover -s tests/security -p 'test_*.py'
PYTHONPATH=modules:/tmp/py-deps python -m unittest discover -s tests/tenancy -p 'test_*.py'
PYTHONPATH=modules:/tmp/py-deps python -m unittest discover -s tests/contract -p 'test_*.py'
PYTHONPATH=modules:/tmp/py-deps python -m unittest discover -s tests/architecture -p 'test_*.py'
PYTHONPATH=modules:/tmp/py-deps python -m unittest discover -s tests/golden -p 'test_*.py'

python - <<'PY'
import json
from pathlib import Path

for path in Path(".").rglob("*.json"):
    if "/target/" in str(path) or "/.git/" in str(path):
        continue
    json.loads(path.read_text())
print("JSON validation passed")
PY

if command -v mvn >/dev/null 2>&1; then
  mvn -q -f idempiere/extensions package
else
  echo "mvn not found; skipping OSGi extension build" >&2
fi

if [[ "${SKIP_COMPOSE_VALIDATION:-0}" != "1" ]] && command -v docker >/dev/null 2>&1; then
  DB_PASS=validation DB_ADMIN_PASS=validation \
  BAOBAB_EVENT_SIGNING_SECRET=validation \
  BAOBAB_WEBHOOK_URL=https://validation.example.com/baobab/events \
  docker compose -f compose.yaml config --quiet
fi
