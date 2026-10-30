"""LONG incidence binding after CountLocation diagnostic invalidation."""
import copy
from types import SimpleNamespace as NS
import pytest
import r1_15a2_long_incidence_read_v24917 as reader
from r1_15a2_skim_v24916p2c import ordered_zone_hash
from r1_15a2_trial_adapter_v24916p2c_active import VisumAdapter as Parent
from r1_15a2_trial_adapter_v24917 import VisumAdapter

def make(monkeypatch, effect=None):
    state = {"state_hash": "parent", "generation_hash": "original"}
    epoch = NS(assignment_epoch=7, epoch_hash="skim7",
               assignment_token="assignment7",
               zone_order_sha256=ordered_zone_hash([1, 2]))
    adapter = object.__new__(VisumAdapter)
    adapter.zones = [1, 2]
    adapter.readback_manager = NS(assignment_epoch=7, mutation_epoch=5,
                                  assignment_completed=True, assignment_in_progress=False)
    adapter.v24916_dynamic_skims = NS(require_current=lambda: epoch)
    adapter.generation_guard_snapshot = lambda: copy.deepcopy(state)
    def inherited(self, folder, label="CURRENT"):
        self.readback_manager.mutation_epoch += 1
        if effect: effect(self, state, epoch)
        return {"label": label}
    monkeypatch.setattr(Parent, "diagnostics", inherited)
    reader.bind_after_assignment(adapter)
    return adapter

def test_diagnostics_keep_verified_assignment(monkeypatch, tmp_path):
    a=make(monkeypatch)
    before=reader._require_binding(a)
    assert a.diagnostics(tmp_path, "AFTER")=={"label":"AFTER"}
    after=reader._require_binding(a)
    assert after["mutation_epoch"]==before["mutation_epoch"]+1
    assert after["assignment_epoch"]==before["assignment_epoch"]
    assert after["skim_epoch_hash"]==before["skim_epoch_hash"]

@pytest.mark.parametrize("effect,error",[
    (lambda a,s,e:s.update(generation_hash="changed"), "MODEL_CHANGED"),
    (lambda a,s,e:setattr(e,"epoch_hash","wrong"), "ASSIGNMENT_CHANGED"),
    (lambda a,s,e:(setattr(a.readback_manager,"assignment_epoch",8),setattr(e,"assignment_epoch",8)), "ASSIGNMENT_CHANGED"),
    (lambda a,s,e:setattr(a.readback_manager,"mutation_epoch",20), "MUTATION_EPOCH_UNEXPECTED"),
])
def test_diagnostic_drift_is_fatal(monkeypatch,tmp_path,effect,error):
    a=make(monkeypatch,effect)
    old=a._long_incidence_assignment_binding
    with pytest.raises(RuntimeError,match="LONG_INCIDENCE_DIAGNOSTICS_"+error):
        a.diagnostics(tmp_path)
    assert a._long_incidence_assignment_binding==old
    with pytest.raises(ValueError,match="BINDING_STALE"):
        reader._require_binding(a)

def test_missing_and_stale_binding_never_rebuilt(monkeypatch,tmp_path):
    a=make(monkeypatch)
    a._long_incidence_assignment_binding=None
    a.diagnostics(tmp_path)
    with pytest.raises(ValueError,match="BINDING_STALE"):
        reader._require_binding(a)
    b=make(monkeypatch)
    b.readback_manager.mutation_epoch+=1
    b.diagnostics(tmp_path)
    with pytest.raises(ValueError,match="BINDING_STALE"):
        reader._require_binding(b)

def test_diagnostic_exception_never_rebinds(monkeypatch,tmp_path):
    def fail(a,s,e): raise RuntimeError("DIAGNOSTIC_FAILED")
    a=make(monkeypatch,fail)
    with pytest.raises(RuntimeError,match="DIAGNOSTIC_FAILED"):
        a.diagnostics(tmp_path)
    with pytest.raises(ValueError,match="BINDING_STALE"):
        reader._require_binding(a)
