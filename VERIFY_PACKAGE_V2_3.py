"""Independent standard-library SHA-256 inventory check for the V2.3 release."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parent
MANIFEST=ROOT/'MANIFEST.json'


def main():
    m=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if m.get('schema')!='R1_15A2_V23_CONTENT_MANIFEST_V1':
        raise RuntimeError('WRONG_RELEASE_MANIFEST')
    expected=m['files']
    actual={str(p.relative_to(ROOT)).replace('\\','/') for p in ROOT.rglob('*') if p.is_file()
            and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts
            and p.name!='SHA256SUMS.txt' and p.name!='MANIFEST.json'}
    if actual!=set(expected):
        raise RuntimeError('FILE_SET_MISMATCH missing='+str(sorted(set(expected)-actual))+
                           ' extra='+str(sorted(actual-set(expected))))
    for name,record in expected.items():
        p=ROOT/name
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if digest!=record['sha256'] or p.stat().st_size!=record['size_bytes']:
            raise RuntimeError('CONTENT_MISMATCH:'+name)
    lines=(ROOT/'SHA256SUMS.txt').read_text(encoding='ascii').splitlines()
    if len(lines)!=len(expected)+1:
        raise RuntimeError('SHA256SUMS_LENGTH_MISMATCH')
    known={}
    for line in lines:
        digest,name=line.split('  ',1)
        if name in known or name not in expected and name!='MANIFEST.json':
            raise RuntimeError('SHA256SUMS_UNEXPECTED_NAME:'+name)
        known[name]=digest
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('SHA256SUMS_HASH_MISMATCH:'+name)
    if set(known)!=set(expected)|{'MANIFEST.json'}:
        raise RuntimeError('SHA256SUMS_FILE_SET_MISMATCH')
    print('V2.3 CLEAN PACKAGE FILES AND SHA256: PASS; files='+str(len(expected)))
    return 0


if __name__=='__main__':
    sys.exit(main())
