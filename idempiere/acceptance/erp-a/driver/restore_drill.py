#!/usr/bin/env python3
"""DEV-12: restore actual ERP-A native PG17 state, never a live DR approval.

The owner harness has already run its real iDempiere/JVM scenarios. Quiesce
that JVM, restore its database into a fresh run-owned sibling, compare native
state/trigger ownership and exercise the restored SQL COMMIT veto. No dump or
database content is exported. A passing receipt requires independently observed
sibling database and archive deletion. This does not boot a restored JVM or
qualify an upgrade, physical PG migration, RPO/RTO or external provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

from erpalib import Compose

TABLES = (
    'adempiere.ad_client', 'adempiere.ad_org', 'adempiere.c_order',
    'adempiere.c_invoice', 'adempiere.fact_acct', 'adempiere.m_transaction',
    'adempiere.m_costdetail', 'baobab_native.native_placement',
    'baobab_native.document_provenance', 'baobab_native.finance_authority_attribution',
    'baobab_native.payment_execution_evidence', 'baobab_native.payment_execution_binding',
)
CASES = (
    'DEV12-ERP-PG17', 'DEV12-ERP-NATIVE-STATE-RESTORE',
    'DEV12-ERP-NATIVE-GUARD-RESTORE', 'DEV12-ERP-RESTORED-COMMIT-DENIAL',
    'DEV12-ERP-RESTORE-RESOURCE-DELETION',
)


def require(ok, code):
    if not ok:
        raise ValueError(code)


def identity(environment, project, source):
    require(environment == 'integration', 'DEV12_ISOLATED_INTEGRATION_REQUIRED')
    require(isinstance(project, str) and re.fullmatch(r'baobab-erp-a-[0-9a-f]{16}', project),
            'DEV12_RUN_OWNERSHIP_REQUIRED')
    require(isinstance(source, str) and re.fullmatch(r'[0-9a-f]{40}', source),
            'DEV12_SOURCE_REQUIRED')


def snapshot(c, database):
    """Hash native rows without exporting their private values or identifiers."""
    result = {}
    for table in TABLES:
        # Relation names are a static owner allowlist, never caller input.
        row = c.sql('erpdb', 'postgres', database,
                    "SELECT count(*)::text, md5(coalesce(string_agg(h, '' ORDER BY h COLLATE \"C\"), '')) "
                    f"FROM (SELECT md5(row_to_json(t)::text) AS h FROM {table} t) s")
        require(len(row) == 1 and len(row[0]) == 2, 'DEV12_NATIVE_SNAPSHOT_INVALID')
        require(row[0][0].isdigit() and re.fullmatch(r'[0-9a-f]{32}', row[0][1]),
                'DEV12_NATIVE_SNAPSHOT_INVALID')
        result[table] = row[0]
    require(int(result['adempiere.fact_acct'][0]) > 0 and
            int(result['baobab_native.native_placement'][0]) >= 2 and
            int(result['baobab_native.finance_authority_attribution'][0]) > 0,
            'DEV12_NATIVE_SCENARIOS_REQUIRED')
    return result


def guards(c, database):
    # Compare trigger state, constraint deferral, function security/ownership
    # and runtime-role ownership after pg_restore; do not use --no-owner.
    raw = c.scalar('erpdb', 'postgres', database, """
      SELECT md5(coalesce(string_agg(v, '' ORDER BY v COLLATE "C"), ''))
      FROM (
        SELECT row_to_json(x)::text AS v FROM (
          SELECT n.nspname, cl.relname, t.tgname, t.tgenabled,
                 t.tgdeferrable, t.tginitdeferred, pg_get_triggerdef(t.oid) AS definition,
                 p.proname, p.prosecdef, pg_get_userbyid(p.proowner) AS function_owner,
                 pg_get_userbyid(cl.relowner) AS table_owner,
                 pg_get_functiondef(p.oid) AS function_definition
          FROM pg_trigger t JOIN pg_class cl ON cl.oid=t.tgrelid
          JOIN pg_namespace n ON n.oid=cl.relnamespace
          JOIN pg_proc p ON p.oid=t.tgfoid
          WHERE NOT t.tgisinternal AND n.nspname IN ('adempiere','baobab_native')
        ) x
      ) s
    """)
    require(isinstance(raw, str) and re.fullmatch(r'[0-9a-f]{32}', raw),
            'DEV12_NATIVE_GUARD_SNAPSHOT_INVALID')
    count = c.scalar('erpdb', 'postgres', database, """
      SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='adempiere' AND c.relname='c_order'
        AND t.tgname='baobab_completion_commit_fence' AND t.tgenabled='O'
        AND t.tgdeferrable AND t.tginitdeferred
    """)
    require(count == '1', 'DEV12_DEFERRED_COMMIT_FENCE_REQUIRED')
    return raw


def restored_denial(c, database):
    record = c.scalar('erpdb', 'postgres', database, """
      SELECT c_order_id FROM adempiere.c_order
      WHERE ad_client_id=11 AND docstatus='DR' AND issotrx='N'
      ORDER BY c_order_id DESC LIMIT 1
    """)
    require(record.isdigit() and int(record) > 0, 'DEV12_NATIVE_DRAFT_REQUIRED')
    before = snapshot(c, database)
    denied = c.psql('erpdb', 'adempiere', database,
                   f"BEGIN; UPDATE adempiere.c_order SET docstatus='CO', processed='Y' "
                   f"WHERE c_order_id={record}; COMMIT;", check=False, quiet=False)
    require(denied.returncode != 0 and 'UPDATE 1' in denied.stdout.splitlines()
            and 'BAOBAB_NATIVE_FINANCE_DENIED' in denied.stderr,
            'DEV12_RESTORED_COMMIT_VETO_MISSING')
    require(snapshot(c, database) == before, 'DEV12_RESTORED_DENIAL_CHANGED_STATE')


def drill(c, source):
    identity(os.environ.get('BAOBAB_ENVIRONMENT'), os.environ.get('ERP_A_PROJECT'), source)
    version = c.scalar('erpdb', 'postgres', 'idempiere', 'SHOW server_version_num')
    require(version.isdigit() and 170000 <= int(version) < 180000, 'DEV12_PG17_REQUIRED')
    nonce = uuid.uuid4().hex
    database = 'baobab_dev12_' + nonce
    archive = '/tmp/baobab-dev12-' + nonce + '.dump'
    require(c.scalar('erpdb', 'postgres', 'postgres',
                     f"SELECT count(*) FROM pg_database WHERE datname='{database}'") == '0',
            'DEV12_RESTORE_DATABASE_ALREADY_EXISTS')
    # Stop the actual JVM before fingerprinting/dumping. Other native harness
    # writers have completed; no cross-engine database is snapshotted here.
    c.run('stop', 'erp')
    before, native_guards = snapshot(c, 'idempiere'), guards(c, 'idempiere')
    created = False
    try:
        c.run('exec', '-T', 'erpdb', 'pg_dump', '-U', 'postgres', '-d', 'idempiere',
              '--format=custom', '--file', archive)
        # Durable cleanup intent precedes create; final harness down removes
        # all owned DB storage even if this process is killed between steps.
        created = True
        c.run('exec', '-T', 'erpdb', 'createdb', '-U', 'postgres', '--template=template0', database)
        c.run('exec', '-T', 'erpdb', 'pg_restore', '-U', 'postgres', '-d', database,
              '--exit-on-error', '--single-transaction', archive)
        require(snapshot(c, database) == before, 'DEV12_NATIVE_RESTORE_MISMATCH')
        require(guards(c, database) == native_guards, 'DEV12_NATIVE_GUARD_RESTORE_MISMATCH')
        restored_denial(c, database)
    finally:
        try:
            if created:
                c.run('exec', '-T', 'erpdb', 'dropdb', '-U', 'postgres', '--if-exists', '--force', database)
        finally:
            c.run('exec', '-T', 'erpdb', 'rm', '-f', archive)
    require(c.scalar('erpdb', 'postgres', 'postgres',
                     f"SELECT count(*) FROM pg_database WHERE datname='{database}'") == '0',
            'DEV12_RESTORE_DATABASE_SURVIVED')
    c.run('exec', '-T', 'erpdb', 'test', '!', '-e', archive)
    return {
        'schema': 'dev12-erp-native-restore.v1', 'source_sha': source,
        'evidence_class': 'REAL_COMPONENT_SYNTHETIC_DATA',
        'scope': 'PG17_LOGICAL_RESTORE_OF_ACTUAL_IDEMPIERE_NATIVE_STATE',
        'cases': {case: 'PASS' for case in CASES},
        'native_state_sha256': hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
        'restored_jvm_qualified': False, 'physical_upgrade_qualified': False,
        'protected_acceptance': False, 'production_authorized': False,
        'provider_qualified': False, 'rpo_rto_accepted': False,
        'cleanup': 'RESTORE_DATABASE_AND_ARCHIVE_DELETION_VERIFIED',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compose', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    target, digest = args.out / 'dev12-native-restore.json', args.out / 'dev12-native-restore.sha256.json'
    target.unlink(missing_ok=True)
    digest.unlink(missing_ok=True)
    try:
        report = drill(Compose(args.compose), os.environ.get('ERP_COMMIT', ''))
        raw = (json.dumps(report, indent=2) + '\n').encode()
        target.write_bytes(raw)
        digest.write_text(json.dumps({'sha256': hashlib.sha256(raw).hexdigest()}) + '\n')
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
        # Never export subprocess diagnostics, native identifiers or dump data.
        raise SystemExit('DEV12_NATIVE_RESTORE_FAILED') from None


if __name__ == '__main__':
    main()
