from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parent

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    m=json.loads((ROOT/'MANIFEST.json').read_text(encoding='utf-8'))
    assert m['schema']=='R1_15A2_V233_COM_API_MANIFEST_V1'
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts and not p.name.endswith('.pyc') and p.name not in ('MANIFEST.json','SHA256SUMS.txt')}
    assert actual==set(m['files']), (sorted(actual-set(m['files'])),sorted(set(m['files'])-actual))
    for name,sha in m['files'].items(): assert digest(ROOT/name)==sha,name
    for line in (ROOT/'SHA256SUMS.txt').read_text(encoding='ascii').splitlines():
        sha,name=line.split('  ',1);assert digest(ROOT/name)==sha,name
    assert m['observations']==dict(total=498,calibration=462,validation=36)
    assert m['live_visum_tested'] is False
    print('V2.3.3 MANIFEST PASS files='+str(len(actual)))
if __name__=='__main__':main()
