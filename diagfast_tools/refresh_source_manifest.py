"""Developer-only: seal additive source files. Does NOT touch protected originals.
Run BEFORE final tests. Never refresh in response to a failed integrity check.
"""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    base=json.loads((ROOT/'DIAGFAST_V1_BASE_MANIFEST.json').read_text('utf-8'))
    changed=[]
    for name,sha in base['files'].items():
        p=ROOT/name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:changed.append(name)
    if changed:raise RuntimeError('ORIGINAL_FILES_CHANGED:'+','.join(changed))
    names=['DIAGFAST_V1_BASE_MANIFEST.json']
    for p in ROOT.rglob('*.py'):
        rel=p.relative_to(ROOT).as_posix()
        if rel not in base['files'] and '__pycache__' not in p.parts:
            names.append(rel)
    import sys
    sys.path.insert(0,str(ROOT))
    from r1_15a2_diagfast_v1 import RELEASE
    manifest={'schema':'R1_DIAGFAST_RELEASE_V1','release':RELEASE,
       'scope':'IMMUTABLE_SOURCE_IDENTITY_TEST_STATUS_IS_SEPARATE',
       'files':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(set(names))}}
    (ROOT/'DIAGFAST_V1_RELEASE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print('SEALED',len(names),'sources; originals verified',len(base['files']))

if __name__=='__main__':main()
