"""A0001 cold-native Generation regeneration and forced fresh COM paths.

All tests are offline mocks. True Visum 09C assignment + route export must
still be validated on the user's Windows host.
"""
from __future__ import annotations
import copy
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

import r1_15a2_rebuild_generation_a0001_v24917 as rebuild
import r1_15a2_resume_a0001_v24917 as original
from r1_15a2_supply import canonical_hash
from r1_15a2_restart_v2494 import semantic_state_hash

ROOT = Path(rebuild.__file__).resolve().parent


@pytest.fixture
def recipe():
    return original.authority(ROOT)


def artifact_source(tmp_path, recipe):
    root=tmp_path/'R1_15A2_V16_RUNS'/'RUN_OLD'/'CALIBRATION'
    cp=root/'CHECKPOINTS'/recipe['checkpoint_filename']
    cp.parent.mkdir(parents=True)
    cp.write_bytes(b'original-A0001-ver')
    updated=copy.deepcopy(recipe)
    updated['expected_checkpoint_raw_sha256']=original.sha256_file(cp)
    Path(str(cp)+'.semantic.json').write_text(json.dumps({
        'semantic_state_hash':updated['checkpoint_semantic_state_hash'],
        'semantic_hashes':updated['checkpoint_semantic_hashes']}))
    reference={'schema':'R1_15A2_SHARED_OBJECTIVE_V22','authority':'fixed'}
    rp=root/updated['source_reference_relative_to_calibration']
    rp.write_text(json.dumps(reference))
    run={
        'status':'FAILED_MANUAL_REOPEN_LATEST_ACCEPTED_REQUIRED',
        'accepted_count':1,
        'latest_accepted_checkpoint':{'path':str(cp),
            'sha256':updated['expected_checkpoint_raw_sha256']},
        'demand_cycles':[{
          'cycle':1,'state_hash_start':updated['epoch_origin_snapshot_state_hash'],
          'generation_completed':True,'generation_changed':True,'td_completed':False,
          'generation':{
              'status':'ACCEPTED','adopted_in_place':True,'search_complete':False,
              'early_stop_policy':'STEP1_FIRST_ELIGIBLE_KEPT',
              'candidate':{'scale':updated['expected_generation_record']['candidate_scale']},
              'path_epoch_transition':{'basis_hash':updated['path_epoch']['basis_hash']},
              'objective_after':{'reference_hash':updated['generation_reference_hash']},
          },
        }],
    }
    r=root/updated['source_run_status_relative_to_calibration']
    r.write_text(json.dumps(run))
    return cp,updated,reference


def snapshots(recipe):
    mats=[{'matrix_no':2000+i,'rows':681,'cols':681,
           'sha256_float64_le':('%064x' % i)} for i in range(37)]
    x=dict(recipe['checkpoint_semantic_hashes'])
    x['matrix_hash']=canonical_hash(mats)
    x.update(matrices=mats,state_hash='verified-native-epoch-state')
    return x


def plan(folder):
    path=folder/'BASELINE_FULL_RECOMPUTE'/'LONG_MASK_EXECUTION_PLAN.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({
      'td_operation_position':6,
      'original_active_flags_restored_after_each_phase':True,
      'phases':[
        ['THROUGH_TD',[1,5,6]],
        ['REALIZATION',[8,10,11,12,14,15]],
        ['ASSIGNMENT_SKIMS',[17,18,19,20,31,32,33,34,35,36]],
      ]}))
    return path


class FakeCollector:
    ready=True
    def __init__(self,path):
        self.route_db_path=path
    def path_basis_hash(self): return 'fresh-basis-001'
    def path_basis_comparison_hash(self): return 'fresh-comparison-001'


def test_source_does_not_require_legacy_sqlite(tmp_path,recipe):
    cp,auth,_=artifact_source(tmp_path,recipe)
    paths=rebuild.source_paths(cp,auth)
    assert not paths['sqlite'].exists()
    assert paths['checkpoint']==cp
    assert paths['reference'].is_file()
    assert paths['run_status'].is_file()
    cp.write_bytes(b'corrupted')
    with pytest.raises(RuntimeError,match='CHECKPOINT_BYTES_CHANGED'):
        rebuild.source_paths(cp,auth)


def test_six_immutable_fields_are_strict_but_old_matrix_is_not(recipe):
    x=snapshots(recipe)
    rebuild.six_fields_match(x,recipe,'TEST')
    assert x['matrix_hash']!=recipe['checkpoint_semantic_hashes']['matrix_hash']
    for key in rebuild.SIX_IMMUTABLE:
        damaged=dict(x)
        damaged[key]='0'*64
        with pytest.raises(RuntimeError,match='FIELD_MISMATCH:'+key):
            rebuild.six_fields_match(damaged,recipe,'TEST')


def test_new_cache_root_and_native_process_operation_contract(tmp_path,recipe):
    cp,auth,_=artifact_source(tmp_path,recipe)
    paths=rebuild.source_paths(cp,auth)
    fresh=tmp_path/'R1_15A2_NEW_PATH_CACHE'/'RUN_NEW'
    assert rebuild.validate_fresh_path_root({
        'runtime_legacy_path_cache_roots':[],
        'runtime_persistent_path_cache_root':str(fresh)
    }, paths)==fresh.resolve()
    with pytest.raises(RuntimeError,match='LEGACY_CACHE_ROOTS_NONEMPTY'):
        rebuild.validate_fresh_path_root({
          'runtime_legacy_path_cache_roots':['old-run'],
          'runtime_persistent_path_cache_root':str(fresh)},paths)
    with pytest.raises(RuntimeError,match='NEW_CACHE_ROOT_NESTED_IN_OLD_RUN'):
        rebuild.validate_fresh_path_root({
          'runtime_legacy_path_cache_roots':[],
          'runtime_persistent_path_cache_root':str(cp.parent.parent/'CACHE')},paths)
    p=plan(tmp_path/'NEW_RUN')
    assert rebuild.validate_native_execution_plan(p)['THROUGH_TD']==[1,5,6]
    item=json.loads(p.read_text())
    item['phases'][0][1]=[5,6]
    p.write_text(json.dumps(item))
    with pytest.raises(RuntimeError,match='NATIVE_OPERATION_PHASE_MISSING:THROUGH_TD'):
        rebuild.validate_native_execution_plan(p)


def test_new_matrix_authority_is_explicit_and_independent(tmp_path,recipe):
    cp,auth,_=artifact_source(tmp_path,recipe)
    paths=rebuild.source_paths(cp,auth)
    matrix=snapshots(auth)
    fresh=tmp_path/'R1_15A2_PATH_CACHE'/'RUN_NEW'
    fresh.mkdir(parents=True)
    db=fresh/'TWO_MODE_PATH_STORE.sqlite'
    db.write_bytes(b'new-test-sqlite')
    diag={'d12':{'rows':[{'id':str(i)} for i in range(248)]}}
    collector=FakeCollector(db)
    root=tmp_path/'R1_15A2_V16_RUNS'/'RUN_NEW'/'CALIBRATION'
    receipt=rebuild.write_rebuilt_authority(
        root,matrix,diag,auth,paths,fresh,collector,
        rebuild.validate_native_execution_plan(plan(root)))
    assert receipt['status']=='FRESH_NATIVE_MATRICES_AND_FRESH_PATH_EPOCH_VERIFIED'
    assert receipt['new_matrix_hash']==matrix['matrix_hash']
    assert receipt['old_matrix_hash_equal'] is False
    assert receipt['source_path_epoch_reused'] is False
    assert receipt['old_sqlite_opened'] is False
    assert receipt['fresh_route_enumeration_called'] is True
    assert receipt['native_matrix_count']==37
    assert (root/rebuild.REBUILD_NAME).exists()
    assert cp.read_bytes()==b'original-A0001-ver'
    collector.route_db_path=paths['sqlite']
    with pytest.raises(RuntimeError,match='NEW_PATH_STORE_MISSING_OR_REUSED_OLD'):
        rebuild.write_rebuilt_authority(root,matrix,diag,auth,paths,fresh,collector,{})


def install_test_environment(monkeypatch,tmp_path,recipe,*,mutate_during_export=False,
                             disable_native_operation=False):
    cp,auth,_=artifact_source(tmp_path,recipe)
    paths=rebuild.source_paths(cp,auth)
    # Original A0001 acceptance was made from true 09C generation coefficients.
    continuation={
      'enabled':True,'mode':original.MODE,'accepted_count':1,
      'next_outer_cycle':1,'resume_outer_cycle':1,
      'inherited_outer_cycles':0,'max_lineage_outer_cycle':100,
      'resume_substep':'TD_FINECDF_V17',
      'generation_reference_sha256':auth['generation_reference_hash'],
      'generation_reference':{'schema':'R1_15A2_SHARED_OBJECTIVE_V22'},
      'resume_generation_record':{'status':'ACCEPTED','search_complete':False},
      'no_path_enumeration':True,
    }
    live=snapshots(auth)
    after=dict(live)
    after['matrix_hash']='changed-by-native-execution'
    # Matrices must match native snapshot hash even when original A0001 differed.
    after['matrix_hash']=canonical_hash(after['matrices'])
    steps=[]
    run_root=cp.parent.parent.parent.parent
    fresh=tmp_path/'SOME_NEW_PERSISTENT_ROOT'/'RUN_NEW'
    class Adapter:
        def __init__(self):
            self.cache=None
            self.cfg={
              'coupled_demand':{'max_outer_cycles':100},
              'runtime_legacy_path_cache_roots':[],
              'runtime_persistent_path_cache_root':str(fresh)}
        def generation_guard_snapshot(self):
            return dict(after)
        def diagnostics(self,folder,label='CURRENT'):
            steps.append('diagnostics')
            return {'d12':{'rows':[{'id':i} for i in range(248)]}}
        def _build_cache(self,diag,folder,snapshot,**kwargs):
            steps.append('fresh_enum')
            assert kwargs.get('allow_persistent_restore') is False
            assert snapshot['generation_hash']==auth['checkpoint_semantic_hashes']['generation_hash']
            db=Path(folder)/'TWO_MODE_PATH_STORE.sqlite'
            db.parent.mkdir(parents=True,exist_ok=True)
            db.write_bytes(b'new-route-db')
            self.cache=FakeCollector(db)
            if mutate_during_export:
                after['matrix_hash']='0'*64
            return self.cache,{}, {'status':'ENUMERATED_NEW'}
    adapter=Adapter()
    module=types.ModuleType('r1_15a2_overnight_controller_coupled_v24915p2_force100')
    module._runtime_demand_continuation=lambda cfg:{'enabled':False}
    monkeypatch.setitem(sys.modules,module.__name__,module)
    def original_controller(adapter,cfg,folder,control,root):
        steps.append('native_TG_TD_assignment')
        if not disable_native_operation:
            plan(Path(folder))
        adapter.diagnostics(folder,label='BASELINE')
        steps.append('TD')
        assert adapter.cache is not None
        return module._runtime_demand_continuation(cfg)
    from r1_15a2_restart_v2494 import semantic_state_hash as semhash
    hashes=dict(auth['checkpoint_semantic_hashes'])
    hashes['matrix_hash']='22dc5ab9027dbb753b38b09f6842a3572e474b12a2e8d264415c9f2c4f63565e'
    pf={
      'passes':True,'current_version_file':str(cp),
      'source_raw_ver_sha256_provenance_only':auth['expected_checkpoint_raw_sha256'],
      'semantic_before_after':{'passes':True},
      'source_semantic_hashes':hashes,
      'source_semantic_state_hash':semhash(hashes)}
    v16=NS(
      RUNS_ROOT_NAME='R1_15A2_V16_RUNS',
      _base_layout=lambda _: {
        'project_base':run_root.parent,
        'detected_run_roots_nearest_first':[run_root],
        'outermost_run_root':run_root},
      _install_runtime=lambda *a:None,
      _run_live_preflight=lambda *a,**k:(dict(pf),{}),
      parent=NS(run_overnight_calibration_coupled=original_controller,
        _assert_new_run_is_not_nested=lambda *a:None))
    disk={'load_version_called':True,
      'source_raw_sha256':auth['expected_checkpoint_raw_sha256']}
    rebuild.install_rebuild(v16,paths,auth,continuation,disk,print_fn=lambda *x:None)
    return v16,adapter,steps,tmp_path/'R1_15A2_V16_RUNS'/'RUN_NEW'/'CALIBRATION'


def test_full_rebuilt_generation_native_then_fresh_paths_before_td(
        monkeypatch,tmp_path,recipe):
    v16,adapter,steps,folder=install_test_environment(monkeypatch,tmp_path,recipe)
    report,_=v16._run_live_preflight()
    assert report['passes']
    v16._install_runtime()
    result=v16.parent.run_overnight_calibration_coupled(
        adapter,adapter.cfg,folder,None,ROOT)
    assert result['accepted_count']==1
    assert result['resume_substep']=='TD_FINECDF_V17'
    assert result['fresh_path_enumeration_required'] is True
    assert result['old_sqlite_reuse_allowed'] is False
    assert steps==['native_TG_TD_assignment','diagnostics','fresh_enum','TD']
    saved=json.loads((folder/rebuild.REBUILD_NAME).read_text())
    assert saved['source_path_epoch_reused'] is False
    assert saved['old_matrix_hash_equal'] is False
    assert saved['fresh_path_basis_hash']=='fresh-basis-001'


@pytest.mark.parametrize('break_type', ['missing_operation','mutated_by_export'])
def test_fresh_recovery_must_fail_closed_before_td(
        monkeypatch,tmp_path,recipe,break_type):
    v16,adapter,steps,folder=install_test_environment(
        monkeypatch,tmp_path,recipe,
        disable_native_operation=(break_type=='missing_operation'),
        mutate_during_export=(break_type=='mutated_by_export'))
    v16._run_live_preflight()
    v16._install_runtime()
    with pytest.raises(RuntimeError,match=(
        'A0001_REBUILD_NATIVE' if break_type=='missing_operation'
        else 'A0001_REBUILD_NEW_PATH_ENUMERATION_MUTATED_LIVE_MODEL')):
        v16.parent.run_overnight_calibration_coupled(
            adapter,adapter.cfg,folder,None,ROOT)
    assert 'TD' not in steps


def test_new_silent_launcher_resolves_old_checkpoint_to_project_root(tmp_path):
    path=ROOT/'01_SPUSTIT_V24917_REBUILD_GENERATION_FRESH_PATHS_SILENT.py'
    spec=importlib.util.spec_from_file_location('_rebuilt_fresh_launcher_test',path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    file=tmp_path/'R1_15A2_V16_RUNS'/'RUN_OLD'/'CALIBRATION'/'CHECKPOINTS'/'ACCEPTED_A.ver'
    assert mod._source_project_base(NS(IO=NS(CurrentVersionFile=str(file))))==tmp_path.resolve()
