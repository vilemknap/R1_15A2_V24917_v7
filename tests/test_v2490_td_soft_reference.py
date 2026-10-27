import copy
import json
import math
from pathlib import Path

import pytest

import r1_15a2_overnight_controller_v242 as ctl
import r1_15a2_finecdf_bridge_v242 as bridge
from r1_15a2_supply import SupplyContractError, canonical_hash

ROOT = Path(__file__).resolve().parents[1]


class Control:
    def checkpoint(self, *args, **kwargs):
        pass


class SoftAdapter:
    def __init__(self, accept_below=None, always_reject=False, hard_error=False):
        self.b = 0.0
        self.c = -0.1
        self.accept_below = accept_below
        self.always_reject = always_reject
        self.hard_error = hard_error
        self.assign_calls = []
        self.gate_calls = []
        self.cfg = {}

    def snapshot(self):
        td = [{"component": "WORK_E_C", "current_b": self.b,
               "current_c": self.c, "status": "OK", "authority_id": "A"}]
        matrices = [{"matrix_no": 9101, "rows": 2, "cols": 2,
                     "sha256_float64_le": canonical_hash([self.b, self.c])}]
        out = {
            "fixed_link_hash": "F", "dseg_hash": "D", "operations_hash": "O",
            "addval_hash": "A", "generation_hash": "G",
            "td_values": td, "td_hash": canonical_hash(sorted(td, key=lambda r: r["component"])),
            "matrices": matrices, "dseg_map": {"NATIVE_CW": 9101},
            "addval1": {},
        }
        out["state_hash"] = canonical_hash(out)
        return out

    def apply_td(self, rows):
        if rows:
            self.b = float(rows[0]["candidate_b"])
            self.c = float(rows[0]["candidate_c"])

    def assign(self, folder, *, supply_only):
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.assign_calls.append((self.b, self.c))
        if self.hard_error:
            raise RuntimeError("UNRELATED_ASSIGNMENT_FAILURE")
        return 0.002

    def parameter_persistence(self, block, rows):
        return None

    def diagnostics(self, folder, label):
        Path(folder).mkdir(parents=True, exist_ok=True)
        # Diagnostics must be a pure read in this synthetic contract.
        return {"constant": 1, "d12": {"rows": []}, "d11": {"summary": {}},
                "signals": {}}

    def block_gate(self, block, before, after, rows):
        self.gate_calls.append((block, self.b, copy.deepcopy(rows)))
        accepted = not self.always_reject
        if self.accept_below is not None:
            accepted = self.b <= self.accept_below
        return {
            "accepted": accepted,
            "reasons": [] if accepted else ["SOFT_REFERENCE_TRADEOFF_GUARD"],
            "selected_relative_improvement": 0.01 if accepted else -0.01,
        }


def _parent(adapter):
    adapter.b = 0.0
    adapter.c = -0.1
    return adapter.snapshot()


def _restore(adapter, before, rows, folder=None):
    by = {r["component"]: r for r in before["td_values"]}
    old = by["WORK_E_C"]
    adapter.b = float(old["current_b"])
    adapter.c = float(old["current_c"])
    return [{"status": "OK"}]


def _soft_cfg(scales=(1.0, 0.5, 0.25)):
    return {
        "coupled_demand": {"finecdf_td": {
            "realization_backtracking_scales": list(scales),
            "realization_parameter_atol": 1.0e-8,
            "realization_parameter_rtol": 1.0e-10,
        }},
        "td_soft_reference_policy": {
            "enabled": True,
            "exact_curve_match_required": False,
            "native_ipf_tolerance_relaxed": False,
        },
    }


def test_v2490_config_declares_survey_as_soft_reference():
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_9_0.json").read_text(encoding="utf-8"))
    assert cfg["td"]["survey_reference_role"] == "SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT"
    assert cfg["td"]["exact_curve_match_required"] is False
    assert cfg["td"]["min_selected_component_relative_improvement"] == pytest.approx(0.005)
    assert cfg["td"]["max_selected_component_relative_degradation"] == pytest.approx(0.05)
    assert cfg["td"]["max_nonselected_component_objective_degradation"] == pytest.approx(0.05)
    fine = cfg["coupled_demand"]["finecdf_td"]
    assert fine["ipf_tolerance_policy"] == "UNCHANGED_NEVER_RELAXED_BY_CALIBRATOR"
    assert fine["exact_curve_match_required"] is False


def test_v19_reference_is_hash_locked_and_stops_chasing_micro_gains():
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_9_0.json").read_text(encoding="utf-8"))
    fine = cfg["coupled_demand"]["finecdf_td"]
    mod, path, got = bridge.load_reference(ROOT, fine)
    assert got == fine["reference_sha256"]
    assert mod.SCRIPT_ID == fine["reference_script_id"]
    assert mod.CONFIG["minimum_relative_objective_improvement"] == pytest.approx(0.001)
    assert mod.CONFIG["max_fine_cdf_rmse_degradation"] == pytest.approx(0.01)
    assert mod.CONFIG["max_mean_error_degradation"] == pytest.approx(0.02)


def _two_component_snapshot():
    td = [
        {"component": "WORK_E_C", "current_b": 1.0, "current_c": -0.1,
         "status": "OK", "authority_id": "W"},
        {"component": "SERV_E_C", "current_b": 2.0, "current_c": -0.2,
         "status": "OK", "authority_id": "S"},
    ]
    return {
        "fixed_link_hash": "F", "dseg_hash": "D", "operations_hash": "O",
        "addval_hash": "A", "generation_hash": "G",
        "td_values": td, "td_hash": canonical_hash(sorted(td, key=lambda r: r["component"])),
    }


def test_td_freeze_tolerates_only_machine_level_bc_roundtrip(tmp_path):
    before = _two_component_snapshot()
    after = copy.deepcopy(before)
    rows = [{"component": "WORK_E_C", "candidate_b": 1.2, "candidate_c": -0.12}]
    for r in after["td_values"]:
        if r["component"] == "WORK_E_C":
            r["current_b"] = 1.2 + 4e-9
            r["current_c"] = -0.12 - 4e-9
        else:
            r["current_b"] += 4e-9
            r["current_c"] -= 4e-9
    after["td_hash"] = canonical_hash(sorted(after["td_values"], key=lambda r: r["component"]))
    audit = tmp_path / "freeze.json"
    ctl._td_expected_freeze(before, after, rows, _soft_cfg(), audit)
    saved = json.loads(audit.read_text(encoding="utf-8"))
    assert saved["passes"] is True
    assert saved["comparison"] == "EXACT_FROZEN_CONTEXT_AND_METADATA__NUMERIC_B_C_ONLY"


def test_td_freeze_rejects_material_unrequested_change():
    before = _two_component_snapshot(); after = copy.deepcopy(before)
    after["td_values"][1]["current_b"] += 1e-5
    after["td_hash"] = canonical_hash(sorted(after["td_values"], key=lambda r: r["component"]))
    with pytest.raises(SupplyContractError, match="V2490_TD_UNREQUESTED_PARAMETER_CHANGE:SERV_E_C"):
        ctl._td_expected_freeze(before, after, [], _soft_cfg())


def test_td_freeze_retains_exact_frozen_context_and_metadata():
    before = _two_component_snapshot(); after = copy.deepcopy(before)
    after["generation_hash"] = "OTHER"
    with pytest.raises(SupplyContractError, match="V242_TD_CHANGED_FROZEN_CONTEXT:generation_hash"):
        ctl._td_expected_freeze(before, after, [], _soft_cfg())
    after = copy.deepcopy(before)
    after["td_values"][0]["authority_id"] = "CHANGED"
    after["td_hash"] = canonical_hash(sorted(after["td_values"], key=lambda r: r["component"]))
    with pytest.raises(SupplyContractError, match="V2490_TD_PARAMETER_METADATA_CHANGED:WORK_E_C"):
        ctl._td_expected_freeze(before, after, [], _soft_cfg())


def test_soft_reference_backtracks_after_realized_but_rejected_candidate(tmp_path, monkeypatch):
    a = SoftAdapter(accept_below=0.11); before = _parent(a)
    monkeypatch.setattr(ctl, "restore_td_parameters", _restore)
    rows, after, diag, gap, evidence = ctl._realize_finecdf_td(
        a, _soft_cfg(), tmp_path, Control(), before, a.diagnostics(tmp_path / "base", "BASE"),
        [{"component": "WORK_E_C", "candidate_b": 0.2, "candidate_c": -0.4}])
    assert evidence["selected_scale"] == pytest.approx(0.5)
    assert [x["status"] for x in evidence["attempts"]] == [
        "REJECTED_SOFT_REFERENCE_GUARD", "REALIZED"]
    assert rows[0]["candidate_b"] == pytest.approx(0.1)
    assert rows[0]["candidate_c"] == pytest.approx(-0.2)
    assert evidence["exact_curve_match_required"] is False
    assert evidence["ipf_tolerance_relaxed"] is False


def test_all_soft_reference_candidates_rejected_becomes_verified_parent_plateau(tmp_path, monkeypatch):
    a = SoftAdapter(always_reject=True); before = _parent(a)
    baseline = a.diagnostics(tmp_path / "base", "BASE")
    monkeypatch.setattr(ctl, "restore_td_parameters", _restore)
    monkeypatch.setattr(ctl, "diagnostic_hash", lambda d: canonical_hash(d))
    rows, after, diag, gap, evidence = ctl._realize_finecdf_td(
        a, _soft_cfg((1.0, 0.5)), tmp_path, Control(), before, baseline,
        [{"component": "WORK_E_C", "candidate_b": 0.2, "candidate_c": -0.4}])
    assert rows == []
    assert gap is None
    assert evidence["status"] == "SOFT_REFERENCE_PLATEAU"
    assert evidence["plateau_reason"] == "NO_SAFE_MATERIAL_FULL_DOWNSTREAM_TD_IMPROVEMENT"
    assert after["state_hash"] == before["state_hash"]
    assert [x["status"] for x in evidence["attempts"]] == [
        "REJECTED_SOFT_REFERENCE_GUARD", "REJECTED_SOFT_REFERENCE_GUARD"]
    rb = json.loads((tmp_path / "SOFT_REFERENCE_PLATEAU_ROLLBACK" /
                     "ROLLBACK_ALL_TD_RESULT.json").read_text(encoding="utf-8"))
    assert rb["passes"] is True


def test_unrelated_full_downstream_failure_remains_hard(tmp_path, monkeypatch):
    a = SoftAdapter(hard_error=True); before = _parent(a)
    monkeypatch.setattr(ctl, "restore_td_parameters", _restore)
    with pytest.raises(RuntimeError, match="UNRELATED_ASSIGNMENT_FAILURE"):
        ctl._realize_finecdf_td(
            a, _soft_cfg(), tmp_path, Control(), before,
            a.diagnostics(tmp_path / "base", "BASE"),
            [{"component": "WORK_E_C", "candidate_b": 0.2, "candidate_c": -0.4}])
    evidence = json.loads((tmp_path / "TD_REALIZATION_ATTEMPTS.json").read_text())
    assert evidence["status"] == "FAILED"
    assert len(evidence["attempts"]) == 1
