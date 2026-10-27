"""Replay reference acceptance rules with diagnostic values near hard thresholds."""
import importlib.util
from pathlib import Path
import math
import pytest
import r1_15a2_diagfast_v1 as df
import r1_15a2_core as core
from fakes import make12
from test_reads import compute12

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('_reference_gate_fixtures',ROOT/'tests'/'test_v2496_early_exploration_pareto_acceptance.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)

@pytest.mark.parametrize('threshold',[5,10,20,30,35,40])
def test_generation_gate_at_threshold_exact_legacy_fast(tmp_path,threshold):
    v,e,manifest,_=make12(tmp_path,extra=3)
    r=next(x for x in manifest.values() if x['observation_direction']=='DIRECTED')
    key=tuple(int(r[k]) for k in ('current_link_no','current_from_node_no','current_to_node_no'))
    link=next(x for x in v.Net.Links.items if tuple(x.a[k] for k in ('NO','FROMNODENO','TONODENO'))==key)
    pairs=[]
    for geh_target in (threshold-1e-8,threshold+1e-8):
        total=fixtures._model_for_geh(float(r['observed_passenger_cars_O']),geh_target)
        for i,ds in enumerate(e['PASSENGER_DSEGS']):link.a['VOLVEH_DSEG(%s,AP)'%ds]=total if i==0 else 0.0
        rows=[]
        for backend in ('LEGACY','FAST_EXACT'):
            env=df.reference_namespace('12D',tmp_path)
            df.configure_namespace(env,'12D',backend,df.Profile('12D',backend))
            rows.append(compute12(env,v)[0])
        assert rows[0]==rows[1]
        pairs.append(rows)
    cfg=fixtures._base_cfg(3,'GENERATION')
    left=core.acceptance_decision(pairs[0][0],pairs[1][0],{},{},cfg,'GENERATION')
    right=core.acceptance_decision(pairs[0][1],pairs[1][1],{},{},cfg,'GENERATION')
    assert left==right

@pytest.mark.parametrize('relative_improvement',[.0005-1e-10,.0005,.0005+1e-10])
def test_td_gate_materiality_exact_legacy_fast(tmp_path,relative_improvement):
    # Identical scalar accumulation through both 11D readers feeds the real gate.
    from fakes import Matrix
    before=[];after=[]
    for backend in ('LEGACY','FAST_EXACT'):
        env=df.reference_namespace('11D',tmp_path)
        df.configure_namespace(env,'11D',backend,df.Profile('11D',backend))
        before.append(env['matrix_total'](Matrix(9101,[[.1,.1]]))[0])
        after.append(env['matrix_total'](Matrix(9102,[[.1*(1-relative_improvement),.1*(1-relative_improvement)]]))[0])
    cfg=fixtures._base_cfg(3,'TD')
    cfg['early_exploration_acceptance']['td']['min_selected_relative_improvement']=.0005
    rows=[fixtures._row('ONE',10)]
    decisions=[fixtures.master.td_acceptance_decision(rows,rows,fixtures._summary(b),fixtures._summary(a),fixtures._signal(b),fixtures._signal(a),['WORK_E_C'],cfg) for b,a in zip(before,after)]
    assert decisions[0]==decisions[1]
    if relative_improvement<.0005:
        assert 'SELECTED_TD_OBJECTIVE_NOT_IMPROVED' in decisions[0]['reasons']
    elif relative_improvement>.0005:
        assert 'SELECTED_TD_OBJECTIVE_NOT_IMPROVED' not in decisions[0]['reasons']
