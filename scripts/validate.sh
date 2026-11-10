#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

python -m compileall -q modules tests

# Unit tests import the actual native inbox/AMQP/OTel modules. Install their
# declared runtime dependencies, rather than a stale hand-maintained subset.
# A private temporary target works with the non-root, read-only source mount
# without writing editable-install metadata or modifying the shared dev image.
deps_dir="$(mktemp -d)"
trap 'rm -rf "$deps_dir"' EXIT
python - "$deps_dir" <<'PY'
from pathlib import Path
import subprocess
import sys
import tomllib

requirements = tomllib.loads(Path("modules/pyproject.toml").read_text())["project"]["dependencies"]
subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                "-q", "--target", sys.argv[1], *requirements], check=True)
PY

PYTHONPATH="modules:$deps_dir" python -m unittest discover -s tests/unit -p 'test_*.py'
PYTHONPATH="modules:$deps_dir" python -m unittest discover -s tests/security -p 'test_*.py'
PYTHONPATH="modules:$deps_dir" python -m unittest discover -s tests/tenancy -p 'test_*.py'
PYTHONPATH="modules:$deps_dir" python -m unittest discover -s tests/architecture -p 'test_*.py'
PYTHONPATH="modules:$deps_dir" python -m unittest discover -s tests/golden -p 'test_*.py'

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
