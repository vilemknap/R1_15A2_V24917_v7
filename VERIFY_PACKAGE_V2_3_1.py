# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    m=json.loads((ROOT/'MANIFEST.json').read_text(encoding='utf-8'))
    assert m['schema']=='R1_15A2_V231_CSD408_MANIFEST_V1'
    expected=m['files']
    real={str(x.relative_to(ROOT)).replace('\\','/') for x in ROOT.rglob('*') if x.is_file()
          and '__pycache__' not in x.parts and '.pytest_cache' not in x.parts
          and x.name not in ('MANIFEST.json','SHA256SUMS.txt') and not x.name.endswith('.pyc')}
    assert real==set(expected),(len(real),len(expected),sorted(real-set(expected)),sorted(set(expected)-real))
    for name,dig in expected.items():
        assert sha(ROOT/name)==dig,name
    for line in (ROOT/'SHA256SUMS.txt').read_text(encoding='ascii').splitlines():
        digest,name=line.split('  ',1)
        assert sha(ROOT/name)==digest,name
    assert m['observations']['total']==408
    print('V2.3.1 CLEAN PACKAGE MANIFEST SHA256: PASS; files='+str(len(expected)))
if __name__=='__main__':main()
