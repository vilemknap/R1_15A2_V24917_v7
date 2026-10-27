from __future__ import annotations

import copy
from pathlib import Path

import pytest

from conftest import FakeAttr, FakeCollection, FakeOperation, FakeVisum
import r1_15a2_acceleration_v24915p1 as perf1
import r1_15a2_inplace_transaction_v24915p1 as tx
from r1_15a2_supply import canonical_hash


def _cfg(expected_profiles=2):
    return {
        "expected_12d_rows": expected_profiles,
        "supply": {
            "passenger_dsegs": ["NATIVE_CW", "NATIVE_CS"],
            "freight_dsegs": [],
            "assignment_operations": [
                {"no": 4, "operation_type": 101, "dseg_object_path": [],
                 "dseg_attribute": "DSEGSET"}
            ],
        },
        "performance": {
            "v24915_perf1": {
                "phase_specific_procseq": {
                    "enabled": True,
                    "fallback_to_full": True,
                    "preserve_active_groups": True,
                    "safe_pre_td_skip_operation_types": [45, 75],
                    "safe_post_assignment_skip_positions": [5],
                },
                "rollback_diagnostic_reuse": {
                    "enabled": True,
                    "expected_profiles": expected_profiles,
                    "absolute_tolerance": 1e-9,
                    "relative_tolerance": 1e-12,
                    "max_reported_mismatches": 10,
                },
            }
        },
        "com_resilience": {},
    }


def _proc_visum(extra_pre=None):
    ops = [
        FakeOperation(OPERATIONTYPE=75, ACTIVE=1, NAME="DEMAND GROUP"),
        FakeOperation(OPERATIONTYPE=45, ACTIVE=1, NAME="TRIP GENERATION"),
        FakeOperation(OPERATIONTYPE=46, ACTIVE=1, NAME="TRIP DISTRIBUTION"),
        FakeOperation(OPERATIONTYPE=101, ACTIVE=1, NAME="PRT", DSEGSET="NATIVE_CW,NATIVE_CS"),
        FakeOperation(OPERATIONTYPE=65, ACTIVE=1, NAME="DISPLAY ONLY"),
    ]
    if extra_pre is not None:
        ops.insert(2, extra_pre)
        # Assignment moves from 4 to 5 and display from 5 to 6.
    return FakeVisum(operations=ops)


def test_phase_plans_are_minimal_and_restore_only_changed_flags():
    visum = _proc_visum()
    cfg = _cfg()

    generation = perf1.phase_recompute_plan(visum, cfg, "GENERATION")
    assert generation["optimized"] is True
    assert generation["selected_operation_positions"] == [1, 2, 3, 4]
    assert generation["skipped_originally_active_positions"] == [5]

    td = perf1.phase_recompute_plan(visum, cfg, "TD_FINECDF")
    assert td["optimized"] is True
    # Structural group is preserved; TG and display-only operation are skipped.
    assert td["selected_operation_positions"] == [1, 3, 4]
    assert td["skipped_originally_active_positions"] == [2, 5]

    supply = perf1.phase_recompute_plan(visum, cfg, "SUPPLY_ADDVAL1")
    assert supply["selected_operation_positions"] == [1, 4]

    original = [op.AttValue("ACTIVE") for op in visum.Procedures.Operations.items]
    with perf1.activate_operation_plan(visum, td) as active:
        assert [op.AttValue("ACTIVE") for op in visum.Procedures.Operations.items] == [1, 0, 1, 1, 0]
        assert active["actual_changed_operation_positions"] == [2, 5]
    assert [op.AttValue("ACTIVE") for op in visum.Procedures.Operations.items] == original




def test_missing_reviewed_safe_post_operation_falls_back_to_full_sequence():
    visum = _proc_visum()
    cfg = _cfg()
    phase = cfg["performance"]["v24915_perf1"]["phase_specific_procseq"]
    phase["safe_post_assignment_skip_positions"] = []
    phase["safe_post_assignment_operations"] = [
        {
            "position": 21,
            "operation_type": 65,
            "text_contains_any": ["12C", "COUNTLOCATION", "GEH", "COLOR"],
        }
    ]
    plan = perf1.phase_recompute_plan(visum, cfg, "TD_FINECDF")
    assert plan["optimized"] is False
    assert plan["mode"] == "FULL_SEQUENCE_FALLBACK"
    assert "SAFE_POST_OPERATION_MISSING:21" in plan["fallback_reason"]
    assert plan["selected_operation_positions"] == [1, 2, 3, 4, 5]

def test_unknown_pre_td_operation_falls_back_to_full_sequence():
    visum = _proc_visum(extra_pre=FakeOperation(OPERATIONTYPE=999, ACTIVE=1, NAME="UNKNOWN"))
    cfg = _cfg()
    cfg["supply"]["assignment_operations"][0]["no"] = 5
    cfg["performance"]["v24915_perf1"]["phase_specific_procseq"][
        "safe_post_assignment_skip_positions"] = [6]
    plan = perf1.phase_recompute_plan(visum, cfg, "TD_FINECDF")
    assert plan["optimized"] is False
    assert plan["mode"] == "FULL_SEQUENCE_FALLBACK"
    assert "UNAPPROVED_PRE_TD_OPERATION" in plan["fallback_reason"]
    assert plan["selected_operation_positions"] == [1, 2, 3, 4, 5, 6]




class FirstActiveReadbackMismatch(FakeOperation):
    def __init__(self, **attrs):
        super().__init__(**attrs)
        self._active_sets = 0
        self._lie_once = False

    def SetAttValue(self, name, value):
        super().SetAttValue(name, value)
        if str(name).upper() == "ACTIVE":
            self._active_sets += 1
            self._lie_once = self._active_sets == 1

    def AttValue(self, name):
        value = super().AttValue(name)
        if str(name).upper() == "ACTIVE" and self._lie_once:
            self._lie_once = False
            return 1 - int(bool(value))
        return value


def test_operation_flag_is_restored_even_when_first_write_readback_fails():
    ops = [
        FakeOperation(OPERATIONTYPE=75, ACTIVE=1, NAME="GROUP"),
        FirstActiveReadbackMismatch(OPERATIONTYPE=45, ACTIVE=1, NAME="TG"),
        FakeOperation(OPERATIONTYPE=46, ACTIVE=1, NAME="TD"),
        FakeOperation(OPERATIONTYPE=101, ACTIVE=1, NAME="PRT"),
        FakeOperation(OPERATIONTYPE=65, ACTIVE=1, NAME="DISPLAY"),
    ]
    visum = FakeVisum(operations=ops)
    plan = perf1.phase_recompute_plan(visum, _cfg(), "TD_FINECDF")
    with pytest.raises(Exception, match="OPERATION_FLAG_WRITE_MISMATCH"):
        with perf1.activate_operation_plan(visum, plan):
            pass
    assert [op.AttValue("ACTIVE") for op in ops] == [1, 1, 1, 1, 1]


class BulkLinks:
    def __init__(self, rows):
        self.rows = list(rows)

    def GetMultiAttValues(self, attr, *args):
        return [(i + 1, row[attr]) for i, row in enumerate(self.rows)]


class BulkVisum:
    def __init__(self, rows):
        self.Net = FakeAttr(Links=BulkLinks(rows))


def _volume_fixture():
    dsegs = ("NATIVE_CW", "NATIVE_CS")
    def row(no, fr, to, cw, cs):
        return {
            "NO": no, "FROMNODENO": fr, "TONODENO": to,
            "VOLVEH_DSEG(NATIVE_CW,AP)": cw,
            "VOLVEH_DSEG(NATIVE_CS,AP)": cs,
        }
    links = [
        row(7, 1, 2, 10.0, 2.0),
        row(7, 2, 1, 30.0, 3.0),
        row(8, 2, 3, 5.0, 7.0),
    ]
    baseline = [
        {
            "profile_id": "BOTH7", "link_no": 7, "from_node_no": 1, "to_node_no": 2,
            "observation_direction": "BOTH", "reverse_link_no": 7,
            "reverse_from_node_no": 2, "reverse_to_node_no": 1,
            "model_NATIVE_CW": 40.0, "model_NATIVE_CS": 5.0, "model": 45.0,
        },
        {
            "profile_id": "DIR8", "link_no": 8, "from_node_no": 2, "to_node_no": 3,
            "observation_direction": "DIRECTED",
            "model_NATIVE_CW": 5.0, "model_NATIVE_CS": 7.0, "model": 12.0,
        },
    ]
    return dsegs, links, baseline


def test_498_style_profile_signature_handles_directed_and_both():
    _dsegs, links, baseline = _volume_fixture()
    result = perf1.count_profile_signature(BulkVisum(links), _cfg(2), baseline)
    assert result["passes"] is True
    assert result["profiles"] == 2
    assert result["directed_links_read"] == 3
    assert len(result["signature_hash"]) == 64

    changed = copy.deepcopy(baseline)
    changed[0]["model_NATIVE_CW"] += 0.01
    bad = perf1.count_profile_signature(BulkVisum(links), _cfg(2), changed)
    assert bad["passes"] is False
    assert bad["mismatches"][0]["field"] == "model_NATIVE_CW"




def test_profile_signature_stays_fail_closed_when_mismatch_report_cap_is_zero():
    _dsegs, links, baseline = _volume_fixture()
    changed = copy.deepcopy(baseline)
    changed[0]["model_NATIVE_CW"] += 1.0
    cfg = _cfg(2)
    cfg["performance"]["v24915_perf1"]["rollback_diagnostic_reuse"][
        "max_reported_mismatches"] = 0
    result = perf1.count_profile_signature(BulkVisum(links), cfg, changed)
    assert result["passes"] is False
    assert result["mismatch_count_total"] >= 1
    assert result["mismatch_count_reported"] == 0
    assert result["mismatches"] == []


def test_rollback_reuses_baseline_diagnostics_only_after_exact_proof(tmp_path, monkeypatch):
    before = {"state_hash": "PARENT"}
    baseline_diag = {"d12": {"rows": []}, "d11": {"summary": {}}, "signals": {}}
    baseline_hash = canonical_hash(baseline_diag)

    class Adapter:
        def __init__(self, proof):
            self.proof = proof
            self.diagnostic_calls = 0

        def snapshot(self):
            return copy.deepcopy(before)

        def rollback_diagnostic_equivalence(self, diag, snapshot, folder):
            assert diag is baseline_diag and snapshot == before
            return {"passes": self.proof}

        def diagnostics(self, folder, label):
            self.diagnostic_calls += 1
            return copy.deepcopy(baseline_diag)

    monkeypatch.setattr(tx, "restore_parameters", lambda *a, **k: [])
    monkeypatch.setattr(tx, "recompute_after_restore", lambda *a, **k: 0.001)

    fast = Adapter(True)
    result, diag = tx.rollback_and_verify(
        fast, "GENERATION", before, baseline_hash, canonical_hash,
        tmp_path / "fast", baseline_diag=baseline_diag)
    assert result["passes"] is True
    assert result["diagnostic_verification_mode"].startswith("REUSED_BASELINE")
    assert fast.diagnostic_calls == 0
    assert diag is baseline_diag

    fallback = Adapter(False)
    result2, _ = tx.rollback_and_verify(
        fallback, "GENERATION", before, baseline_hash, canonical_hash,
        tmp_path / "fallback", baseline_diag=baseline_diag)
    assert result2["passes"] is True
    assert result2["diagnostic_verification_mode"] == "FULL_12D_11D_FALLBACK"
    assert fallback.diagnostic_calls == 1
