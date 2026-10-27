"""Offline package integrity verifier. No Visum instance or other writes needed."""
from pathlib import Path
import csv
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parent
EXCLUDED = {'MANIFEST_V238.json', 'SHA256SUMS_V238.txt'}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def payload_files():
    for p in ROOT.rglob('*'):
        rel = p.relative_to(ROOT)
        if (not p.is_file() or p.suffix == '.pyc' or
                any(x in ('__pycache__', '.pytest_cache') for x in rel.parts) or
                str(rel) in EXCLUDED):
            continue
        yield p, rel.as_posix()


def verify():
    manifest = json.loads((ROOT / 'MANIFEST_V238.json').read_text(encoding='utf-8'))
    expected = manifest['files']
    actual = {rel: digest(p) for p, rel in payload_files()}
    problems = []
    for rel in sorted(set(expected) | set(actual)):
        if expected.get(rel) != actual.get(rel):
            problems.append('PAYLOAD_MISSING_CHANGED_OR_EXTRA: ' + rel)
    sums = (ROOT / 'SHA256SUMS_V238.txt').read_text(encoding='utf-8').splitlines()
    listed = dict((name, sha) for sha, name in (line.split('  ', 1) for line in sums))
    if listed != expected:
        problems.append('SHA256SUMS_MANIFEST_DISAGREEMENT')
    cfg = json.loads((ROOT / 'R1_15A2_CONFIG_V2_3_8.json').read_text(encoding='utf-8'))
    if cfg['apply'] is not False or cfg['two_mode']['design_only'] is not True:
        problems.append('DESIGN_ONLY_CONTRACT')
    if cfg['supply']['gap_readback']['maximum_gap'] != 0.005:
        problems.append('EPSILON_CHANGED')
    if cfg['supply']['equivalent_seconds_per_addval1'] != 10.0:
        problems.append('ADDVAL1_SECONDS_CHANGED')
    if len(set(cfg['supply']['passenger_dsegs'])) != 12:
        problems.append('DSeg_SCOPE_CHANGED')
    records = []
    for name in ('R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv',
                 'R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_90.csv'):
        with (ROOT / 'authorities' / name).open(encoding='utf-8-sig', newline='') as h:
            records.extend(csv.DictReader(h))
    if (len(records), sum(r['role']=='CALIBRATION' for r in records),
            sum(r['role']=='VALIDATION' for r in records)) != (498, 462, 36):
        problems.append('OBSERVATION_SCOPE_CHANGED')
    integrity = json.loads((ROOT / 'V238_SOURCE_INTEGRITY.json').read_text(encoding='utf-8'))
    for rel, sha in integrity['protected_unchanged_files'].items():
        if actual.get(rel) != sha:
            problems.append('PROTECTED_AUTHORITY_OR_NUMERICAL_CODE_CHANGED: ' + rel)
    return {'status': 'FAIL' if problems else 'PASS', 'checked_files': len(actual),
            'protected_files': len(integrity['protected_unchanged_files']),
            'apply_permitted': False, 'live_visum_tested': False, 'problems': problems}


if __name__ == '__main__':
    try:
        result = verify()
    except Exception as exc:
        result = {'status': 'FAIL', 'error': type(exc).__name__ + ': ' + str(exc)}
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['status']=='PASS' else 1)
