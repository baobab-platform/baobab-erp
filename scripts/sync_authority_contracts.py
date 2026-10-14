#!/usr/bin/env python3
"""P0-04A: copy the complete immutable Shared schema closure to both runtimes.

Git blobs, not mutable checkout files, are authoritative. Validate every path
before replacing generated directories. Runtime resolution never downloads a
schema. Use --check in CI to prove bytes, provenance and absence of stale files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    ROOT / 'modules/shared_contracts/data',
    ROOT / 'idempiere/extensions/org.nabhold.baobab.erp.integration/src/main/resources/shared-contracts',
)
ENTRIES = {
    # Legacy assessment wire accepts an opaque string; current stored Context
    # identifiers independently use the canonical UUID grammar.
    'context_uuid': ('control-plane/v1/domain.schema.json', 'uuid'),
    'legal_request': ('organisation/v2/legal-actor-enforcement.schema.json', 'AssessLegalActorRequest'),
    'legal_response': ('organisation/v2/legal-actor-enforcement.schema.json', 'AssessLegalActorResponse'),
    'documentary_request': ('admission/v2/documentary-restriction.schema.json', 'DocumentaryRestrictionAssessmentRequest'),
    'documentary_response': ('admission/v2/documentary-restriction.schema.json', 'DocumentaryRestrictionAssessmentResponse'),
    'context_request': ('control-plane/v1/platform-context.schema.json', 'PlatformContextResolveRequest'),
    'context_response': ('control-plane/v1/platform-context.schema.json', 'PlatformContext'),
    'context_validation': ('control-plane/v1/platform-context.schema.json', 'PlatformContextValidation'),
    'erp_assignment': ('control-plane/v1/erp-assignment.schema.json', 'ErpAssignment'),
    'posting_request': ('erp/v2/posting-authority.schema.json', 'PostingAuthorityRequest'),
    'posting_decision': ('erp/v2/posting-authority.schema.json', 'PostingAuthorityDecision'),
}


def generate(shared: Path) -> dict[str, bytes]:
    lock = yaml.safe_load((ROOT / 'contracts.lock.yaml').read_text())
    pin = lock['source']['commit']
    def git(*args: str) -> bytes:
        return subprocess.check_output(['git', '-C', str(shared), *args])
    if git('rev-parse', 'HEAD').decode().strip() != pin:
        raise ValueError('Shared checkout must be at the exact lock pin')
    documents: dict[str, bytes] = {}
    def discover(path: str) -> None:
        if path in documents:
            return
        if not path.startswith('contracts/') or not path.endswith('.schema.json'):
            raise ValueError(f'Unexpected schema reference: {path}')
        if path not in lock['contracts']:
            raise ValueError(f'Declare consumed closure path in contracts.lock.yaml: {path}')
        raw = git('show', f'{pin}:{path}')
        schema = json.loads(raw)
        documents[path] = raw
        def walk(node: object) -> None:
            if isinstance(node, dict):
                for key in ('$ref', '$dynamicRef'):
                    ref = node.get(key)
                    if isinstance(ref, str):
                        file = ref.split('#', 1)[0]
                        if file:
                            if urlsplit(file).scheme or file.startswith('/'):
                                raise ValueError(f'Remote/absolute schema reference forbidden: {ref}')
                            discover(posixpath.normpath(posixpath.join(posixpath.dirname(path), file)))
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)
        walk(schema)
    roots = sorted({'contracts/' + path for path, _ in ENTRIES.values()})
    for path in roots:
        discover(path)
    entries = {}
    for name, (path, definition) in ENTRIES.items():
        schema = json.loads(documents['contracts/' + path])
        if definition not in schema['$defs']:
            raise ValueError(f'Missing owned entry point: {name}')
        entries[name] = schema['$id'] + '#/$defs/' + definition
    manifest = {
        'repository': lock['source']['repository'], 'commit': pin,
        'roots': roots, 'entries': entries,
        'files': {path: hashlib.sha256(raw).hexdigest() for path, raw in sorted(documents.items())},
    }
    return {**documents, 'provenance.json': (json.dumps(manifest, indent=2) + '\n').encode()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shared-checkout', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    files = generate(args.shared_checkout)
    for target in TARGETS:
        if args.check:
            actual = {str(p.relative_to(target)): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            if actual != files:
                raise ValueError(f'Generated bundle differs (including inventory): {target}')
        else:
            # Only generated assets are replaced; source Python/Java stays outside.
            if target.exists():
                shutil.rmtree(target)
            for path, raw in files.items():
                output = target / path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(raw)
    print(f'Exact Shared closure verified: {len(files) - 1} schemas, two runtimes')


if __name__ == '__main__':
    main()
