from pathlib import Path
import json,hashlib,csv
ROOT=Path(__file__).resolve().parent

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    m=json.loads((ROOT/'MANIFEST.json').read_text(encoding='utf-8'))
    assert m['schema']=='R1_15A2_V235_POP_ZP_FORMULA_EVIDENCE_MANIFEST_V1'
    paths={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts and p.suffix!='.pyc' and p.name not in ('MANIFEST.json','SHA256SUMS.txt')}
    assert paths==set(m['files']),(sorted(paths-set(m['files'])),sorted(set(m['files'])-paths))
    for name,digest in m['files'].items():
        assert sha(ROOT/name)==digest,name
    sums=(ROOT/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines()
    assert len(sums)==len(m['files'])
    for line in sums:
        digest,name=line.split('  ',1)
        assert m['files'][name]==digest==sha(ROOT/name),name
    cfg=json.loads((ROOT/'R1_15A2_CONFIG_V2_3_5.json').read_text(encoding='utf-8'))
    contract=json.loads((ROOT/cfg['tg_dependency_contract_file']).read_text(encoding='utf-8'))
    assert cfg['apply'] is False and cfg['zahr']['population_attr']=='POP_ZP'
    assert cfg['supply']['assignment_operations']==[]
    assert cfg['supply']['gap_readback']['attribute'] is None
    assert cfg['expected_12d_rows']==498 and cfg['expected_calibration_rows']==462 and cfg['expected_validation_rows']==36
    assert 'POP_ZP' in contract['required_zone_attributes'] and 'POP_ZP_2022' not in contract['required_zone_attributes']
    assert len(contract['dstrata'])==10
    prior=json.loads((ROOT/'V235_PROTECTED_FILE_HASHES.json').read_text(encoding='utf-8'))
    for name,digest in prior['protected_sha256'].items(): assert sha(ROOT/name)==digest,name
    live=json.loads((ROOT/'authorities/R1_TG_NESTED_FORMULA_POP_ZP_LIVE_EVIDENCE_20261015.json').read_text(encoding='utf-8'))
    assert live['population_attr']=='POP_ZP' and live['neighbour_positive_population_zones']==6
    assert m['original_live_forensic_sha256']==live['source_sha256']
    counts=[]
    for name in ('authorities/R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv','authorities/R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_90.csv'):
        with (ROOT/name).open(encoding='utf-8-sig',newline='') as f: counts+=list(csv.DictReader(f))
    assert len(counts)==498
    assert sum(r['role']=='CALIBRATION' for r in counts)==462
    assert sum(r['role']=='VALIDATION' for r in counts)==36
    print('V2.3.5 PACKAGE PASS files='+str(len(paths)))
if __name__=='__main__': main()
