#!/usr/bin/env bash
# EA v2.2 EA-R03 ERP-A engine-local harness (ADR-SHARED-037, ADR-ERP-022 §4.3).
# Runs REAL iDempiere 13 with the shipped Baobab finance veto and native
# migrations against the REAL CP release binary built at a pinned merged commit,
# real RS256-signed workload tokens from a test issuer, and PostgreSQL 17 for
# both ERP and CP. Every hop iDempiere makes is TLS through the edge. Drives the
# purchase-side scenarios and writes the evidence bundle and receipt.
#
# Engine-local real-component evidence on SYNTHETIC data: NOT EA Gate D and
# NOT L4 (EA v2.2). Nothing here is deployable.
#
#   run-gate-d-erp-a.sh <evidence-dir>
#
# Required environment:
#   BAOBAB_ENVIRONMENT=integration   anything else is refused
#   ERP_IMAGE                        the Gate D acceptance image (driver bundle on the release image)
#   CP_SRC                           baobab-cp checkout at the pinned commit
# Optional: GATE_D_KEEP=1 leaves the stack running for inspection.
set -euo pipefail

if [ "${BAOBAB_ENVIRONMENT:-}" != "integration" ]; then
  echo "the ERP-A harness runs only with BAOBAB_ENVIRONMENT=integration" >&2
  exit 2
fi
: "${ERP_IMAGE:?ERP_IMAGE is required}" "${CP_SRC:?CP_SRC is required}"
: "${IAM_SRC:?IAM_SRC is required}" "${IAM_COMMIT:?IAM_COMMIT is required}"
OUT=$(mkdir -p "${1:?evidence directory required}" && cd "$1" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
RUN=$(mktemp -d)
echo "[erp-a] run directory: $RUN"
export RUN_DIR=$RUN ERP_IMAGE
export CP_IMAGE=baobab-gate-d-erp-a/cp:local PYTHON_IMAGE=baobab-gate-d-erp-a/python:local
export CPDB_PASSWORD="cpdb-$(openssl rand -hex 12)" ERP_WORKLOAD_SECRET=$(openssl rand -hex 24)
export ORY_DB_PASSWORD="$(openssl rand -hex 24)" ORY_SYSTEM_SECRET="$(openssl rand -hex 32)"
export ORY_HOOK_SECRET="$(openssl rand -hex 32)"
export ERP_A_PROJECT="baobab-erp-a-$(openssl rand -hex 8)"
COMPOSE=(docker compose -f "$HERE/compose.yaml" -p "$ERP_A_PROJECT")
log() { printf '[erp-a] %s\n' "$*" | tee -a "$OUT/run.log"; }

collect() {
  for s in erp cp issuer edge hydra kratos; do
    "${COMPOSE[@]}" logs --no-color "$s" > "$OUT/$s.log" 2>&1 || true
  done
  # Logs are evidence: they must never carry a token or the workload secret.
  if grep -l -e "$ERP_WORKLOAD_SECRET" -e "$ORY_HOOK_SECRET" -e "$ORY_SYSTEM_SECRET" "$OUT"/*.log >/dev/null 2>&1 \
     || grep -Pl 'eyJ[A-Za-z0-9_-]{20,}\.' "$OUT"/*.log >/dev/null 2>&1; then
    log "a log carries a token or the workload secret"; return 1
  fi
}
cleanup() {
  local status=$?
  trap - EXIT
  collect || status=1
  if [ "${GATE_D_KEEP:-0}" != "1" ]; then
    "${COMPOSE[@]}" down -v --remove-orphans > "$OUT/cleanup.log" 2>&1 || status=1
    rm -rf "$RUN" || status=1
    python3 "$REPO/scripts/dev09_evidence.py" cleanup --project "$ERP_A_PROJECT" --run "$RUN" \
      --output "$OUT/dev09-cleanup.json" || status=1
  fi
  exit "$status"
}
# Old receipts never survive an aborted rerun. Only these owned evidence files are removed.
rm -f "$OUT"/{erp-a-receipt,dev09-cleanup,dev09-report,dev09-report.sha256,dev09-ory-provision,dev09-ory-consumption,dev09-native-company,dev09-connected-report,dev09-connected-report.sha256}.json
trap cleanup EXIT
: > "$OUT/run.log"
: > "$OUT/erp-a-report.txt"
# Each invocation owns a fresh Compose project. A loopback port collision fails safely.

log "throwaway CA, the TLS edge certificate and iDempiere's truststore"
mkdir -p "$RUN"/{edge,cp,issuer,erp-tls,erp-secret,gate-d/requests,gate-d/results}
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=Baobab ERP-A throwaway CA" \
  -keyout "$RUN/ca.key" -out "$RUN/ca.pem" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=gated.test" -keyout "$RUN/edge/server.key" -out "$RUN/edge.csr" 2>/dev/null
printf 'subjectAltName=DNS:cp.gated.test,DNS:iam.gated.test,DNS:hydra.gated.test\nextendedKeyUsage=serverAuth\n' > "$RUN/edge.ext"
openssl x509 -req -in "$RUN/edge.csr" -CA "$RUN/ca.pem" -CAkey "$RUN/ca.key" -CAcreateserial -days 1 \
  -extfile "$RUN/edge.ext" -out "$RUN/edge/server.pem" 2>/dev/null
keytool -importcert -noprompt -alias erp-a-ca -file "$RUN/ca.pem" -keystore "$RUN/erp-tls/truststore.p12" \
  -storetype PKCS12 -storepass changeit >/dev/null 2>&1
cp "$RUN/ca.pem" "$RUN/cp/ca.pem"; cp "$RUN/ca.pem" "$OUT/ca.pem"
chmod -R a+rX "$RUN"; chmod -R 0777 "$RUN/gate-d"

log "IAM-owned Ory configuration at its exact source pin"
python3 "$HERE/driver/ory_bootstrap.py" prepare --run "$RUN" --out "$OUT" --iam "$IAM_SRC" --iam-sha "$IAM_COMMIT"

log "workload client and the CI-only registry snapshot"
python3 - "$RUN/issuer/clients.json" "$ERP_WORKLOAD_SECRET" <<'EOF'
import json, sys
json.dump({"baobab-erp-legal-actor-assessor-staging": {
    "secret": sys.argv[2], "audience": "baobab-control-plane",
    "scopes": ["context:resolve", "legal-actor:assess", "documentary:restriction-assess",
               "erp-posting-authority:resolve"]}}, open(sys.argv[1], "w"))
EOF
cp "$HERE/cp/workload-registry.yaml" "$RUN/cp/workload-registry.yaml"
printf '%s\n' "$ERP_WORKLOAD_SECRET" > "$RUN/erp-secret/workload-secret"
chmod a+rX "$RUN/erp-secret"; chmod 0444 "$RUN/erp-secret/workload-secret"
chmod -R a+rX "$RUN/issuer" "$RUN/cp"

CP_COMMIT=$(git -C "$CP_SRC" rev-parse HEAD)
log "images: CP release binaries at $CP_COMMIT, test issuer"
mkdir -p "$RUN/build/cp" "$RUN/build/py/wheels" "$RUN/build/py/issuer"
(cd "$CP_SRC" && CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o "$RUN/build/cp/controlplane" ./cmd/controlplane \
  && CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o "$RUN/build/cp/migrate" ./cmd/migrate)
docker build -q -t "$CP_IMAGE" -f "$HERE/images/cp.Dockerfile" "$RUN/build/cp" >/dev/null
pip download --quiet --only-binary=:all: --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 \
  --platform manylinux_2_17_x86_64 --python-version 3.12 --implementation cp "cryptography==44.0.3" \
  -d "$RUN/build/py/wheels"
cp "$HERE/issuer/issuer.py" "$RUN/build/py/issuer/"
docker build -q -t "$PYTHON_IMAGE" -f "$HERE/images/python.Dockerfile" "$RUN/build/py" >/dev/null

log "CP, real Ory Hydra/Kratos databases and private TLS issuer"
"${COMPOSE[@]}" up -d --wait hydra-db kratos-db >/dev/null
"${COMPOSE[@]}" up -d hydra kratos issuer edge >/dev/null

log "CP database, the TLS edge, Ory workload issuer, then CP"
"${COMPOSE[@]}" up -d --wait cpdb erpdb >/dev/null
"${COMPOSE[@]}" run --rm --no-deps --entrypoint /migrate cp >"$OUT/cp-migrate.log" 2>&1
"${COMPOSE[@]}" up -d cp >/dev/null
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:18092/healthz >/dev/null && break; sleep 2; done
curl -sf http://127.0.0.1:18092/healthz >/dev/null || { log "CP did not start"; exit 1; }

log "seeding CP through its admin API (and the recorded synthetic rows)"
python3 "$HERE/driver/gate_d_erp_a.py" seed --run "$RUN" --out "$OUT" --compose "$HERE/compose.yaml"
python3 "$HERE/driver/ory_bootstrap.py" provision --run "$RUN" --out "$OUT" --iam-sha "$IAM_COMMIT"

log "iDempiere (imports GardenWorld on first start), protected acceptance runtime"
"${COMPOSE[@]}" up -d erp >/dev/null
for _ in $(seq 1 180); do
  [ -f "$RUN/gate-d/ready" ] && "${COMPOSE[@]}" exec -T erp test -s /opt/idempiere/.baobab/native-finance-veto-active && break
  "${COMPOSE[@]}" ps -q erp | grep -q . || { log "iDempiere exited"; exit 1; }
  sleep 5
done
[ -f "$RUN/gate-d/ready" ] || { log "iDempiere did not become ready"; exit 1; }

log "Baobab migrations on iDempiere's database, then the ERP-owned placement and baseline"
export DATABASE_URL="postgresql://adempiere:adempiere@127.0.0.1:55462/idempiere"
"$REPO/db/migrate.sh" > "$OUT/erp-migrate.log"
"$REPO/db/migrate-native.sh" >> "$OUT/erp-migrate.log"
python3 "$HERE/driver/gate_d_erp_a.py" place --run "$RUN" --out "$OUT" --compose "$HERE/compose.yaml"
python3 "$HERE/driver/independent_company.py" place --run "$RUN" --out "$OUT" --compose "$HERE/compose.yaml"
python3 "$HERE/driver/independent_company.py" verify --run "$RUN" --out "$OUT" --compose "$HERE/compose.yaml"
python3 "$HERE/driver/ory_bootstrap.py" consume --run "$RUN" --out "$OUT"

log "scenarios"
export CP_COMMIT ERP_COMMIT=$(git -C "$REPO" rev-parse HEAD)
python3 "$HERE/driver/gate_d_erp_a.py" scenarios --run "$RUN" --out "$OUT" --compose "$HERE/compose.yaml"
grep -q '^ERP-A failures: 0$' "$OUT/erp-a-report.txt"
