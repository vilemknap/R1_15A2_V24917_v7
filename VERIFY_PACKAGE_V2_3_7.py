"""Independent package integrity and this candidate's immutable-authority assertions."""
from pathlib import Path
import hashlib,json
R=Path(__file__).resolve().parent
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
def verify():
    manifest=json.loads((R/'MANIFEST.json').read_text(encoding='utf-8'))
    expected=manifest['files']
    actual={p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_file()
            and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts
            and p.suffix!='.pyc' and p.name not in ('MANIFEST.json','SHA256SUMS.txt')}
    assert set(expected)==actual,(sorted(set(expected)-actual),sorted(actual-set(expected)))
    for name,digest in expected.items(): assert sha(R/name)==digest,name
    lines=(R/'SHA256SUMS.txt').read_text(encoding='ascii').splitlines()
    assert len(lines)==len(expected)
    for line in lines:
        digest,name=line.split('  ',1)
        assert expected[name]==digest==sha(R/name),name
    delta=json.loads((R/'BASELINE_DELTA_DUPQA_20261016.json').read_text())
    for rec in delta['unchanged_protected_files_from_predecessor']:
        assert sha(R/rec['path'])==rec['sha256'],rec['path']
    for rec in delta['base_sources_modified_intentionally']:
        assert sha(R/rec['path'])==rec['after_sha256']!=rec['before_sha256'],rec['path']
    cfg=json.loads((R/'R1_15A2_CONFIG_V2_3_7.json').read_text())
    assert cfg['apply'] is False and cfg['supply']['assignment_operations']==[]
    assert cfg['supply']['gap_readback']['maximum_gap']==0.005
    assert cfg['supply']['sequence']['design_only_duplicate_scope_policy']=='DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS'
    assert (cfg['expected_12d_rows'],cfg['expected_calibration_rows'],cfg['expected_validation_rows'])==(498,462,36)
    overlap=json.loads((R/'AUTHORITY_498_DUPLICATE_DIRECTED_EDGE_QA_STATIC.json').read_text())
    assert (overlap['approved_observations'],overlap['same_source_conflicting_scope_group_count'],
            overlap['shared_directed_edge_count'],overlap['shared_across_sources_count'])==(498,2,37,35)
    print('DESIGN-ONLY DUPLICATE QA / NO COM RELOAD VERIFIED:',len(expected),'files')
if __name__=='__main__':verify()
