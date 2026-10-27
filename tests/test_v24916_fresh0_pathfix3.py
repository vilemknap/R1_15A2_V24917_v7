from pathlib import Path
import importlib.util
import json

import r1_15a2_runtime_io_hotfix_profile488 as io
import r1_15a2_active_targeting_runtime_v24916_fresh0isolated as runtime


def test_v24916_short_runs_identity():
    assert runtime.RUNS_ROOT_NAME == "R1_15A2_V16_RUNS"
    assert runtime.LOCK_NAME == ".R1_15A2_V16.lock"
    assert "IOFIX3_PATHFIX3" in runtime.RELEASE


def test_v24916_projected_path_budget_is_below_240():
    run = Path(r"C:/Users/vilem_knap/Documents/VISUM/v45/2022") / runtime.RUNS_ROOT_NAME / "RUN_20261022_120000_123456"
    audit = io.audit_run_path_budget(run)
    assert audit["passes"] is True
    assert audit["max_projected_logical_length"] < 240
    labels = {row["label"] for row in audit["samples"]}
    assert "v24916_generation_evidence_manifest" in labels
    assert "v24916_td_evidence_manifest" in labels


def test_v24916_shortroot_parent_is_additive_and_uses_short_names():
    root = Path(__file__).resolve().parents[1]
    child = (root / "r1_15a2_fresh0_shortroot_parent_v24916.py").read_text(encoding="utf-8")
    parent = (root / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_FRESH100_PROFILE488_FRESHCACHE_SAVEFIX1_NO_WALLCLOCK.py").read_text(encoding="utf-8")
    assert 'else "R1_15A2_V16_RUNS"' in child
    assert '.R1_15A2_V16.lock' in child
    assert 'PATH_LENGTH_PREFLIGHT.json' in child
    assert 'else "R1_15A2_V16_RUNS"' not in parent


def test_v24916_launcher_uses_runtime_authority_path_and_critical_bootstrap():
    root = Path(__file__).resolve().parents[1]
    text = (root / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py").read_text(encoding="utf-8")
    assert 'r1_15a2_fresh0_shortroot_parent_v24916' in text
    assert 'critical_atomic_json' in text
    assert 'runtime_v24916_live_authority_path' in text


def test_v24916_specific_writers_are_hardened(tmp_path):
    import r1_15a2_coefficient_ledger_v24916 as ledger
    import r1_15a2_demand_evidence_v24916 as evidence
    import r1_15a2_fresh_baseline_live_preflight_v24916p2c as preflight

    deep = tmp_path
    while len(str(deep)) < 205:
        deep = deep / "deep_abcdefghijk"
    deep.mkdir(parents=True)

    ledger._atomic_json(deep / "ACCEPTED_PARENT_COEFFICIENTS.json", {"ok": True})
    ledger._write_csv(deep / "ACCEPTED_PARENT_COEFFICIENTS.csv", [{"a": 1}])
    evidence._write_json(deep / "14_DEMAND_EVIDENCE_MANIFEST.json", {"passes": True})
    evidence._write_csv(deep / "08_FLOWBUNDLE_PATH_PARITY.csv", [{"passes": True}])
    preflight.write_live_authority(deep / "V24916_FRESH0_ISOLATED_LIVE_AUTHORITY.json", {"passes": True})

    assert json.loads((deep / "ACCEPTED_PARENT_COEFFICIENTS.json").read_text(encoding="utf-8"))["ok"] is True
    assert json.loads((deep / "14_DEMAND_EVIDENCE_MANIFEST.json").read_text(encoding="utf-8"))["passes"] is True
    assert not list(deep.glob('.r1*.tmp'))
