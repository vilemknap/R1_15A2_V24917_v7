"""Read-only hash/inventory verification of the delivered V2.2 package."""
from pathlib import Path
import hashlib
import json
import sys


def verify(root=None):
    root = Path(root or Path(__file__).resolve().parent)
    manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    errors = []
    for rel, expected in manifest['files'].items():
        path = root / rel
        if not path.is_file():
            errors.append('MISSING:' + rel)
        elif path.stat().st_size != expected['size_bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
            errors.append('HASH_OR_SIZE:' + rel)
    actual = {str(p.relative_to(root)).replace('\\', '/') for p in root.rglob('*')
              if p.is_file() and not any(x in p.parts for x in ('__pycache__', '.pytest_cache', 'R1_15A2_V2_2_RUNS'))}
    allowed = set(manifest['files']) | {'MANIFEST.json', 'SHA256SUMS.txt'}
    errors += ['UNDECLARED:' + rel for rel in sorted(actual - allowed)]
    result = {'status': 'PASS' if not errors else 'FAIL', 'file_count': len(manifest['files']), 'errors': errors,
              'verification': 'FILE_HASH_AND_INVENTORY_ONLY_NOT_LIVE_VISUM'}
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    sys.exit(0 if verify()['status'] == 'PASS' else 1)
