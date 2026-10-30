"""Adversarial review of the actual consecutive-native-restore optimization."""
import pytest
import r1_15a2_td_restore_v24917 as restore
import r1_15a2_dynamic_skim_v24916p2c as dyn
from test_v24917_td_restore_perf import native


def test_audit_write_failure_cannot_publish_restore_receipt(native, monkeypatch):
    b,state,abc,expected=native
    def fail(*args,**kwargs):
        raise OSError('SIMULATED_AUDIT_WRITE_FAILURE')
    monkeypatch.setattr(restore,'audit',fail)
    with pytest.raises(OSError,match='SIMULATED_AUDIT_WRITE_FAILURE'):
        b.restore_state(abc,expected)
    assert state.native_calls==1
    assert b._td_perf_restore_receipt is None


def test_identical_dis_values_under_new_binding_require_native_recompute(native):
    b,state,abc,expected=native
    b.restore_state(abc,expected)
    rows=dyn._native_dis_rows(b.outer_adapter)
    old_no=rows['NATIVE_CW']['matrix_no_int']
    state.arrays[801]=state.arrays[old_no].copy()
    rows['NATIVE_CW']['matrix_no_int']=801
    b.restore_state(abc,expected)
    assert state.native_calls==2
    assert b._td_perf_restore_audit['verified_reuses']==0


def test_generation_cache_cannot_supply_a_fresh_restore_proof(native):
    b,state,abc,expected=native
    b.restore_state(abc,expected)
    outer=b.outer_adapter
    cached=outer._live_generation_matrices()
    outer._v24917_generation_reads={}
    outer._live_generation_matrices=lambda:{code:a.copy() for code,a in cached.items()}
    state.arrays[9300][0,1]+=10.
    b.restore_state(abc,expected)
    assert state.native_calls==2
    assert b._td_perf_restore_audit['verified_reuses']==0


def test_equal_vehicle_od_values_under_changed_dseg_binding_require_native_recompute(native):
    b,state,abc,expected=native
    b.restore_state(abc,expected)
    old=state.dseg_matrix_numbers['NATIVE_CW']
    state.arrays[9400]=state.arrays[old].copy()
    state.dseg_matrix_numbers['NATIVE_CW']=9400
    b.restore_state(abc,expected)
    assert state.native_calls==2
    assert b._td_perf_restore_audit['verified_reuses']==0


def test_renamed_protected_matrix_cannot_reuse_old_source_proof(native):
    b,state,abc,expected=native
    b.restore_state(abc,expected)
    state.matrix_codes[9697]='CHANGED_OSRM_SOURCE_IDENTITY'
    b.restore_state(abc,expected)
    assert state.native_calls==2
    assert b._td_perf_restore_audit['verified_reuses']==0


def test_other_visum_wrapper_is_not_same_restore_owner(native):
    from types import SimpleNamespace as NS
    b,state,abc,expected=native
    b.restore_state(abc,expected)
    b.outer_adapter.visum=NS(Net=b.v.Net)
    b.restore_state(abc,expected)
    assert state.native_calls==2
    assert b._td_perf_restore_audit['verified_reuses']==0


def test_live_procedure_collection_is_checked_instead_of_old_objects(native):
    from types import SimpleNamespace as NS
    b,state,abc,expected=native
    b.restore_state(abc,expected)
    changed=NS(AttValue=lambda attr:{'OPERATIONTYPE':65,'ACTIVE':1}.get(attr,''))
    b.v.Procedures.Operations.GetAll=lambda:[changed]
    with pytest.raises(restore.SupplyContractError,match='TD_OPERATION_CHANGED'):
        b.restore_state(abc,expected)
    assert state.native_calls==1
    assert b._td_perf_restore_audit['verified_reuses']==0


def test_replaced_td_parameter_root_is_read_live_not_from_cached_object(native):
    import copy
    from types import SimpleNamespace as NS
    b,state,abc,expected=native
    b.read_abc=lambda:copy.deepcopy(getattr(b.td,'values',state.coeff))
    b.restore_state(abc,expected)
    changed=copy.deepcopy(abc);changed[9101]['b']+=.1
    replacement=NS(values=changed,AttValue=lambda attr:'R1_MUTABLE')
    b.ops[0].TripDistributionParameters=replacement
    with pytest.raises(restore.SupplyContractError,match='RESTORE_PARAMETER_CHANGED'):
        b.restore_state(abc,expected)
    assert b._td_perf_restore_audit['verified_reuses']==0
