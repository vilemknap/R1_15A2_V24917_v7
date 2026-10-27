from pathlib import Path
import json
import types

import r1_15a2_finecdf_bridge_v242 as bridge

ROOT = Path(__file__).resolve().parents[1]


def test_v244_config_uses_native_multi_diagnostic_only_policy():
    cfg = json.loads((ROOT / 'R1_15A2_CONFIG_V2_4_4.json').read_text(encoding='utf-8'))
    fine = cfg['coupled_demand']['finecdf_td']
    assert fine['native_multi_guard_policy'] == 'DIAGNOSTIC_ONLY_NATIVE_OUTPUT_AUTHORITY'
    assert fine['strict_fixed_marginal_reject'] is False
    assert cfg['coupled_demand']['max_outer_cycles'] == 12
    assert fine['max_iterations'] == 35
    assert fine['max_td_evaluations'] == 180


def test_native_multi_wrapper_preserves_evidence_but_suppresses_external_reject():
    def raw(reference, trial, prior, zones):
        assert prior == {}
        return (
            [{'constraint_status':'REJECT_CONSTRAINED_SIDE','hard_guard_failure':1}],
            [{'interpretation':'CHECK_FAILED','hard_guard_failure':1}],
            [(9101, 0, 4, 2.0, 8.0)],
            {9101:'NO_STABLE_MARGIN_REJECT'},
            [{'evidence':'native measurement'}],
        )
    ref = types.SimpleNamespace(audit_native_marginals=raw)
    original = bridge._install_native_multi_diagnostic_guard(ref, 'DIAGNOSTIC_ONLY_NATIVE_OUTPUT_AUTHORITY')
    assert original is raw
    rows, worst, failures, modes, mode_rows = ref.audit_native_marginals({}, {}, {9101:'whatever'}, [])
    assert failures == []
    assert modes == {}
    assert rows[0]['hard_guard_failure'] == 0
    assert rows[0]['original_hard_guard_failure'] == 1
    assert rows[0]['constraint_status'] == 'NATIVE_MULTI_DIAGNOSTIC_ONLY'
    assert worst[0]['hard_guard_failure'] == 0
    assert worst[0]['interpretation'] == 'NATIVE_MULTI_RESIDUAL_DIAGNOSTIC'
    assert mode_rows[0]['hard_reject_suppressed'] == 1


def test_reference_v17_is_still_bit_identical_authority():
    path = ROOT / 'reference_v17' / 'R1_BC_AUTO_DIST_ONLY_FINECDF_PATCHED_v1_7.py'
    assert bridge._sha(path) == bridge.REF_SHA256
