#!/usr/bin/env python3
"""Read-only ERP registration preflight; never activate or publish authority.

Uses the exact clean Shared checkout named by contracts.lock.yaml. Output is a
construction report, not a runtime profile, support attestation or readiness
decision. --require-registrable fails if any provider has no canonical support.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


def source_dirty(shared_checkout, repository=ROOT):
    """Whether ERP's own source differs from its revision. The supplied Shared checkout (verified clean separately) may sit inside the
    ERP tree as an untracked nested repository; it is not ERP source and must not make every report ineligible."""
    command = ['git', '-C', str(repository), 'status', '--porcelain']
    try:
        relative = Path(shared_checkout).resolve().relative_to(Path(repository).resolve())
        command += ['--', '.', f':(exclude){relative.as_posix()}']
    except ValueError:
        pass  # outside the repository: nothing to exclude
    return bool(subprocess.check_output(command, text=True).strip())


def load_shared(checkout, repository=ROOT):
    lock = yaml.safe_load((repository / 'contracts.lock.yaml').read_text())
    source = lock['source']
    if source['repository'] != 'baobab-platform/shared':
        raise ValueError('unapproved contract authority')
    commit = subprocess.check_output(
        ['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != source['commit']:
        raise ValueError('Shared checkout does not match the immutable ERP pin')
    if subprocess.check_output(
            ['git', '-C', str(checkout), 'status', '--porcelain', '--untracked-files=all'], text=True).strip():
        raise ValueError('Shared checkout must be clean, including untracked files')
    spec = importlib.util.spec_from_file_location(
        'erp_pinned_capability_catalogue', checkout / 'scripts/capability_catalogue.py')
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module, commit


def prepare(module, checkout, declaration, repository=ROOT):
    contracts = module.Contracts(checkout / 'contracts')
    errors = module.validate_catalogue(contracts)
    errors += module.validate_declaration(contracts, declaration, repository, 'baobab-erp')
    if errors:
        raise ValueError('; '.join(errors))
    registrations, excluded = [], []
    for provider in sorted(declaration['providers'], key=lambda p: p['provider_key']):
        for support in provider['support']:
            if support['implementation_status'] != 'IMPLEMENTED':
                excluded.append({
                    'provider_key': provider['provider_key'],
                    'capability_key': support['capability_key'],
                    'implementation_status': support['implementation_status'],
                })
        if any(s['implementation_status'] == 'IMPLEMENTED' for s in provider['support']):
            # Shared validates and generates the wire format; no ERP shadow schema.
            registrations.append(module.generate_registration(
                contracts, declaration, provider['provider_key'], 'DRAFT'))
    return contracts, registrations, excluded


def compare_exports(module, contracts, registrations, exports):
    """Compare reviewed EngineRegistration exports, not CP lifecycle/health.

    Input is a JSON array of canonical EngineRegistration documents. Missing,
    extra, duplicate and substituted declarations all count as drift. This
    offline comparison has no freshness or runtime-authority claim.
    """
    if not isinstance(exports, list):
        raise ValueError('registration export must be a JSON array')
    actual = {}
    for entry in exports:
        errors = contracts.errors(module.REGISTRATION_REF, entry)
        if errors:
            raise ValueError('invalid registration export: ' + '; '.join(errors))
        key = entry['provider']['provider_key']
        if entry['repository'] != 'baobab-erp' or key in actual:
            raise ValueError('foreign or duplicate registration export')
        actual[key] = entry
    expected = {entry['provider']['provider_key']: entry for entry in registrations}
    drift = []
    for key in sorted(set(actual) | set(expected)):
        if key not in expected:
            drift.append({'provider_key': key, 'reason': 'UNDECLARED_SUPPORT'})
        elif key not in actual:
            drift.append({'provider_key': key, 'reason': 'MISSING_REGISTRATION'})
        else:
            if actual[key] != expected[key]:
                drift.append({'provider_key': key, 'reason': 'DECLARATION_MISMATCH'})
    return drift


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shared-checkout', type=Path, required=True)
    parser.add_argument('--registration-export', type=Path)
    parser.add_argument('--require-registrable', action='store_true')
    args = parser.parse_args(argv)
    try:
        module, commit = load_shared(args.shared_checkout.resolve())
        path = ROOT / '.baobab/capability-provider.yaml'
        raw = path.read_bytes()
        declaration = yaml.safe_load(raw)
        contracts, registrations, excluded = prepare(
            module, args.shared_checkout.resolve(), declaration)
        drift = compare_exports(module, contracts, registrations,
                                json.loads(args.registration_export.read_text())) if args.registration_export else None
        eligible = {r['provider']['provider_key'] for r in registrations}
        blocked = sorted(p['provider_key'] for p in declaration['providers'] if p['provider_key'] not in eligible)
        report = {
            'classification': 'CONSTRUCTION_PREFLIGHT',
            'shared_commit': commit,
            'declaration_sha256': hashlib.sha256(raw).hexdigest(),
            'source_revision': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
            'source_dirty': source_dirty(args.shared_checkout),
            'draft_registrations': registrations,
            'excluded_support': excluded,
            'blocked_providers': blocked,
            'registration_drift': drift,
            'runtime_authority_verified': False,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2 if drift or (args.require_registrable and blocked) else 0
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        print(f'publication preflight denied: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
