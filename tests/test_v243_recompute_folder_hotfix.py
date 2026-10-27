from pathlib import Path
import importlib.util
import json

from r1_15a2_trial_adapter_v243 import VisumAdapter

ROOT = Path(__file__).resolve().parents[1]

def test_v243_adapter_creates_recompute_folder_before_super(monkeypatch, tmp_path):
    target = tmp_path / "CALIBRATION" / "BASELINE_FULL_RECOMPUTE"
    seen = {}
    from r1_15a2_trial_adapter_v240 import VisumAdapter as Parent
    def fake_assign(self, folder, *, supply_only):
        seen["exists"] = Path(folder).is_dir()
        seen["folder"] = Path(folder)
        return 0.001
    monkeypatch.setattr(Parent, "assign", fake_assign)
    obj = object.__new__(VisumAdapter)
    assert obj.assign(target, supply_only=False) == 0.001
    assert seen["exists"] is True
    assert seen["folder"] == target

def test_v243_entrypoint_requires_verified_final_state_for_final_save():
    text = (ROOT / "R1_15A2_FULL_OVERNIGHT_COUPLED_V2_4_3.py").read_text(encoding="utf-8")
    assert 'verified_final = bool(result.get("final_state_hash"))' in text
    assert 'not status_text.startswith(("FAILED", "FULL_OVERNIGHT_FAILED", "LIVE_API_PREFLIGHT_FAILED"))' in text
    assert 'final_accepted_version_not_written' in text

def test_v243_keeps_coupled_demand_iteration_authority():
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_3.json").read_text(encoding="utf-8"))
    assert cfg["coupled_demand"]["max_outer_cycles"] == 12
    assert cfg["coupled_demand"]["finecdf_td"]["max_iterations"] == 35
    assert cfg["coupled_demand"]["finecdf_td"]["max_td_evaluations"] == 180
    assert cfg["coupled_demand"]["convergence_rule"] == "NO_ACCEPTED_GENERATION_AND_NO_ACCEPTED_FINECDF_TD_IN_SAME_OUTER_CYCLE"
