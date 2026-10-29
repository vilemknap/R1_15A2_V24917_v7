"""Regression for 2026-10-29 live baseline failure: approved 09C partial assignments."""
from contextlib import contextmanager
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_long_post_td_mask_v24917 as maskmod
import r1_15a2_com_compat as com
import r1_15a2_acceleration_v24915p1 as accel


FINAL = (
    "EXOG_EE_CF,EXOG_EE_CL,EXOG_EE_CS,EXOG_EE_CS_noT,"
    "EXOG_EE_CW,EXOG_EE_CW_noT,LNV,NATIVE_CF,NATIVE_CL,"
    "NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT,NV"
)
PARTIAL = {
    17: "LNV,NV",
    18: "NATIVE_CF,NATIVE_CL",
    19: "NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT",
    20: FINAL,
}


class PrtOperation:
    def __init__(self, scope):
        self.PrTAssignmentParameters = NS(AttValue=lambda name: scope if name == "DSEGSET" else None)


def _adapter():
    return NS(visum=NS(), zones=[1, 2],
              cfg={"supply": {"assignment_operations": [
                  {"no": 20, "operation_type": 101,
                   "expected_dsegs": [x for x in FINAL.replace("_noT", "_NOT").split(",")]}]}})


def _rows(extra=None, omit=None, scopes=None):
    assignments = dict(PARTIAL)
    if omit:
        assignments.pop(omit)
    assignments.update(extra or {})
    scopes = scopes or {}
    rows = []
    for pos in range(1, 21):
        kind = 46 if pos == 6 else (101 if pos in assignments else (75 if pos in (2, 4, 7, 9, 13, 16) else 65))
        rows.append({"no": pos, "position": pos, "active": 1, "type": kind,
                     "object": PrtOperation(scopes.get(pos, assignments.get(pos, "")))})
    return rows


def _run(monkeypatch, tmp_path, rows):
    adapter = _adapter()
    calls = []
    changed = []
    # Other historical tests purge/reimport r1_15a2_* modules in this process.
    # Patch the module which execute_sequence imports NOW, not a stale reference
    # retained when pytest first collected this test file.
    import importlib
    live_com = importlib.import_module("r1_15a2_com_compat")
    live_accel = importlib.import_module("r1_15a2_acceleration_v24915p1")
    monkeypatch.setattr(live_com, "operation_rows", lambda _visum: rows)
    monkeypatch.setattr(maskmod, "read_current", lambda _adapter: (np.array([[0., 80.], [80., 0.]]), {"status": "PASS"}))
    monkeypatch.setattr(maskmod, "apply_group", lambda *_args, **_kwargs: calls.append(("mask", tuple(_args[2]))))
    monkeypatch.setattr(maskmod, "_verify_support", lambda *_args: calls.append(("verify", None)))

    @contextmanager
    def scoped(_visum, plan):
        before = [r["active"] for r in rows]
        selected = set(plan["selected_operation_positions"])
        for r in rows:
            r["active"] = int(r["no"] in selected)
        changed.append(sorted(selected))
        try:
            yield plan
        finally:
            for row, old in zip(rows, before):
                row["active"] = old

    monkeypatch.setattr(live_accel, "activate_operation_plan", scoped)

    def native(_visum, _folder):
        calls.append(("execute", [r["no"] for r in rows if r["active"] and r["type"] != 75]))

    maskmod.execute_sequence(adapter, tmp_path, native)
    return calls, changed, rows


def test_real_09c_assignments_17_to_20_execute_as_one_final_authority(monkeypatch, tmp_path):
    rows = _rows()
    calls, phases, rows = _run(monkeypatch, tmp_path, rows)
    executed = [x[1] for x in calls if x[0] == "execute"]
    assert executed == [[1, 3, 5, 6], [8, 10, 11, 12, 14, 15], [17, 18, 19, 20]]
    assert [x[0] for x in calls] == ["execute", "mask", "execute", "mask", "execute", "verify"]
    assert len(phases) == 3
    assert all(r["active"] == 1 for r in rows)



def test_real_09c_only_final_op20_active_promotes_partials_for_execution(monkeypatch, tmp_path):
    """Saved model has only OP20 active; execution safely runs OP17..OP20."""
    rows = _rows()
    for no in (17, 18, 19):
        rows[no - 1]["active"] = 0
    before = [row["active"] for row in rows]
    calls, phases, after = _run(monkeypatch, tmp_path, rows)
    executed = [x[1] for x in calls if x[0] == "execute"]
    assert executed == [[1, 3, 5, 6], [8, 10, 11, 12, 14, 15], [17, 18, 19, 20]]
    assert [x[0] for x in calls] == ["execute", "mask", "execute", "mask", "execute", "verify"]
    assert len(phases) == 3
    assert [row["active"] for row in after] == before
    import json
    report = json.loads((tmp_path / 'LONG_MASK_EXECUTION_PLAN.json').read_text())
    assert report['temporarily_activated_partial_assignments'] == [17, 18, 19]
    assert report['expected_final_assignment_sequence'] == [17, 18, 19, 20]
    assert report['original_active_flags_restored_after_each_phase'] is True


@pytest.mark.parametrize("scopes, error", [
    ({18: "NATIVE_CF,NATIVE_CW"}, "LONGMASK_ASSIGNMENT_DSEG_SCOPE_MISMATCH:18"),
    ({19: "NATIVE_CS,NATIVE_CS,NATIVE_CW"}, "LONGMASK_ASSIGNMENT_DSEG_SCOPE_UNREADABLE:19"),
    ({20: "LNV,NV"}, "LONGMASK_ASSIGNMENT_DSEG_SCOPE_MISMATCH:20"),
])
def test_rejects_changed_live_dseg_scope_before_any_execution(monkeypatch, tmp_path, scopes, error):
    rows = _rows(scopes=scopes)
    with pytest.raises(Exception, match=error):
        _run(monkeypatch, tmp_path, rows)
    assert all(r["active"] for r in rows)



def test_inactive_partial_scope_drift_blocks_before_any_execution(monkeypatch, tmp_path):
    rows = _rows(scopes={18: 'NATIVE_CF,NATIVE_CW'})
    for pos in (17, 18, 19): rows[pos - 1]['active'] = 0
    with pytest.raises(Exception, match='LONGMASK_ASSIGNMENT_DSEG_SCOPE_MISMATCH:18'):
        _run(monkeypatch, tmp_path, rows)
    assert [row['active'] for row in rows[16:20]] == [0, 0, 0, 1]


def test_inactive_partial_definition_missing_blocks_before_execution(monkeypatch, tmp_path):
    rows = _rows(omit=17)
    for pos in (18, 19): rows[pos - 1]['active'] = 0
    with pytest.raises(Exception, match='LONGMASK_PARTIAL_ASSIGNMENT_DEFINITION_MISMATCH:17'):
        _run(monkeypatch, tmp_path, rows)


def test_supply_only_recomputation_runs_all_four_scopes_with_restored_flags(
        monkeypatch, tmp_path):
    rows = _rows()
    for pos in (17, 18, 19): rows[pos - 1]['active'] = 0
    rows[5]['active'] = 0   # no active TD; cold re-realization path
    before = [row['active'] for row in rows]
    calls, phases, after = _run(monkeypatch, tmp_path, rows)
    executed = [x[1] for x in calls if x[0] == 'execute']
    assert executed[-1] == [17, 18, 19, 20]
    assert [row['active'] for row in after] == before


def test_rejects_missing_final_20_even_when_partial_assignments_active(monkeypatch, tmp_path):
    with pytest.raises(Exception, match="LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH"):
        _run(monkeypatch, tmp_path, _rows(omit=20))


def test_rejects_unapproved_extra_assignment(monkeypatch, tmp_path):
    rows = _rows(extra={16: "NATIVE_CL"})
    with pytest.raises(Exception, match="LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH"):
        _run(monkeypatch, tmp_path, rows)


def test_normalizes_visum_not_suffix():
    for position, scope in PARTIAL.items():
        row = {"no": position, "object": PrtOperation(scope)}
        expected = scope.replace("_noT", "_NOT").split(",")
        maskmod._verify_assignment_scope(row, expected)


def test_single_final_assignment_scope_is_verified_without_partials(monkeypatch, tmp_path):
    # Supply-only config can select only final op20. Even with no partial
    # assignments, a changed final DSEGSET is a hard error before execution.
    rows = _rows(scopes={20: "LNV,NV"})
    for position in (17, 18, 19):
        rows[position - 1]["active"] = 0
    rows[5]["active"] = 0  # supply-only: no native TD operation
    before = [row["active"] for row in rows]
    with pytest.raises(Exception, match="LONGMASK_ASSIGNMENT_DSEG_SCOPE_MISMATCH:20"):
        _run(monkeypatch, tmp_path, rows)
    assert [row["active"] for row in rows] == before


def test_duplicate_approved_final_operation_rejected(monkeypatch, tmp_path):
    original = _adapter
    def duplicate_adapter():
        adapter = original()
        adapter.cfg["supply"]["assignment_operations"].append(
            dict(adapter.cfg["supply"]["assignment_operations"][0]))
        return adapter
    # Patches a module-global lookup in the test's _run helper, not model code.
    import sys
    this_module = sys.modules[__name__]
    monkeypatch.setattr(this_module, "_adapter", duplicate_adapter)
    with pytest.raises(Exception, match="LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH"):
        _run(monkeypatch, tmp_path, _rows())


def test_wrong_final_assignment_type_in_config_rejected(monkeypatch, tmp_path):
    original = _adapter
    def wrong_adapter():
        adapter = original()
        adapter.cfg["supply"]["assignment_operations"][0]["operation_type"] = 65
        return adapter
    import sys
    monkeypatch.setattr(sys.modules[__name__], "_adapter", wrong_adapter)
    with pytest.raises(Exception, match="LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH"):
        _run(monkeypatch, tmp_path, _rows())
