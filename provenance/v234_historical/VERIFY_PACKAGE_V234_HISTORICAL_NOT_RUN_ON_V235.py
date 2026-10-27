from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
 m=json.loads((ROOT/'MANIFEST.json').read_text(encoding='utf-8'))
 assert m['schema']=='R1_15A2_V234_LIVE_API_REMEDIATION_MANIFEST_V1'
 actual={x.relative_to(ROOT).as_posix() for x in ROOT.rglob('*') if x.is_file() and '__pycache__' not in x.parts and '.pytest_cache' not in x.parts and not x.name.endswith('.pyc') and x.name not in ('MANIFEST.json','SHA256SUMS.txt')}
 assert actual==set(m['files']),(sorted(actual-set(m['files'])),sorted(set(m['files'])-actual))
 for name,value in m['files'].items():assert sha(ROOT/name)==value,name
 sums=(ROOT/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines()
 assert len(sums)==len(m['files'])
 for line in sums:
  digest,name=line.split('  ',1)
  assert name in m['files'] and sha(ROOT/name)==digest,name
 assert m['observations']=={'total':498,'calibration':462,'validation':36}
 assert m['apply_default'] is False
 assert m['population_attribute_live_blocker_resolved'] is False
 assert m['updated_code_live_tested'] is False
 cfg=json.loads((ROOT/'R1_15A2_CONFIG_V2_3_4.json').read_text(encoding='utf-8'))
 assert cfg['apply'] is False and cfg['supply']['assignment_operations']==[]
 assert cfg['supply']['gap_readback']['attribute'] is None
 assert cfg['zahr']['population_attr']=='POP_ZP_2022'
 print('V2.3.4 PACKAGE PASS files='+str(len(actual)))
if __name__=='__main__':main()
