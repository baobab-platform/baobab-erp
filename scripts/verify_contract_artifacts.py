#!/usr/bin/env python3
"""Verify deployed wheel/JAR assets, private OSGi wiring and wire vectors.

A source-tree import is not packaging evidence. Inspect actual artifacts and
run validators from the installed wheel or a standalone isolated Java loader.
This is synthetic compatibility proof, never a legal/native support grant.
"""
import argparse
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ROOT = ROOT / 'modules/shared_contracts/data'
EXPECTED = {str(p.relative_to(EXPECTED_ROOT)): p.read_bytes() for p in EXPECTED_ROOT.rglob('*') if p.is_file()}


def verify_bundle(path: Path, prefix: str) -> None:
    with zipfile.ZipFile(path) as archive:
        actual = {name[len(prefix):]: archive.read(name) for name in archive.namelist()
                  if name.startswith(prefix) and not name.endswith('/')}
        if actual != EXPECTED:
            raise ValueError('Packaged contract bytes/provenance/inventory differ')
        if prefix == 'shared-contracts/':
            # Shade must not export/import the private validator/Jackson stack.
            manifest = archive.read('META-INF/MANIFEST.MF').decode().replace('\r\n ', '').replace('\n ', '')
            fields = dict(line.split(': ', 1) for line in manifest.splitlines() if ': ' in line)
            if fields.get('Bundle-SymbolicName') != 'org.nabhold.baobab.erp.integration':
                raise ValueError('OSGi bundle identity changed')
            for field in ['Import-Package', 'Export-Package']:
                for library in ['com.networknt', 'com.fasterxml.jackson', 'com.ethlo', 'org.slf4j', '.internal.']:
                    if library in fields.get(field, ''):
                        raise ValueError('Private validator dependency leaked into OSGi wiring')
            if 'org/nabhold/baobab/erp/integration/internal/networknt/schema/Schema.class' not in archive.namelist():
                raise ValueError('Private validator dependency missing')
            for name in archive.namelist():
                if name.startswith('org/nabhold/baobab/erp/') and '/internal/' not in name and name.endswith('.class'):
                    if int.from_bytes(archive.read(name)[6:8], 'big') > 61:
                        raise ValueError('Native code no longer targets Java 17')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jar', type=Path)
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--vectors', type=Path, default=ROOT / 'tests/fixtures/authority-contract-cases.json')
    parser.add_argument('--runtime-python', type=Path)
    args = parser.parse_args()
    if bool(args.jar) == bool(args.wheel):
        parser.error('Select exactly one actual artifact')
    if args.jar:
        verify_bundle(args.jar, 'shared-contracts/')
        driver = ['java', '-cp', str(args.jar.resolve()), 'org.nabhold.baobab.erp.integration.PinnedSharedSchemas']
        subprocess.run(driver + ['--self-test'], check=True)
        subprocess.run(driver + ['--conformance', str(args.vectors.resolve())], check=True)
    else:
        if not args.runtime_python:
            parser.error('Wheel verification requires its isolated installed Python')
        verify_bundle(args.wheel, 'shared_contracts/data/')
        probe = '''import json, sys
from pathlib import Path
from shared_contracts import ContractViolation, validate_contract
cases = json.loads(Path(sys.argv[1]).read_bytes())
for case in cases:
    try:
        validate_contract(case['contract'], case['instance'])
        valid = True
    except ContractViolation:
        valid = False
    if valid != case['valid']:
        raise RuntimeError('Installed wheel wire mismatch: ' + case['name'])
print('Installed wheel vectors verified:', len(cases))
'''
        # Preserve the venv executable symlink; resolving it selects the host
        # interpreter and loses the installed wheel's isolated site-packages.
        subprocess.run([str(args.runtime_python.absolute()), '-I', '-c', probe, str(args.vectors.resolve())], cwd='/tmp', check=True)
    print('Packaged contract artifact verified')


if __name__ == '__main__':
    main()
