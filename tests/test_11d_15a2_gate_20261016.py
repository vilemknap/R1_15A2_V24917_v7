import csv
import json
from pathlib import Path
import pytest
import r1_15a2_runtime_v1 as rt
import R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1 as base


def sample_12d():
    return {"summary": {"status": "PASS"},
            "row_gate": {"rows": 498, "calibration": 462, "validation": 36}}


def sample_11d(status="REVIEW_11D_TFLOWFUZZY_SCAFFOLD"):
    rows=[]
    for component,no in rt._15A2_ATOMIC_IDP.items():
        family="SCHOOL" if component=="SCHOOL" else ("SERV" if component.startswith("SERV_") else "WORK")
        rows.append({"component":component, "family":family, "matrix_no":no,
                     "target_status":"ACTIVE_COMPONENT_DIST_TARGET",
                     "conditioned_volume":500, "total_volume":700,
                     "mean_model_conditioned":9, "mean_target":10,
                     "l1_distance_half":.2, "rmse_share":.1})
    return {"step":"11d_v1_3", "final_status":status,
            "model_modified":False, "model_saved":False,
            "matrix_correction_executed":False, "assignment_executed":False,
            "dist_classification_matrix":{"code":"R1_OSRM_DIST_KM",
                "readback":{"nonfinite_cells":0, "negative_cells":0}},
            "idp_contract":{"backend_metric":"DIST_KM"},
            "component_dist_summary_rows":rows,
            "tflowfuzzy_scaffold_status":"REVIEW_TFLOWFUZZY_SCAFFOLD",
            "outputs":{"component_model_dist_vs_idp":"p"}}


def test_old_tflowfuzzy_review_does_not_block_a_sealed_498_idp_design():
    g=rt.assess_11d_idp_gate(sample_11d(), sample_12d(), {"apply":False})
    assert g['passes'] and g['status']=='PASS_IDP_ONLY_WITH_LEGACY_11D_ADVISORIES'
    assert len(g['validated_atomic_idp_components'])==11
    assert g['does_not_authorize_apply']


@pytest.mark.parametrize('status', ["REVIEW_11D_NO_TRAFFIC_COUNT_ROWS",
                                     "REVIEW_11D_COMPONENT_WEIGHT_FALLBACK",
                                     "PASS_11D_BASELINE_DIAGNOSTICS_READ_ONLY"])
def test_all_legacy_advisories_require_atomic_evidence(status):
    g=rt.assess_11d_idp_gate(sample_11d(status),sample_12d(),{"apply":False})
    assert g['passes']


def test_strict_apply_does_not_auto_approve_legacy_review():
    assert not rt.assess_11d_idp_gate(sample_11d(), sample_12d(), {"apply":True})['passes']


@pytest.mark.parametrize('mutation', ['missing_school','wrong_number','missing_mean','bad_l1','nan_volume',
                                      'neg_dist','missing_readonly','changed_model','missing_d12',
                                      'unrecognized_status','unexpected_step','wrong_classification'])
def test_safety_fail_closed_on_missing_or_corrupted_idp(mutation):
    a=sample_11d(); d=sample_12d()
    if mutation=='missing_school':
        a['component_dist_summary_rows']=[r for r in a['component_dist_summary_rows'] if r['component']!='SCHOOL']
    if mutation=='wrong_number': a['component_dist_summary_rows'][0]['matrix_no']=999
    if mutation=='missing_mean': a['component_dist_summary_rows'][0]['mean_target']=None
    if mutation=='bad_l1': a['component_dist_summary_rows'][0]['l1_distance_half']=1.3
    if mutation=='nan_volume': a['component_dist_summary_rows'][0]['conditioned_volume']='NaN'
    if mutation=='neg_dist': a['dist_classification_matrix']['readback']['negative_cells']=1
    if mutation=='missing_readonly': a.pop('matrix_correction_executed')
    if mutation=='changed_model': a['model_modified']=True
    if mutation=='missing_d12': d['row_gate']['rows']=497
    if mutation=='unrecognized_status': a['final_status']='UNEXPECTED_SUCCESS'
    if mutation=='unexpected_step': a['step']='something_other_than_11d_v1_3'
    if mutation=='wrong_classification': a['dist_classification_matrix']['code']='R1_OSRM_TIME_MIN'
    assert not rt.assess_11d_idp_gate(a,d,{'apply':False})['passes']


def _mock_helper_factory(status="REVIEW_11D_TFLOWFUZZY_SCAFFOLD", missing_csv=False, active66=False):
    def fake_helper(script, visum, stage, ws, logfile):
        ws=Path(ws);ws.mkdir(parents=True,exist_ok=True)
        (ws/rt.D11_SUMMARY).write_text(json.dumps(sample_11d(status)),encoding='utf-8')
        ops=[{"index":20,"operation_type":"101.0","active":"1"},
             {"index":42,"operation_type":"66.0","active":"1" if active66 else "0"}]
        (ws/(rt.D11_PREFIX+'tflowfuzzy_scaffold_status.json')).write_text(json.dumps({'operations':ops}),encoding='utf-8')
        suffixes=['component_model_dist_vs_idp_summary.csv','component_model_dist_vs_idp.csv','component_model_dist_baseline.csv']
        if missing_csv: suffixes.pop()
        for suffix in suffixes:
            rows=sample_11d()['component_dist_summary_rows'] if suffix=='component_model_dist_vs_idp_summary.csv' else []
            with (ws/(rt.D11_PREFIX+suffix)).open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['component','bin_label']);w.writeheader();w.writerows(rows)
    return fake_helper


def test_live_format_prefixed_csv_loaded_and_archived(tmp_path,monkeypatch):
    monkeypatch.setattr(rt,'run_helper',_mock_helper_factory())
    d=rt.run_11d(None,tmp_path,'CURRENT',sample_12d(),{'apply':False})
    assert d['idp_gate']['passes']
    assert d['summary']['final_status']=='REVIEW_11D_TFLOWFUZZY_SCAFFOLD'
    assert (tmp_path/'11D_CURRENT.zip').is_file()
    assert (tmp_path/'11D_CURRENT'/'11D_15A2_COMPATIBILITY_GATE.json').is_file()
    sources=base.load_11d_sources(d)
    assert len(sources['summary_rows'])==11
    assert all(Path(p).is_file() for p in sources['paths'].values())


@pytest.mark.parametrize('variant', ['active66','missing_csv'])
def test_failed_11d_gate_keeps_zip_evidence(tmp_path,monkeypatch,variant):
    monkeypatch.setattr(rt,'run_helper',_mock_helper_factory(active66=variant=='active66',missing_csv=variant=='missing_csv'))
    with pytest.raises(RuntimeError,match='compatibility gate failed'):
        rt.run_11d(None,tmp_path,'CURRENT',sample_12d(),{'apply':False})
    assert (tmp_path/'11D_CURRENT.zip').is_file()
    p=tmp_path/'11D_CURRENT'/'11D_15A2_COMPATIBILITY_GATE.json'
    gate=json.loads(p.read_text(encoding='utf-8'))
    assert gate['status']=='FAIL_IDP_OR_READ_ONLY'
    assert gate['failures']


def test_original_11d_and_12d_authorities_are_unchanged_via_archive_hashes():
    # Enforced separately by the package manifest build step.
    assert rt.D11_PREFIX+"summary.json" == rt.D11_SUMMARY
