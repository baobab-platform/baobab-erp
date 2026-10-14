#!/usr/bin/env bash
# EA v2.1 Gate D (P0-04B ERP): REAL iDempiere 13 + PostgreSQL posting through the
# installed Baobab native finance veto, the native migrations' COMMIT fence and a
# SYNTHETIC CP/IAM over TLS. CI only. Asserts persisted database state, never
# just exit codes. Synthetic data proves mechanism, not legal standing.
#
# Usage: run-gate-d.sh <acceptance-image> <work-dir>
set -euo pipefail

IMAGE=${1:?acceptance image}
WORK=$(mkdir -p "${2:?work dir}" && cd "$2" && pwd)
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
NET=baobab-gate-d
PG_PORT=${GATE_D_PG_PORT:-55432}
PG_IMAGE=${GATE_D_PG_IMAGE:-postgres:16}
PY_IMAGE=${GATE_D_PY_IMAGE:-python:3.12-slim}
LE=SYNTHETIC-GATED-LE
export DATABASE_URL="postgresql://adempiere:adempiere@localhost:${PG_PORT}/idempiere"
FAILURES=0
REPORT="$WORK/gate-d-report.txt"
: > "$REPORT"

cleanup() {
  docker logs gd-erp > "$WORK/idempiere.log" 2>&1 || true
  docker logs gd-cp > "$WORK/synthetic-cp.log" 2>&1 || true
  # GATE_D_KEEP=1 leaves the containers up for local diagnosis (never in CI).
  if [ "${GATE_D_KEEP:-0}" != 1 ]; then
    docker rm -f gd-erp gd-cp gd-pg >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

note() { echo "$*" | tee -a "$REPORT"; }
pass() { note "PASS  $1"; }
fail() { note "FAIL  $1: $2"; FAILURES=$((FAILURES + 1)); }
sql() { psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -tAq -c "SET search_path = adempiere, public; $1" | tail -n 1; }

# --- TLS: a CI-generated CA trusted only by this JVM ---------------------------------------------
mkdir -p "$WORK/tls" "$WORK/state" "$WORK/gate-d/requests" "$WORK/gate-d/results"
chmod -R 0777 "$WORK/state" "$WORK/gate-d"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=Baobab Gate D synthetic CA" \
  -keyout "$WORK/tls/ca.key" -out "$WORK/tls/ca.pem" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=cp-synthetic" -keyout "$WORK/tls/server.key" \
  -out "$WORK/tls/server.csr" 2>/dev/null
printf 'subjectAltName=DNS:cp-synthetic\n' > "$WORK/tls/san.ext"
openssl x509 -req -in "$WORK/tls/server.csr" -CA "$WORK/tls/ca.pem" -CAkey "$WORK/tls/ca.key" \
  -CAcreateserial -days 1 -extfile "$WORK/tls/san.ext" -out "$WORK/tls/server.pem" 2>/dev/null
rm -f "$WORK/tls/truststore.p12"
keytool -importcert -noprompt -alias gate-d-ca -file "$WORK/tls/ca.pem" -keystore "$WORK/tls/truststore.p12" \
  -storetype PKCS12 -storepass changeit >/dev/null 2>&1
chmod 0644 "$WORK/tls/"*

# --- Fresh PostgreSQL (the upstream entrypoint imports GardenWorld) ------------------------------
docker rm -f gd-erp gd-cp gd-pg >/dev/null 2>&1 || true
docker network rm "$NET" >/dev/null 2>&1 || true
docker network create "$NET" >/dev/null
docker run -d --name gd-pg --network "$NET" -p "${PG_PORT}:5432" -e POSTGRES_PASSWORD=postgres "$PG_IMAGE" >/dev/null
until docker exec gd-pg pg_isready -U postgres -q; do sleep 1; done

# --- Synthetic CP/IAM ---------------------------------------------------------------------------
echo authorized > "$WORK/state/mode"
docker run -d --name gd-cp --network "$NET" --network-alias cp-synthetic \
  -v "$REPO/idempiere/acceptance/synthetic_cp.py:/srv/synthetic_cp.py:ro" -v "$WORK/tls:/tls:ro" \
  -v "$WORK/state:/state" -e GATE_D_CERT=/tls/server.pem -e GATE_D_KEY=/tls/server.key \
  -e GATE_D_LEGAL_ENTITY="$LE" -e GATE_D_MARKET=US "$PY_IMAGE" python3 /srv/synthetic_cp.py >/dev/null

# --- Real iDempiere with the shipped Baobab bundles, acceptance (protected) runtime ---------------
JAVA_OPTS="-Xms256m -Xmx2g -Dbaobab.erp.native.environment=acceptance \
-Dbaobab.cp.native.base.url=https://cp-synthetic:8443 -Dbaobab.iam.token.url=https://cp-synthetic:8443/token \
-Dbaobab.iam.native.client.id=baobab-erp-legal-actor-assessor-staging -Dbaobab.iam.native.client.secret=synthetic-gate-d \
-Djavax.net.ssl.trustStore=/gate-d-tls/truststore.p12 -Djavax.net.ssl.trustStoreType=PKCS12 -Djavax.net.ssl.trustStorePassword=changeit"
docker run -d --name gd-erp --network "$NET" -e DB_HOST=gd-pg -e DB_ADMIN_PASS=postgres -e DB_PASS=adempiere \
  -e JAVA_OPTS="$JAVA_OPTS" -v "$WORK/tls:/gate-d-tls:ro" -v "$WORK/gate-d:/opt/idempiere/.baobab/gate-d" \
  "$IMAGE" >/dev/null
for _ in $(seq 1 180); do
  [ -f "$WORK/gate-d/ready" ] && docker exec gd-erp test -s /opt/idempiere/.baobab/native-finance-veto-active && break
  docker ps -q -f name=gd-erp | grep -q . || { docker logs gd-erp | tail -40; echo "iDempiere exited" >&2; exit 1; }
  sleep 5
done
[ -f "$WORK/gate-d/ready" ] || { docker logs gd-erp | tail -60; echo "iDempiere did not become ready" >&2; exit 1; }
docker exec gd-erp test -s /opt/idempiere/.baobab/native-finance-veto-active \
  && pass "finance veto bundle ACTIVE (PID marker present)" || fail "finance veto" "marker missing"

# --- Baobab migrations on the SAME database, then synthetic governed facts -----------------------
"$REPO/db/migrate.sh" > "$WORK/migrate.log"
"$REPO/db/migrate-native.sh" >> "$WORK/migrate.log"
PLACEMENT=0b6d1f9a-3c2e-4a8b-9d7f-5e4c3b2a1908
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q <<SQL
-- An accounting operator puts GardenWorld under STANDARD period control (C_PeriodControl, which
-- Baobab readiness checks, ADR-ERP-008). The seed ships Automatic Period Control, under which
-- iDempiere ignores C_PeriodControl and rewrites C_AcctSchema.C_Period_ID from MPeriod.isOpen in
-- its own autocommit transaction: a configuration write the native veto refuses (Gate D finding).
UPDATE adempiere.c_acctschema SET autoperiodcontrol = 'N' WHERE ad_client_id = 11;
-- Opening inventory valuation (operator setup, before the placement exists): the seed's schemas cost by
-- Average PO but hold only standard costs and no average-cost quantity, so every shipment would fail
-- ("No Costs" / negative average quantity). Each stocked product gets an Average PO cost at its standard
-- material cost with its client-wide quantity on hand, in every schema of the client.
INSERT INTO adempiere.m_cost
SELECT (jsonb_populate_record(c, jsonb_build_object(
          'c_acctschema_id', s.c_acctschema_id, 'm_cost_uu', gen_random_uuid()::text,
          'm_costelement_id', ae.m_costelement_id,
          'currentqty', q.qty, 'cumulatedqty', q.qty, 'cumulatedamt', q.qty * c.currentcostprice))).*
  FROM adempiere.m_cost c
  JOIN adempiere.m_costelement se ON se.m_costelement_id = c.m_costelement_id AND se.costingmethod = 'S'
   AND se.costelementtype = 'M'
  JOIN adempiere.m_costelement ae ON ae.ad_client_id = 11 AND ae.costingmethod = 'A' AND ae.isactive = 'Y'
  JOIN adempiere.c_acctschema s ON s.ad_client_id = 11
  JOIN (SELECT st.m_product_id, sum(st.qtyonhand) AS qty FROM adempiere.m_storageonhand st
         WHERE st.ad_client_id = 11 GROUP BY st.m_product_id) q ON q.m_product_id = c.m_product_id
 WHERE c.ad_client_id = 11 AND c.currentcostprice > 0 AND q.qty > 0
   AND c.c_acctschema_id = (SELECT c_acctschema1_id FROM adempiere.ad_clientinfo WHERE ad_client_id = 11)
   AND NOT EXISTS (SELECT 1 FROM adempiere.m_cost x WHERE x.c_acctschema_id = s.c_acctschema_id
     AND x.ad_client_id = 11 AND x.ad_org_id = c.ad_org_id AND x.m_product_id = c.m_product_id
     AND x.m_costtype_id = c.m_costtype_id AND x.m_costelement_id = ae.m_costelement_id
     AND x.m_attributesetinstance_id = c.m_attributesetinstance_id);
-- ...and opens the current period for the governed sales-side document types (seed ships them never-opened).
UPDATE adempiere.c_periodcontrol pc SET periodstatus = 'O'
  FROM adempiere.c_period p
 WHERE p.c_period_id = pc.c_period_id AND p.ad_client_id = 11
   AND pc.docbasetype IN ('GLJ', 'SOO', 'MMS', 'ARI', 'ARR', 'CMA')
   AND current_date BETWEEN p.startdate AND p.enddate;
INSERT INTO baobab_native.native_placement (placement_id, version, tenant_id, engine_instance_id,
  operating_organisation_id, legal_entity_id, market, ad_client_id, ad_org_id, effective_from,
  approved_by, checked_by, evidence_reference, erp_assignment_reference)
VALUES ('$PLACEMENT', 1, 'tn_gated01', 'ei_gated01', '2c8e4f6a-1b3d-4e5f-8a7c-9d0e1f2a3b4c', '$LE', 'US',
  11, 11, now() - interval '1 day', 'Synthetic Placement Maker', 'Synthetic Placement Checker',
  'synthetic:gate-d/placement', 'synthetic:gate-d/plan/v1');
INSERT INTO baobab.financial_configuration_baseline (legal_entity_id, version, functional_currency,
  fiscal_year_start_month, chart_of_accounts_template, accounting_schema, tax_profile, costing_method,
  effective_from, approved_by, approved_at, evidence_reference)
VALUES ('$LE', 1, 'USD', 1, 'synthetic-gardenworld', 'synthetic-gardenworld', 'synthetic-gardenworld',
  'AVERAGE_PO', current_date - 30, 'Synthetic Finance Approver', now(), 'synthetic:gate-d/baseline');
SQL

# --- Driver protocol ----------------------------------------------------------------------------
run() { # name mode key=value...
  local name=$1 mode=$2; shift 2
  echo "$mode" > "$WORK/state/mode"
  printf '%s\n' "$@" > "$WORK/gate-d/requests/$name.tmp"
  mv "$WORK/gate-d/requests/$name.tmp" "$WORK/gate-d/requests/$name.properties"
  for _ in $(seq 1 120); do [ -f "$WORK/gate-d/results/$name.properties" ] && break; sleep 1; done
  [ -f "$WORK/gate-d/results/$name.properties" ] || { fail "$name" "driver timed out"; return 1; }
  sed 's/^/    /' "$WORK/gate-d/results/$name.properties" | grep -v '^    #' >> "$REPORT"
}
prop() { grep -E "^$2=" "$WORK/gate-d/results/$1.properties" | head -1 | cut -d= -f2- || true; }
posted_ok() { # journal_id: CO, posted, balanced ledger, attributed by a CP decision
  local id=$1
  [ "$(sql "SELECT docstatus || posted FROM gl_journal WHERE gl_journal_id = $id")" = "COY" ] &&
  [ "$(sql "SELECT count(*) > 0 AND sum(amtacctdr) = sum(amtacctcr) FROM fact_acct WHERE ad_table_id = 224 AND record_id = $id")" = "t" ] &&
  [ "$(sql "SELECT count(*) > 0 FROM baobab_native.finance_authority_attribution WHERE source_table = 'GL_Journal' AND source_record_id = $id AND decision_id IS NOT NULL AND operation_class = 'erp.gl-journal.post' AND finance_baseline_version = 1")" = "t" ]
}
not_posted() { # journal_id: never completed and no ledger
  local id=$1
  [ "$(sql "SELECT count(*) FROM gl_journal WHERE gl_journal_id = $id AND docstatus IN ('CO','CL')")" = "0" ] &&
  [ "$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 224 AND record_id = $id")" = "0" ]
}
baobab_denied() { grep -q "BAOBAB_NATIVE_FINANCE_DENIED" "$WORK/gate-d/results/$1.properties"; }
co_count() { sql "SELECT count(*) FROM gl_journal WHERE ad_client_id = 11 AND docstatus = 'CO'"; }

# 1. Current exact authority: real completion and Doc_GLJournal posting commit with attribution.
run valid authorized action=journal complete=true post=true || true
J1=$(prop valid journal_id)
if [ -n "$J1" ] && posted_ok "$J1"; then pass "valid authority: CO, posted, balanced Fact_Acct, attributed (journal $J1)"
else fail "valid authority" "journal ${J1:-none} not completed/posted/attributed"; fi

# 2. No current mandate: even the draft is refused; nothing completes.
before=$(co_count)
run no_mandate no_mandate action=journal complete=true post=true || true
J=$(prop no_mandate journal_id)
if [ "$(co_count)" = "$before" ] && { [ -z "$J" ] || not_posted "$J"; } && baobab_denied no_mandate; then pass "no mandate: refused, no completion or ledger"
else fail "no mandate" "a document completed"; fi

# 3. Authority lost between draft and completion (revocation, other actor/tenant/market, expiry, documentary hold).
for mode in revoked other_le other_tenant wrong_market wrong_activity expired documentary_hold; do
  run "draft_$mode" authorized action=journal complete=false post=false || true
  D=$(prop "draft_$mode" journal_id)
  if [ -z "$D" ]; then fail "$mode" "draft not created"; continue; fi
  run "complete_$mode" "$mode" action=complete journal_id="$D" || true
  if not_posted "$D" && baobab_denied "complete_$mode"; then pass "$mode at completion: refused, no CO and no Fact_Acct (journal $D)"
  else fail "$mode at completion" "journal $D completed or posted"; fi
done

# 4. Native org without a placement: the document cannot even be created.
run unplaced authorized action=journal org=12 complete=true post=true || true
J=$(prop unplaced journal_id)
if { [ -z "$J" ] || [ "$(sql "SELECT count(*) FROM gl_journal WHERE gl_journal_id = $J")" = "0" ]; } && baobab_denied unplaced; then
  pass "unplaced AD_Org: creation refused"
else fail "unplaced AD_Org" "document $J exists"; fi

# 5. Failure injected AFTER Fact_Acct rows were written, BEFORE commit: nothing survives.
run injected_failure authorized action=journal complete=true post=false rollbackAfterPost=true || true
J=$(prop injected_failure journal_id); F=$(prop injected_failure facts_before_rollback)
if [ -n "$J" ] && [ "${F:-0}" -gt 0 ] && [ "$(sql "SELECT count(*) FROM gl_journal WHERE gl_journal_id = $J")" = "0" ] \
   && [ "$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 224 AND record_id = $J")" = "0" ] \
   && [ "$(sql "SELECT count(*) FROM baobab_native.finance_authority_attribution WHERE source_record_id = $J")" = "0" ]; then
  pass "injected failure after $F Fact_Acct rows: no journal, ledger or attribution survives"
else fail "injected failure" "journal ${J:-?} facts ${F:-?} left state behind"; fi

# 6. Concurrent postings: each commits its own balanced ledger under its own attribution.
run concurrent authorized action=journal complete=true post=true parallel=3 || true
ok=0
for i in 0 1 2; do J=$(prop concurrent "run$i.journal_id"); [ -n "$J" ] && posted_ok "$J" && ok=$((ok + 1)); done
if [ "$ok" = 3 ] && [ "$(sql "SELECT count(DISTINCT txid) >= 3 FROM baobab_native.finance_authority_attribution WHERE source_record_id IN ($(for i in 0 1 2; do prop concurrent "run$i.journal_id"; done | paste -sd, -))")" = "t" ]; then
  pass "concurrent postings: 3 independent, balanced, separately attributed"
else fail "concurrent postings" "$ok of 3 posted cleanly"; fi

# 7. Retry after a committed posting: no duplicate ledger.
if [ -n "${J1:-}" ]; then
  facts=$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 224 AND record_id = $J1")
  run retry authorized action=repost journal_id="$J1" || true
  [ "$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 224 AND record_id = $J1")" = "$facts" ] \
    && pass "retry after commit: Fact_Acct unchanged ($facts rows)" || fail "retry after commit" "ledger duplicated"
fi

# 7b. Background/batch posting: a forced repost runs in iDempiere's own posting transaction (the
#     accounting-processor path). Under current authority the ledger is rebuilt, balanced and
#     attributed afresh; once authority is revoked the repost is refused and the committed ledger
#     is left exactly as it was (no partial delete).
if [ -n "${J1:-}" ]; then
  ledger() { sql "SELECT count(*) || ':' || sum(amtacctdr) || ':' || sum(amtacctcr) FROM fact_acct WHERE ad_table_id = 224 AND record_id = $J1"; }
  attributions() { sql "SELECT count(DISTINCT txid) FROM baobab_native.finance_authority_attribution WHERE source_table = 'GL_Journal' AND source_record_id = $J1"; }
  before=$(ledger); txids=$(attributions)
  run batch_repost authorized action=repost journal_id="$J1" force=true || true
  if [ "$(ledger)" = "$before" ] && posted_ok "$J1" && [ "$(attributions)" -gt "$txids" ]; then
    pass "background forced repost under authority: ledger rebuilt ($before), newly attributed"
  else fail "background forced repost" "ledger $(ledger) vs $before, attributions $(attributions) vs $txids"; fi
  run batch_repost_revoked revoked action=repost journal_id="$J1" force=true || true
  if [ "$(ledger)" = "$before" ] && [ "$(prop batch_repost_revoked post_error)" != "null" ]; then
    pass "background forced repost after revocation: refused, committed ledger intact"
  else fail "background forced repost after revocation" "ledger $(ledger) vs $before"; fi
fi

# 8. Direct SQL bypass of the JVM: refused at COMMIT by the database fence. Each statement
#    must really change one row before COMMIT, so a vacuous no-op can never pass.
fenced() { # label sql expected-tag
  local out
  out=$(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "BEGIN" -c "$2" -c "COMMIT" 2>&1 || true)
  echo "$out" | sed 's/^/    /' >> "$REPORT"
  if echo "$out" | grep -q "^$3\$" && echo "$out" | grep -q "BAOBAB_NATIVE_FINANCE_DENIED"; then
    pass "$1: refused at COMMIT"
  else fail "$1" "not refused by the COMMIT fence"; fi
}
if [ -n "${J1:-}" ]; then
  fenced "direct SQL Fact_Acct insert" "INSERT INTO adempiere.fact_acct SELECT (jsonb_populate_record(f, jsonb_build_object(
      'fact_acct_id', (SELECT max(fact_acct_id) + 1 FROM adempiere.fact_acct),
      'fact_acct_uu', gen_random_uuid()::text, 'ad_table_id', 224, 'record_id', $J1))).*
      FROM adempiere.fact_acct f WHERE ad_client_id = 11 ORDER BY fact_acct_id LIMIT 1" "INSERT 0 1"
fi
run bypass_draft authorized action=journal complete=false post=false || true
B=$(prop bypass_draft journal_id)
if [ -n "$B" ]; then
  fenced "direct SQL completion" "UPDATE adempiere.gl_journal SET docstatus = 'CO', processed = 'Y' WHERE gl_journal_id = $B" "UPDATE 1"
  [ "$(sql "SELECT docstatus FROM gl_journal WHERE gl_journal_id = $B")" = "DR" ] \
    && pass "direct SQL completion left journal $B in DR" || fail "direct SQL completion" "journal $B not DR"
fi

# ---------------------------------------------------------------------------------------------
# P0-04B-05: the other catalogued classes on the real sales flow, receipts-only payments,
# sales-only allocations and derived shipment costing.
# ---------------------------------------------------------------------------------------------
drun() { local name=$1 mode=$2; shift 2; run "$name" "$mode" action=doc "$@"; }
attributed() { # table id class
  [ "$(sql "SELECT count(*) > 0 FROM baobab_native.finance_authority_attribution WHERE lower(source_table) = lower('$1') AND source_record_id = $2 AND operation_class = '$3' AND decision_id IS NOT NULL")" = "t" ]
}
balanced() { # ad_table_id id
  [ "$(sql "SELECT count(*) > 0 AND sum(amtacctdr) = sum(amtacctcr) FROM fact_acct WHERE ad_table_id = $1 AND record_id = $2")" = "t" ]
}
doc_status() { sql "SELECT docstatus || posted FROM $1 WHERE $1_id = $2"; }
doc_posted() { # relation table_id id class
  [ "$(doc_status "$1" "$3")" = "COY" ] && balanced "$2" "$3" && attributed "$1" "$3" "$4"
}
doc_refused() { # relation table_id id result-name
  [ "$(sql "SELECT count(*) FROM $1 WHERE $1_id = $3 AND docstatus IN ('CO','CL')")" = "0" ] &&
  [ "$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = $2 AND record_id = $3")" = "0" ] && baobab_denied "$4"
}
cost_details() { sql "SELECT count(*) FROM m_costdetail cd JOIN m_inoutline l ON l.m_inoutline_id = cd.m_inoutline_id WHERE l.m_inout_id = $1"; }
derived_rows() { sql "SELECT count(*) FROM baobab_native.derived_write_attribution WHERE root_table = 'M_InOut' AND root_record_id = $1"; }

# S1. Valid sales flow: order -> shipment (with derived costing) -> invoice -> receipt (+ allocation).
drun so authorized kind=order qty=2 || true; O=$(prop so id)
if [ -n "$O" ] && [ "$(sql "SELECT docstatus FROM c_order WHERE c_order_id = $O")" = "CO" ] \
   && attributed C_Order "$O" erp.sales-order.complete; then pass "sales order: CO, attributed (order $O)"
else fail "sales order" "order ${O:-none} not completed/attributed"; fi
if [ -n "$O" ]; then
  drun ship authorized kind=shipment order_id="$O" || true; S=$(prop ship id)
  if [ -n "$S" ] && doc_posted m_inout 319 "$S" erp.shipment.complete; then
    pass "shipment: CO, posted, balanced Fact_Acct, attributed (shipment $S)"
  else fail "shipment" "shipment ${S:-none} not completed/posted/attributed"; fi
  if [ -n "$S" ] && [ "$(cost_details "$S")" -gt 0 ] && [ "$(derived_rows "$S")" -gt 0 ] \
     && [ "$(sql "SELECT count(*) FROM baobab_native.finance_authority_attribution WHERE native_table = 'M_CostDetail' AND NOT (operation_class = 'erp.shipment.complete' AND source_table = 'M_InOut' AND source_record_id = $S) AND source_record_id = $S")" = "0" ] \
     && [ "$(sql "SELECT count(*) FROM baobab_native.finance_authority_attribution WHERE operation_class NOT IN ('erp.gl-journal.post','erp.customer-invoice.issue','erp.payment.record','erp.allocation.record','erp.shipment.complete','erp.sales-order.complete')")" = "0" ]; then
    pass "shipment costing: $(cost_details "$S") cost detail(s) derived from the shipment's own authority, no costing decision"
  else fail "shipment costing" "cost details $( [ -n "$S" ] && cost_details "$S"), derived rows $( [ -n "$S" ] && derived_rows "$S")"; fi
  drun inv authorized kind=invoice order_id="$O" || true; I=$(prop inv id)
  if [ -n "$I" ] && doc_posted c_invoice 318 "$I" erp.customer-invoice.issue; then
    pass "customer invoice: CO, posted, balanced Fact_Acct, attributed (invoice $I)"
  else fail "customer invoice" "invoice ${I:-none} not completed/posted/attributed"; fi
  if [ -n "$I" ]; then
    drun rcpt authorized kind=payment invoice_id="$I" || true; R=$(prop rcpt id)
    if [ -n "$R" ] && doc_posted c_payment 335 "$R" erp.payment.record; then
      pass "receipt: CO, posted, balanced Fact_Acct, attributed (payment $R)"
    else fail "receipt" "payment ${R:-none} not completed/posted/attributed"; fi
    AH=$(sql "SELECT max(c_allocationhdr_id) FROM c_allocationline WHERE c_payment_id = ${R:-0}")
    if [ -n "$AH" ] && [ "$(sql "SELECT docstatus FROM c_allocationhdr WHERE c_allocationhdr_id = $AH")" = "CO" ] \
       && attributed C_AllocationHdr "$AH" erp.allocation.record && [ "$(sql "SELECT ispaid FROM c_invoice WHERE c_invoice_id = $I")" = "Y" ]; then
      pass "receipt allocation: CO under its own allocation authority, invoice paid (allocation $AH)"
    else fail "receipt allocation" "allocation ${AH:-none}"; fi
  fi
fi

# S2. Explicit allocation of an unallocated receipt against a second invoice.
drun so2 authorized kind=order qty=1 || true; O2=$(prop so2 id)
drun inv2 authorized kind=invoice order_id="${O2:-0}" || true; I2=$(prop inv2 id)
GT2=$(sql "SELECT grandtotal FROM c_invoice WHERE c_invoice_id = ${I2:-0}")
drun rcpt2 authorized kind=payment amount="${GT2:-1}" || true; R2=$(prop rcpt2 id)
drun alloc authorized kind=allocation invoice_id="${I2:-0}" payment_id="${R2:-0}" || true; A=$(prop alloc id)
if [ -n "$A" ] && [ "$(sql "SELECT docstatus FROM c_allocationhdr WHERE c_allocationhdr_id = $A")" = "CO" ] \
   && attributed C_AllocationHdr "$A" erp.allocation.record; then pass "manual allocation: CO, attributed (allocation $A)"
else fail "manual allocation" "allocation ${A:-none} ($(prop alloc error))"; fi

# S3. Authority lost between draft and completion, for every class.
drun so3 authorized kind=order qty=1 || true; O3=$(prop so3 id)
for mode in revoked wrong_activity other_le expired documentary_hold; do
  drun "d_ord_$mode" authorized kind=order qty=1 complete=false || true
  drun "d_shp_$mode" authorized kind=shipment order_id="${O3:-0}" complete=false || true
  drun "d_inv_$mode" authorized kind=invoice order_id="${O3:-0}" complete=false || true
  drun "d_pay_$mode" authorized kind=payment amount=5 complete=false || true
  for pair in "ord:c_order:259:C_Order" "shp:m_inout:319:M_InOut" "inv:c_invoice:318:C_Invoice" "pay:c_payment:335:C_Payment"; do
    IFS=: read -r k rel tid tbl <<< "$pair"
    D=$(prop "d_${k}_$mode" id)
    if [ -z "$D" ]; then fail "$mode $tbl" "draft not created ($(prop "d_${k}_$mode" error))"; continue; fi
    run "c_${k}_$mode" "$mode" action=completeDoc table="$tbl" id="$D" || true
    if doc_refused "$rel" "$tid" "$D" "c_${k}_$mode" && { [ "$k" != shp ] || [ "$(cost_details "$D")" = "0" ]; }; then
      pass "$mode at $tbl completion: refused, no CO, no ledger$( [ "$k" = shp ] && echo ', no costing')"
    else fail "$mode at $tbl completion" "$tbl $D completed, posted or costed"; fi
  done
done

# S4. Injected failure after ledger AND cost rows, before commit: nothing survives.
drun shp_fail authorized kind=shipment order_id="${O3:-0}" rollbackAfterPost=true || true
SF=$(prop shp_fail id); FF=$(prop shp_fail facts_before_rollback); CF=$(prop shp_fail costs_before_rollback)
if [ -n "$SF" ] && [ "${FF:-0}" -gt 0 ] && [ "${CF:-0}" -gt 0 ] && [ "$(sql "SELECT count(*) FROM m_inout WHERE m_inout_id = $SF")" = "0" ] \
   && [ "$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 319 AND record_id = $SF")" = "0" ] \
   && [ "$(cost_details "$SF")" = "0" ] && [ "$(derived_rows "$SF")" = "0" ]; then
  pass "injected failure after $FF Fact_Acct and $CF cost rows: no shipment, ledger, costing or attribution survives"
else fail "injected shipment failure" "shipment ${SF:-?} facts ${FF:-?} costs ${CF:-?} ($(prop shp_fail error))"; fi

# S5. Retry and background repost of the posted shipment.
if [ -n "${S:-}" ]; then
  F0=$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 319 AND record_id = $S"); C0=$(cost_details "$S"); D0=$(derived_rows "$S")
  run shp_retry authorized action=repostDoc table=M_InOut id="$S" || true
  [ "$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 319 AND record_id = $S")" = "$F0" ] && [ "$(cost_details "$S")" = "$C0" ] \
    && pass "shipment retry after commit: ledger ($F0) and costing ($C0) unchanged" || fail "shipment retry" "duplicated"
  run shp_force authorized action=repostDoc table=M_InOut id="$S" force=true || true
  if [ "$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 319 AND record_id = $S")" = "$F0" ] && balanced 319 "$S" \
     && [ "$(cost_details "$S")" = "$C0" ]; then
    pass "background forced shipment repost under authority: ledger rebuilt ($F0), cost detail not duplicated"
  else fail "background forced shipment repost" "facts/costs changed ($(prop shp_force post_error))"; fi
  run shp_force_rev revoked action=repostDoc table=M_InOut id="$S" force=true || true
  [ "$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 319 AND record_id = $S")" = "$F0" ] && [ "$(cost_details "$S")" = "$C0" ] \
    && [ "$(prop shp_force_rev post_error)" != "null" ] \
    && pass "background forced shipment repost after revocation: refused, ledger and costing intact" \
    || fail "background forced shipment repost after revocation" "state changed"
fi

# S6. Money out and purchase side stay denied on every route.
drun pay_out authorized kind=payment direction=out amount=10 || true
if baobab_denied pay_out && [ -z "$(prop pay_out id)" ] \
   && [ "$(sql "SELECT count(*) FROM c_payment WHERE isreceipt = 'N' AND description LIKE 'Baobab Gate D%'")" = "0" ]; then
  pass "outbound vendor payment: refused at creation"
else fail "outbound vendor payment" "created ($(prop pay_out id))"; fi
VP=$(sql "SELECT min(c_payment_id) FROM c_payment WHERE ad_client_id = 11 AND isreceipt = 'N' AND docstatus IN ('CO','CL')")
if [ -n "$VP" ]; then
  VF=$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 335 AND record_id = $VP")
  run vp_repost authorized action=repostDoc table=C_Payment id="$VP" force=true || true
  [ "$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 335 AND record_id = $VP")" = "$VF" ] && [ "$(prop vp_repost post_error)" != "null" ] \
    && pass "outbound payment posting (accounting path): refused, ledger unchanged" || fail "outbound payment posting" "ledger changed"
fi
VI=$(sql "SELECT min(c_invoice_id) FROM c_invoice WHERE ad_client_id = 11 AND issotrx = 'N' AND docstatus = 'CO' AND ispaid = 'N'")
if [ -n "$VI" ] && [ -n "${R2:-}" ]; then
  drun alloc_vendor authorized kind=allocation invoice_id="$VI" payment_id="$R2" amount=1 || true
  baobab_denied alloc_vendor && [ "$(sql "SELECT count(*) FROM c_allocationline WHERE c_invoice_id = $VI AND c_payment_id = $R2")" = "0" ] \
    && pass "allocation against a vendor invoice: refused" || fail "vendor allocation" "allocated"
fi
MR=$(sql "SELECT min(m_inout_id) FROM m_inout WHERE ad_client_id = 11 AND issotrx = 'N' AND docstatus IN ('CO','CL')")
if [ -n "$MR" ]; then
  MF=$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 319 AND record_id = $MR")
  run mr_repost authorized action=repostDoc table=M_InOut id="$MR" force=true || true
  [ "$(sql "SELECT count(*) FROM fact_acct WHERE ad_table_id = 319 AND record_id = $MR")" = "$MF" ] && [ "$(prop mr_repost post_error)" != "null" ] \
    && pass "purchase material receipt posting: refused, ledger unchanged" || fail "purchase receipt posting" "ledger changed"
fi

# S7. Direction is immutable; direct SQL costing, outbound completion and payment ledger are fenced.
if [ -n "${R:-}" ]; then
  out=$(psql "$DATABASE_URL" -c "UPDATE adempiere.c_payment SET isreceipt = 'N' WHERE c_payment_id = $R" 2>&1 || true)
  echo "$out" | grep -q "cannot change direction" && pass "receipt direction flip by SQL: refused" || fail "direction flip" "$out"
  fenced "direct SQL outbound completed payment" "INSERT INTO adempiere.c_payment SELECT (jsonb_populate_record(p, jsonb_build_object(
      'c_payment_id', (SELECT max(c_payment_id) + 1 FROM adempiere.c_payment), 'c_payment_uu', gen_random_uuid()::text,
      'isreceipt', 'N', 'docstatus', 'CO', 'documentno', 'GATE-D-OUT'))).* FROM adempiere.c_payment p WHERE c_payment_id = $R" "INSERT 0 1"
  fenced "direct SQL payment Fact_Acct insert" "INSERT INTO adempiere.fact_acct SELECT (jsonb_populate_record(f, jsonb_build_object(
      'fact_acct_id', (SELECT max(fact_acct_id) + 1 FROM adempiere.fact_acct), 'fact_acct_uu', gen_random_uuid()::text))).*
      FROM adempiere.fact_acct f WHERE ad_table_id = 335 AND record_id = $R LIMIT 1" "INSERT 0 1"
fi
if [ -n "${S:-}" ]; then
  fenced "direct SQL M_CostDetail insert" "INSERT INTO adempiere.m_costdetail SELECT (jsonb_populate_record(cd, jsonb_build_object(
      'm_costdetail_id', (SELECT max(m_costdetail_id) + 1 FROM adempiere.m_costdetail), 'm_costdetail_uu', gen_random_uuid()::text))).*
      FROM adempiere.m_costdetail cd JOIN adempiere.m_inoutline l ON l.m_inoutline_id = cd.m_inoutline_id WHERE l.m_inout_id = $S LIMIT 1" "INSERT 0 1"
  fenced "direct SQL M_Cost update" "UPDATE adempiere.m_cost c SET currentqty = currentqty + 1 FROM adempiere.m_costdetail cd
      JOIN adempiere.m_inoutline l ON l.m_inoutline_id = cd.m_inoutline_id
      WHERE l.m_inout_id = $S AND c.m_product_id = cd.m_product_id AND c.c_acctschema_id = cd.c_acctschema_id
        AND c.m_costelement_id = cd.m_costelement_id AND c.ad_client_id = 11 AND c.ad_org_id = 0 AND c.m_attributesetinstance_id = 0" "UPDATE 1"
fi

note "Gate D failures: $FAILURES"
[ "$FAILURES" = 0 ]
