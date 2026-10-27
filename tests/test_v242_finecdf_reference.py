from pathlib import Path

import r1_15a2_finecdf_bridge_v242 as bridge

ROOT = Path(__file__).resolve().parents[1]


def test_user_v17_reference_hash_and_authority_load():
    ref, path, sha = bridge.load_reference(ROOT)
    assert sha == bridge.REF_SHA256
    assert path.name == 'R1_BC_AUTO_DIST_ONLY_FINECDF_PATCHED_v1_7.py'
    assert len(ref.MUTABLE_NOS) == 16
    assert 9116 not in ref.MUTABLE_NOS
    assert set(ref.FINE_AUTHORITY['targets']) == set(ref.TARGETS)
    for target in ref.FINE_AUTHORITY['targets'].values():
        grid = ref.FINE_AUTHORITY['common_grid_%s_km' % target['grid']]
        assert len(grid) == 512
        assert len(target['cdf']) == 512


def test_bridge_contains_no_direct_matrix_setvalues():
    text = (ROOT / 'r1_15a2_finecdf_bridge_v242.py').read_text(encoding='utf-8')
    assert '.SetValues(' not in text
    assert 'write_matrix(' not in text


def test_v242_config_points_to_exact_user_reference():
    import json
    cfg = json.loads((ROOT / 'R1_15A2_CONFIG_V2_4_2.json').read_text(encoding='utf-8'))
    fine = cfg['coupled_demand']['finecdf_td']
    assert fine['reference_sha256'] == bridge.REF_SHA256
    assert fine['direct_od_matrix_writes'] is False
    assert fine['foreign_fixed'] is True
    assert fine['generation_frozen'] is True
    assert fine['addval1_frozen'] is True
