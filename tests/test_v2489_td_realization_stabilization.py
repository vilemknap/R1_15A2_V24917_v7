import copy
import json
import math
from pathlib import Path

import pytest

import r1_15a2_overnight_controller_v242 as ctl
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError, canonical_hash


class Control:
    def checkpoint(self, *args, **kwargs):
        pass


class TDAdapter:
    def __init__(self, fail_above=None, hard_error=False):
        self.b = 0.0
        self.c = -0.1
        self.fail_above = fail_above
        self.hard_error = hard_error
        self.assign_calls = []
        self.apply_calls = []
        self.persistence_calls = []

    def snapshot(self):
        td = [{"component": "WORK_E_C", "current_b": self.b,
               "current_c": self.c, "status": "OK"}]
        matrices = [{"matrix_no": 9101, "rows": 2, "cols": 2,
                     "sha256_float64_le": canonical_hash([self.b, self.c])}]
        out = {
            "fixed_link_hash": "F", "dseg_hash": "D", "operations_hash": "O",
            "addval_hash": "A", "generation_hash": "G",
            "td_values": td, "td_hash": canonical_hash(td),
            "matrices": matrices, "dseg_map": {"NATIVE_CW": 9101},
            "addval1": {},
        }
        out["state_hash"] = canonical_hash(out)
        return out

    def apply_td(self, rows):
        self.apply_calls.append(copy.deepcopy(rows))
        if rows:
            self.b = float(rows[0]["candidate_b"])
            self.c = float(rows[0]["candidate_c"])

    def assign(self, folder, *, supply_only):
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.assign_calls.append((self.b, self.c))
        if self.hard_error:
            raise RuntimeError("UNRELATED_ASSIGNMENT_FAILURE")
        if self.fail_above is not None and self.b > self.fail_above:
            raise RuntimeError(
                "20B SILENT failed: IPF did not converge for Matrix(9189): "
                "max_rel_err=3.495787955651562e-06")
        return 0.003

    def parameter_persistence(self, block, rows):
        self.persistence_calls.append((block, copy.deepcopy(rows)))

    def diagnostics(self, folder, label):
        Path(folder).mkdir(parents=True, exist_ok=True)
        return {"label": label, "constant": 1}


def _parent(adapter):
    adapter.b = 0.0
    adapter.c = -0.1
    return adapter.snapshot()


def _restore(adapter, before, rows, folder=None):
    old = before["td_values"][0]
    adapter.b = float(old["current_b"])
    adapter.c = float(old["current_c"])
    return [{"status": "OK"}]


def test_default_realization_scales_are_strict_and_start_at_one():
    assert ctl._td_realization_scales({}) == [1.0, 0.5, 0.25, 0.125, 0.0625]


def test_invalid_realization_scales_fail_closed():
    cfg = {"coupled_demand": {"finecdf_td": {
        "realization_backtracking_scales": [1.0, 0.5, 0.5]}}}
    with pytest.raises(SupplyContractError, match="SCALES_INVALID"):
        ctl._td_realization_scales(cfg)


def test_scale_one_preserves_exact_target_float():
    a = TDAdapter(); before = _parent(a)
    rows = ctl._td_rows_at_scale(before, [{"component": "WORK_E_C",
        "candidate_b": 0.08, "candidate_c": -0.1}], 1.0)
    assert rows[0]["candidate_b"] == 0.08
    assert rows[0]["candidate_c"] == -0.1


def test_half_scale_is_linear_b_and_log_negative_c():
    a = TDAdapter(); before = _parent(a)
    rows = ctl._td_rows_at_scale(before, [{"component": "WORK_E_C",
        "candidate_b": 0.2, "candidate_c": -0.4}], 0.5)
    assert rows[0]["candidate_b"] == pytest.approx(0.1)
    assert rows[0]["candidate_c"] == pytest.approx(-0.2)
    assert rows[0]["coordinate_system"] == "B_LINEAR_LOG_NEG_C"


def test_nonnegative_c_is_rejected():
    a = TDAdapter(); before = _parent(a)
    with pytest.raises(SupplyContractError, match="C_NOT_NEGATIVE"):
        ctl._td_rows_at_scale(before, [{"component": "WORK_E_C",
            "candidate_b": 0.2, "candidate_c": 0.0}], 0.5)


def test_retry_classifier_accepts_only_native_ipf_nonconvergence():
    assert ctl._is_retryable_td_realization_error(
        RuntimeError("IPF did not converge: max_rel_err=3e-6"))
    assert not ctl._is_retryable_td_realization_error(
        RuntimeError("foreign matrix changed"))


def test_realization_backtracks_to_first_full_downstream_success(tmp_path, monkeypatch):
    a = TDAdapter(fail_above=0.11); before = _parent(a)
    monkeypatch.setattr(ctl, "restore_td_parameters", _restore)
    rows, after, diag, gap, evidence = ctl._realize_finecdf_td(
        a, {"coupled_demand": {"finecdf_td": {
            "realization_backtracking_scales": [1.0, 0.5, 0.25]}}},
        tmp_path, Control(), before, {"label": "BASE", "constant": 1},
        [{"component": "WORK_E_C", "candidate_b": 0.2, "candidate_c": -0.4}])
    assert evidence["selected_scale"] == 0.5
    assert evidence["ipf_tolerance_relaxed"] is False
    assert [r["status"] for r in evidence["attempts"]] == [
        "RETRYABLE_NATIVE_IPF_NONCONVERGENCE", "REALIZED"]
    assert rows[0]["candidate_b"] == pytest.approx(0.1)
    assert rows[0]["candidate_c"] == pytest.approx(-0.2)
    assert after["td_values"][0]["current_b"] == pytest.approx(0.1)
    assert gap == pytest.approx(0.003)
    saved = json.loads((tmp_path / "TD_REALIZATION_ATTEMPTS.json").read_text())
    assert saved["selected_scale"] == 0.5


def test_non_ipf_failure_does_not_backtrack(tmp_path, monkeypatch):
    a = TDAdapter(hard_error=True); before = _parent(a)
    monkeypatch.setattr(ctl, "restore_td_parameters", _restore)
    with pytest.raises(RuntimeError, match="UNRELATED_ASSIGNMENT_FAILURE"):
        ctl._realize_finecdf_td(
            a, {}, tmp_path, Control(), before, {"label": "BASE", "constant": 1},
            [{"component": "WORK_E_C", "candidate_b": 0.2, "candidate_c": -0.4}])
    assert len(a.assign_calls) == 1


def test_exhausted_ipf_backtracking_fails_closed(tmp_path, monkeypatch):
    a = TDAdapter(fail_above=-1.0); before = _parent(a)
    monkeypatch.setattr(ctl, "restore_td_parameters", _restore)
    cfg = {"coupled_demand": {"finecdf_td": {
        "realization_backtracking_scales": [1.0, 0.5]}}}
    with pytest.raises(SupplyContractError, match="BACKTRACK_EXHAUSTED"):
        ctl._realize_finecdf_td(
            a, cfg, tmp_path, Control(), before, {"label": "BASE", "constant": 1},
            [{"component": "WORK_E_C", "candidate_b": 0.2, "candidate_c": -0.4}])
    evidence = json.loads((tmp_path / "TD_REALIZATION_ATTEMPTS.json").read_text())
    assert evidence["status"] == "FAILED"
    assert len(evidence["attempts"]) == 2
    assert all(x["ipf_tolerance_relaxed"] is False for x in evidence["attempts"])


def test_long_helper_destination_uses_run_root_central_mirror(tmp_path):
    run = tmp_path / "R1_15A2_V2489_RUNS" / ("RUN_" + "x" * 48)
    deep = run / "CALIBRATION" / ("D" * 90) / ("R" * 90)
    got = rt._durable_helper_paths(deep, "11D_ROLLBACK")
    assert got["mode"] == "RUN_ROOT_H_CENTRAL_SHORT_MIRROR"
    assert got["mirror"].is_relative_to(run / "H")
    assert len(str(got["mirror"])) < len(str(got["intended_mirror"]))


def test_atomic_evidence_copy_never_leaves_temp_file(tmp_path):
    source = tmp_path / "source.txt"; source.write_text("abc", encoding="utf-8")
    destination = tmp_path / "nested" / "destination.txt"
    assert rt._copy_if_file(source, destination) == destination
    assert destination.read_text(encoding="utf-8") == "abc"
    assert not list(destination.parent.glob("*.tmp_*"))


def test_controller_source_has_explicit_td_pending_generation_gate():
    text = Path(ctl.__file__).read_text(encoding="utf-8")
    assert "V2489_NEXT_GENERATION_BLOCKED_TD_REALIZATION_PENDING" in text
    assert 'result["td_realization_pending"] = True' in text
    assert 'result["td_realization_pending"] = False' in text
    assert text.index("V2489_NEXT_GENERATION_BLOCKED_TD_REALIZATION_PENDING") < \
           text.index('control.checkpoint("COUPLED_DEMAND_CYCLE_START"')
