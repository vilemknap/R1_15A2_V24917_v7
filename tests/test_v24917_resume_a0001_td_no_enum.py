"""No COM regression tests for exact A0001 incomplete-TD restart."""
from __future__ import annotations
import copy
import hashlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

import r1_15a2_resume_a0001_v24917 as resume

ROOT = Path(resume.__file__).resolve().parent

@pytest.fixture
def recipe():
    return resume.authority(ROOT)


def make_artifacts(tmp_path, recipe):
    # Exact 2026-10-30 nested source layout; the new run must be a sibling.
    calib = (tmp_path / 'R1_15A2_V16_RUNS' /
             'RUN_20261030_143622_183126' / 'CALIBRATION')
    cps = calib / 'CHECKPOINTS'
    cps.mkdir(parents=True)
    checkpoint = cps / recipe['checkpoint_filename']
    checkpoint.write_bytes(b'fake-test-only-checkpoint')
    rec = copy.deepcopy(recipe)
    rec['expected_checkpoint_raw_sha256'] = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    (Path(str(checkpoint)+'.semantic.json')).write_text(json.dumps({
        'semantic_state_hash':rec['checkpoint_semantic_state_hash'],
        'semantic_hashes':rec['checkpoint_semantic_hashes']}))
    store = calib / rec['path_store_relative_to_calibration']
    store.parent.mkdir(parents=True,exist_ok=True)
    store.write_bytes(b'fake-sqlite-store')
    reference = {'schema':'R1_15A2_SHARED_OBJECTIVE_V22','cal_scale':12.0}
    ref = calib / rec['source_reference_relative_to_calibration']
    ref.write_text(json.dumps(reference))
    run = {
        'status':'FAILED_MANUAL_REOPEN_LATEST_ACCEPTED_REQUIRED',
        'accepted_count':1,
        'latest_accepted_checkpoint':{'path':str(checkpoint), 'sha256':rec['expected_checkpoint_raw_sha256']},
        'demand_cycles':[{
            'cycle':1, 'generation_completed':True, 'generation_changed':True,
            'td_completed':False,
            'state_hash_start':rec['epoch_origin_snapshot_state_hash'],
            'generation':{
                'status':'ACCEPTED', 'adopted_in_place':True,
                'search_complete':False,
                'early_stop_policy':'STEP1_FIRST_ELIGIBLE_KEPT',
                'candidate':{'scale':rec['expected_generation_record']['candidate_scale']},
                'path_epoch_transition':{'basis_hash':rec['path_epoch']['basis_hash']},
                'objective_after':{'reference_hash':rec['generation_reference_hash']},
            },
        }],
    }
    (calib / rec['source_run_status_relative_to_calibration']).write_text(json.dumps(run))
    return checkpoint,rec,run,reference


def test_source_and_partial_generation_resume(tmp_path,recipe):
    cp,auth,run,ref=make_artifacts(tmp_path,recipe)
    paths=resume.check_source(cp,auth)
    cont=resume.load_continuation(paths,auth,lambda _:auth['generation_reference_hash'])
    assert cont['resume_outer_cycle']==1 and cont['accepted_count']==1
    assert cont['resume_substep']=='TD_FINECDF_V17' and cont['resume_generation_completed']
    assert cont['resume_generation_record']['search_complete'] is False
    assert cont['generation_reference']==ref
    assert resume.validate_continuation({'runtime_demand_continuation':cont},auth)==cont


def test_missing_store_fails_without_enumeration(tmp_path,recipe):
    cp,auth,_,_=make_artifacts(tmp_path,recipe)
    (cp.parent.parent / auth['path_store_relative_to_calibration']).unlink()
    with pytest.raises(RuntimeError,match='PATH_STORE_MISSING'):
        resume.check_source(cp,auth)


def test_changed_checkpoint_or_sidecar_fails(tmp_path,recipe):
    cp,auth,_,_=make_artifacts(tmp_path,recipe)
    cp.write_bytes(b'changed')
    with pytest.raises(RuntimeError,match='CHECKPOINT_BYTES_CHANGED'):
        resume.check_source(cp,auth)
    cp.write_bytes(b'fake-test-only-checkpoint')
    s=Path(str(cp)+'.semantic.json')
    bad=json.loads(s.read_text());bad['semantic_hashes']['matrix_hash']='0'*64
    s.write_text(json.dumps(bad))
    with pytest.raises(RuntimeError,match='SIDECAR_FIELD_MISMATCH:matrix_hash'):
        resume.check_source(cp,auth)


def test_generation_reference_or_acceptance_mismatch_fatal(tmp_path,recipe):
    cp,auth,run,ref=make_artifacts(tmp_path,recipe)
    paths=resume.check_source(cp,auth)
    with pytest.raises(RuntimeError,match='REFERENCE_FIXED_OBJECTIVE_HASH_MISMATCH'):
        resume.load_continuation(paths,auth,lambda _: '0'*64)
    run['demand_cycles'][0]['generation']['adopted_in_place']=False
    paths['run_status'].write_text(json.dumps(run))
    with pytest.raises(RuntimeError,match='GENERATION_RECORD_MISMATCH:adopted_in_place'):
        resume.load_continuation(paths,auth,lambda _: auth['generation_reference_hash'])


def test_runtime_binding_requires_real_completed_assignment_source(monkeypatch,tmp_path,recipe):
    cp,auth,_,_=make_artifacts(tmp_path,recipe)
    paths=resume.check_source(cp,auth)
    cont=resume.load_continuation(paths,auth,lambda _:auth['generation_reference_hash'])
    checkpoint={'current':{'state_hash':'live',**auth['checkpoint_semantic_hashes']}}
    class Adapter:
        def __init__(self):
            self.cache=None
            self.cfg={'coupled_demand':{'max_outer_cycles':100}}
        def snapshot(self):return dict(checkpoint['current'])
        def diagnostics(self,*args,**kwargs):return {'d12':{'rows':[]}}
    adapter=Adapter()
    calls=[]
    mock_supply=types.ModuleType('r1_15a2_supply'); mock_supply.canonical_hash=lambda _:auth['generation_reference_hash']; mock_supply.SupplyContractError=RuntimeError
    monkeypatch.setitem(sys.modules,'r1_15a2_supply',mock_supply)
    mock_controller=types.ModuleType('r1_15a2_overnight_controller_coupled_v24915p2_force100')
    mock_controller._runtime_demand_continuation=lambda cfg:{'enabled':False}
    monkeypatch.setitem(sys.modules,mock_controller.__name__,mock_controller)
    def original(adapter,cfg,folder,control,root):
        calls.append(('run',cfg['runtime_demand_continuation']['resume_substep']))
        adapter.diagnostics(folder,label='BASELINE')
        return mock_controller._runtime_demand_continuation(cfg)
    original_runs_root = cp.parent.parent.parent.parent
    v16=NS(RUNS_ROOT_NAME='R1_15A2_V16_RUNS',
           _base_layout=lambda source: {
               'project_base':original_runs_root.parent,
               'detected_run_roots_nearest_first':[original_runs_root],
               'outermost_run_root':original_runs_root},
           _install_runtime=lambda *a:None,
           _run_live_preflight=lambda *a,**k:({'source_semantic_state_hash':auth['checkpoint_semantic_state_hash'],
               'source_semantic_hashes':auth['checkpoint_semantic_hashes']},{}),
           parent=NS(run_overnight_calibration_coupled=original,
                     _assert_new_run_is_not_nested=lambda *args:None))
    def fake_restore(*args):calls.append(('restore',))
    monkeypatch.setattr(resume,'restore_readonly_path_epoch',fake_restore)
    resume.install_resume(v16,cp,auth,paths,cont,print_fn=lambda *x:None)
    v16._install_runtime()
    assert v16._run_live_preflight()[0]['source_semantic_state_hash']==auth['checkpoint_semantic_state_hash']
    result=v16.parent.run_overnight_calibration_coupled(adapter,adapter.cfg,tmp_path,None,None)
    assert result['accepted_count']==1 and result['resume_generation_record']['search_complete'] is False
    assert calls==[('run','TD_FINECDF_V17'),('restore',)]
    with pytest.raises(Exception,match='A0001_RESUME_NO_PATH_ENUMERATION_ALLOWED'):
        adapter._build_cache()


def test_read_only_store_hash_and_origin_checks(monkeypatch,tmp_path,recipe):
    cp,auth,_,_=make_artifacts(tmp_path,recipe)
    paths=resume.check_source(cp,auth)
    mock_twomode=types.ModuleType('r1_15a2_two_mode_v238')
    mock_twomode.DEFAULT_SETTINGS={}
    mock_twomode.atomic_json=lambda path,value:Path(path).parent.mkdir(parents=True,exist_ok=True) or Path(path).write_text(json.dumps(value))
    class Collector:
        parent_hash=auth['epoch_origin_snapshot_state_hash']
        incidence_ready=True
        closed=False
        read_only_args=None
        @classmethod
        def open_existing(cls,*args,**kwargs):
            cls.read_only_args=(kwargs['read_only'],kwargs['require_profile_metadata'])
            return cls()
        def path_basis_hash(self):return auth['path_epoch']['basis_hash']
        def path_basis_comparison_hash(self):return auth['path_epoch']['comparison_basis_hash']
        def rebind_profiles(self,rows,**kwargs):return {'profile_count':len(rows)}
        def close(self):self.closed=True
    mock_twomode.TwoModeRouteCollector=Collector
    monkeypatch.setitem(sys.modules,mock_twomode.__name__,mock_twomode)
    monkeypatch.setattr(resume, 'verify_legacy_profile_hits', lambda collector: {'passes':True})
    adapter=NS(cache=None,path_epoch_index=0,path_epoch_accepts=0,
               path_epoch_history=[],persistent_path_cache=NS(enabled=False),
               cfg={'performance':{'path_epochs':{'enabled':True}},'two_mode':{},
                    'dseg_path_volume_relative_tolerance':.01,'supply':{},
                    'com_resilience':{}},policy=NS(),control=None,
               read_links=lambda:{(11,1,2):{'object':'COM-ignored','eligible':True}})
    snapshot={'state_hash':'live',**auth['checkpoint_semantic_hashes'],'addval1':{'11|1|2':3.0}}
    rec=resume.restore_readonly_path_epoch(adapter,{'d12':{'rows':[{'model':3.0}]}},
                                           snapshot,paths,auth,tmp_path/'out')
    assert rec['status']=='VERIFIED_ORIGINAL_PATH_EPOCH_RESTORED'
    assert adapter.cache is not None and adapter.path_epoch_index==1
    assert Collector.read_only_args==(True,False)
    assert adapter.cache_links[(11,1,2)]['addval1']==3.0
    # Any basis mismatch must close the read-only store and refuse publication.
    adapter.cache=None;adapter.path_epoch_index=0
    real_basis=auth['path_epoch']['basis_hash']
    Collector.path_basis_hash=lambda self:real_basis
    auth['path_epoch']['basis_hash']='0'*64
    with pytest.raises(RuntimeError,match='PATH_STORE_BASIS_MISMATCH'):
        resume.restore_readonly_path_epoch(adapter,{'d12':{'rows':[]}},snapshot,paths,auth,tmp_path/'out')
    assert adapter.cache is None


def test_legacy_path_store_profile_hits_exact_geometry_reconstruction(monkeypatch):
    """Prove profile-index meanings without metadata added only by publisher."""
    import sqlite3
    import struct
    from types import SimpleNamespace as NS
    # Pure mock matches the V238 little-endian stored uint32 geometry format.
    mock_twomode=types.ModuleType('r1_15a2_two_mode_v238')
    mock_twomode._unpacked=lambda b:struct.unpack('<%dI' % (len(b)//4),b)
    monkeypatch.setitem(sys.modules,mock_twomode.__name__,mock_twomode)
    mock_supply=types.ModuleType('r1_15a2_supply')
    mock_supply.SupplyContractError=RuntimeError
    monkeypatch.setitem(sys.modules,mock_supply.__name__,mock_supply)
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE geometry(gid INTEGER,edge_ids BLOB,edge_count INTEGER)')
    db.execute('CREATE TABLE profile_hits(gid INTEGER,profile_index INTEGER,multiplicity INTEGER)')
    # profile 0 observes link 11; profile 1 observes link 12 and link 11.
    db.executemany('INSERT INTO geometry VALUES(?,?,?)',[
        (1,struct.pack('<III',1,2,1),3), (2,struct.pack('<I',2),1)])
    db.executemany('INSERT INTO profile_hits VALUES(?,?,?)',[
        (1,0,2),(1,1,3),(2,1,1)])
    adapter=NS(db=db,edge_keys=(None,(11,1,2),(12,2,3)),
               profile_index_by_key={(11,1,2):[0,1],(12,2,3):[1]})
    proof=resume.verify_legacy_profile_hits(adapter)
    assert proof['passes'] and proof['routes_checked']==2 and proof['links_checked']==4
    assert proof['com_path_export_calls']==0
    db.execute('UPDATE profile_hits SET multiplicity=4 WHERE gid=1 AND profile_index=1')
    with pytest.raises(Exception, match='PROFILE_HITS_STATIC_AUTHORITY_MISMATCH'):
        resume.verify_legacy_profile_hits(adapter)
    db.close()


def test_real_run_status_latest_checkpoint_is_flat(tmp_path,recipe):
    cp,auth,run,ref=make_artifacts(tmp_path,recipe)
    paths=resume.check_source(cp,auth)
    assert resume.load_continuation(paths,auth,lambda _:auth['generation_reference_hash'])['accepted_count']==1
    run['latest_accepted_checkpoint']={'checkpoint':run['latest_accepted_checkpoint']}
    paths['run_status'].write_text(json.dumps(run))
    with pytest.raises(RuntimeError,match='RUN_LATEST_CHECKPOINT_MISMATCH'):
        resume.load_continuation(paths,auth,lambda _:auth['generation_reference_hash'])

def test_real_parent_layout_false_positive_is_fixed_for_a0001(tmp_path, recipe):
    """Test real resolver and old false-positive guard, then scoped correction."""
    import ast
    cp, _, _, _ = make_artifacts(tmp_path, recipe)
    source_run = cp.parent.parent.parent
    runs_root = source_run.parent
    source_path = ROOT / "r1_15a2_fresh0_shortroot_parent_v24916.py"
    syntax = ast.parse(source_path.read_text(encoding="utf-8"))
    names = {"_is_runs_root", "_run_tree_ancestors", "_stable_project_layout",
             "_is_relative_to", "_assert_new_run_is_not_nested"}
    nodes = [n for n in syntax.body
             if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == names
    ns = {"Path": Path}
    exec(compile(ast.Module(body=nodes, type_ignores=[]),
                 str(source_path), "exec"), ns)
    layout = ns["_stable_project_layout"](cp)
    assert layout["project_base"] == tmp_path.resolve()
    assert layout["detected_run_roots_nearest_first"] == [runs_root.resolve()]
    assert layout["outermost_run_root"] == runs_root.resolve()

    sibling = runs_root / "RUN_20261030_235959_999999"
    with pytest.raises(RuntimeError, match="V24915P2_NEW_RUN_STILL_NESTED_UNDER_PRIOR_RUN_TREE"):
        ns["_assert_new_run_is_not_nested"](
            sibling, layout["detected_run_roots_nearest_first"])
    parent = NS(_assert_new_run_is_not_nested=ns["_assert_new_run_is_not_nested"])
    v16 = NS(RUNS_ROOT_NAME="R1_15A2_V16_RUNS",
             _base_layout=ns["_stable_project_layout"], parent=parent)
    info = resume.install_sibling_run_layout_guard(
        v16, cp, print_fn=lambda *args:None)
    assert info["runs_root"] == str(runs_root.resolve())
    assert info["source_run"] == str(source_run.resolve())
    assert parent._assert_new_run_is_not_nested(
        sibling, layout["detected_run_roots_nearest_first"]) is None

    invalid = (
        cp.parent / sibling.name,  # below CHECKPOINTS
        source_run / "R1_15A2_V16_RUNS" / sibling.name,  # historical error
        source_run / sibling.name,
        tmp_path / "WRONG_RUNS" / sibling.name,
        source_run,  # cannot reuse or overwrite the old run
    )
    for candidate in invalid:
        with pytest.raises(RuntimeError, match="A0001_RESUME_NEW_RUN_"):
            parent._assert_new_run_is_not_nested(
                candidate, layout["detected_run_roots_nearest_first"])
    with pytest.raises(RuntimeError, match="A0001_RESUME_PRIOR_RUN_ROOTS_CHANGED"):
        parent._assert_new_run_is_not_nested(sibling, [])


def test_sibling_layout_guard_rejects_unexpected_project_base(tmp_path, recipe):
    cp, _, _, _ = make_artifacts(tmp_path, recipe)
    old_root = cp.parent.parent.parent.parent
    v16 = NS(
        RUNS_ROOT_NAME="R1_15A2_V16_RUNS",
        _base_layout=lambda _: {
            "project_base":cp.parent,
            "detected_run_roots_nearest_first":[old_root]},
        parent=NS(_assert_new_run_is_not_nested=lambda *a:None),
    )
    with pytest.raises(RuntimeError, match="A0001_RESUME_SOURCE_LAYOUT_PROJECT_BASE_MISMATCH"):
        resume.install_sibling_run_layout_guard(v16, cp, print_fn=lambda *args:None)
    v16._base_layout = lambda _: {
        "project_base":tmp_path,
        "detected_run_roots_nearest_first":[],
    }
    with pytest.raises(RuntimeError, match="A0001_RESUME_SOURCE_LAYOUT_RUNS_ROOT_MISMATCH"):
        resume.install_sibling_run_layout_guard(v16, cp, print_fn=lambda *args:None)

def test_a0001_silent_launcher_normalizes_source_to_project_root(tmp_path, recipe):
    import importlib.util
    launcher = ROOT / "01_SPUSTIT_V24917_RESUME_A0001_TD_NO_ENUM_SILENT.py"
    spec = importlib.util.spec_from_file_location("_a0001_silent_launch_test", launcher)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cp, _, _, _ = make_artifacts(tmp_path, recipe)
    host = NS(IO=NS(CurrentVersionFile=str(cp)))
    assert mod._source_project_base_for_silent(host) == tmp_path.resolve()
    assert not (cp.parent / "R1_15A2_SILENT_DEBUG").exists()
    other = tmp_path / "UNRELATED" / "source.ver"
    other.parent.mkdir()
    other.write_bytes(b"not-checkpoint")
    with pytest.raises(RuntimeError, match="A0001_RESUME_SILENT_SOURCE_NOT_IN_PREVIOUS_RUN_CHECKPOINTS"):
        mod._source_project_base_for_silent(NS(IO=NS(CurrentVersionFile=str(other))))
