# -*- coding: utf-8 -*-
"""Active self-contained verification for 15P streaming candidate (not historic V2.X)."""
from pathlib import Path
from hashlib import sha256
import json

ROOT=Path(__file__).resolve().parent
HASH=lambda p:sha256(p.read_bytes()).hexdigest()


def verify():
    manifest=json.loads((ROOT/'MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['release']=='R1_15A2_V237_DESIGN_ONLY_15P_STREAMING_OFFDIAG_CANDIDATE_20261016'
    expected=manifest['files']
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
            and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts
            and p.suffix!='.pyc' and p.name not in ('MANIFEST.json','SHA256SUMS.txt')}
    assert set(expected)==actual,(sorted(set(expected)-actual),sorted(actual-set(expected)))
    for path,digest in expected.items():
        assert HASH(ROOT/path)==digest,path
    sums=(ROOT/'SHA256SUMS.txt').read_text(encoding='ascii').splitlines()
    assert len(sums)==len(expected)
    for line in sums:
        digest,path=line.split('  ',1)
        assert digest==expected[path]==HASH(ROOT/path),path
    delta=json.loads((ROOT/'15P_SOURCE_DELTA_PROTECTED_INTEGRITY.json').read_text())
    for row in delta['preserved_protected_sha256']:
        assert HASH(ROOT/row['path'])==row['sha256'],row['path']
    for row in delta['modified_source_files']:
        assert HASH(ROOT/row['path'])==row['candidate_sha256']!=row['parent_sha256'],row['path']
    cfg=json.loads((ROOT/'R1_15A2_CONFIG_V2_3_7.json').read_text(encoding='utf-8'))
    assert cfg['apply'] is False
    assert cfg['supply']['assignment_operations']==[]
    assert cfg['supply']['gap_readback']['maximum_gap']==0.005
    assert cfg['require_verified_bounded_pathlink_com'] is True
    assert cfg['pathlink_page_size']==256 and cfg['path_export_fail_fast'] is True
    assert cfg['dseg_path_volume_parity_basis']=='OFFDIAGONAL_INTERZONAL'
    assert (cfg['expected_12d_rows'],cfg['expected_calibration_rows'],cfg['expected_validation_rows'])==(498,462,36)
    entry=(ROOT/'R1_15A2_DESIGN_ONLY_FIRST_RUN_V2_3_7.py').read_text(encoding='utf-8')
    assert 'cfg["apply"] = False' in entry
    source=(ROOT/'r1_15a2_runtime_v1.py').read_text(encoding='utf-8')
    assert 'def iter_prt_pathlink_bounded(' in source and 'def matrix_interzonal_authority(' in source
    assert 'def consume_stream(' in (ROOT/'r1_15a2_sequence_v23.py').read_text(encoding='utf-8')
    assert manifest['apply_permitted'] is False and manifest['live_visum_tested'] is False
    print('15P BOUNDED OFFDIAGONAL CANDIDATE VERIFIED:',len(expected),'files',len(delta['preserved_protected_sha256']),'unchanged protected')

if __name__=='__main__':verify()
