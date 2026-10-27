from pathlib import Path
import json,hashlib,csv
ROOT=Path(__file__).resolve().parent
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
 m=json.loads((ROOT/'MANIFEST.json').read_text(encoding='utf-8'))
 assert m['schema']=='R1_15A2_V236_EXACT_TG09F4_MANIFEST_V1'
 paths={x.relative_to(ROOT).as_posix() for x in ROOT.rglob('*') if x.is_file() and '__pycache__' not in x.parts and '.pytest_cache' not in x.parts and x.suffix!='.pyc' and x.name not in ('MANIFEST.json','SHA256SUMS.txt')}
 assert paths==set(m['files']),(sorted(paths-set(m['files'])),sorted(set(m['files'])-paths))
 for name,digest in m['files'].items():assert sha(ROOT/name)==digest,name
 sums=(ROOT/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines()
 assert len(sums)==len(m['files'])
 for line in sums:
  digest,name=line.split('  ',1)
  assert m['files'][name]==digest==sha(ROOT/name),name
 cfg=json.loads((ROOT/'R1_15A2_CONFIG_V2_3_6.json').read_text(encoding='utf-8'))
 auth=json.loads((ROOT/cfg['tg_dependency_contract_file']).read_text(encoding='utf-8'))
 ev=json.loads((ROOT/auth['live_tg_evidence_file']).read_text(encoding='utf-8'))
 assert cfg['apply'] is False and cfg['supply']['assignment_operations']==[]
 assert cfg['supply']['gap_readback']['attribute'] is None
 assert cfg['zahr']['population_attr']=='POP_ZP'
 assert [cfg[k] for k in ('expected_12d_rows','expected_calibration_rows','expected_validation_rows')]==[498,462,36]
 assert len(auth['dstrata'])==10 and len(auth['expected_zone_attribute_types'])==21
 assert len(ev['dstrata_formula_readback'])==10 and len(ev['real_pre_input_schema'])==20
 for item in ev['dstrata_formula_readback']:
  spec=auth['dstrata'][item['dstrat_code']]
  for side in ('production','attraction'):
   expected='['+spec[side+'_outer_attribute']+']+['+spec[side+'_additive_attribute']+']'
   assert ''.join(item[side].upper().split())==expected.upper()
 prior=json.loads((ROOT/'V235_PROTECTED_FILE_HASHES.json').read_text(encoding='utf-8'))
 for name,digest in prior['protected_sha256'].items():assert sha(ROOT/name)==digest,name
 rows=[]
 for name in ('authorities/R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv','authorities/R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_90.csv'):
  with (ROOT/name).open(encoding='utf-8-sig',newline='') as f:rows.extend(csv.DictReader(f))
 assert len(rows)==498 and sum(r['role']=='CALIBRATION' for r in rows)==462
 assert sum(r['role']=='VALIDATION' for r in rows)==36
 print('V2.3.6 PACKAGE VERIFIED:',len(paths),'files; 10 TG formula pairs; 20 09F4 REAL prefeed UDAs')
if __name__=='__main__':main()
