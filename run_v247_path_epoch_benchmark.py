# -*- coding: utf-8 -*-
"""Offline controller-call benchmark for V2.4.7 path epochs.

Counts path-enumeration requests in synthetic controller workflows.  This is
not a real PTV Visum wall-time benchmark and makes no production speed claim.
"""
from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path
from types import MethodType
from _pytest.monkeypatch import MonkeyPatch

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))

import r1_15a2_overnight_controller_v242 as coupled
from test_v245_workflow import setup_workflow, ROOT


def execute(policy, repeated_generation=False):
    root = Path(tempfile.mkdtemp(prefix="r1_v247_bench_"))
    mp = MonkeyPatch()
    try:
        cfg, control, adapter = setup_workflow(root, mp)
        if repeated_generation:
            adapter.once_generation = False
            cfg["coupled_demand"]["max_outer_cycles"] = 12
        adapter._benchmark_cache_valid = False
        adapter._benchmark_enumerations = []
        original_generation = adapter.generation_design
        original_supply = adapter.supply_design

        def ensure(phase):
            if not adapter._benchmark_cache_valid:
                adapter._benchmark_enumerations.append({"phase": phase, "reason": "CACHE_REQUIRED"})
                adapter._benchmark_cache_valid = True

        def generation(self, *args, **kwargs):
            ensure("GENERATION")
            return original_generation(*args, **kwargs)

        def supply(self, *args, **kwargs):
            ensure("SUPPLY")
            return original_supply(*args, **kwargs)

        adapter.generation_design = MethodType(generation, adapter)
        adapter.supply_design = MethodType(supply, adapter)

        if policy == "V246_INVALIDATE_AFTER_ACCEPT":
            def invalidate(self, reason="STATE_CHANGED", clear_proof=False):
                self._benchmark_cache_valid = False
            adapter.invalidate_cache = MethodType(invalidate, adapter)
        else:
            verified = set()
            def accepted(self, snapshot, diag=None, *, reason="ACCEPTED_STATE_CHANGED", phase="DEMAND"):
                return {"retained": True, "phase": phase, "reason": reason}
            def plateau(self, diag, folder, snapshot, *, phase):
                key = (phase, snapshot["state_hash"])
                if key not in verified:
                    self._benchmark_enumerations.append({"phase": phase, "reason": "LOCAL_PLATEAU_REFRESH"})
                    verified.add(key)
                return {"stationarity_confirmed": True, "basis_changed": False,
                        "action": "FRESH_ENUMERATION_CONFIRMED_LOCAL_PLATEAU"}
            adapter.accepted_state_changed = MethodType(accepted, adapter)
            adapter.path_epoch_plateau_gate = MethodType(plateau, adapter)

        result = coupled.run_overnight_calibration_coupled(
            adapter, cfg, root / "workflow", control, ROOT)
        return {
            "policy": policy,
            "repeated_generation": repeated_generation,
            "status": result["status"],
            "calibration_complete": result.get("calibration_complete"),
            "accepted_count": result.get("accepted_count"),
            "path_enumeration_requests": len(adapter._benchmark_enumerations),
            "enumerations": adapter._benchmark_enumerations,
            "generation_design_calls": adapter.generation_design_calls,
            "supply_design_calls": adapter.supply_design_calls,
            "assignment_or_recompute_calls": len(adapter.assignments),
        }
    finally:
        mp.undo()


def comparison(name, repeated_generation):
    old = execute("V246_INVALIDATE_AFTER_ACCEPT", repeated_generation)
    new = execute("V247_FROZEN_PATH_EPOCH", repeated_generation)
    old_n = old["path_enumeration_requests"]
    new_n = new["path_enumeration_requests"]
    return {
        "name": name,
        "v246_model": old,
        "v247_model": new,
        "enumeration_reduction": old_n - new_n,
        "enumeration_reduction_fraction": (old_n-new_n)/old_n if old_n else None,
        "same_status": old["status"] == new["status"],
        "same_accepted_count": old["accepted_count"] == new["accepted_count"],
    }


def main():
    result = {
        "schema": "R1_15A2_V247_PATH_ENUMERATION_BENCHMARK_V1",
        "scope": "OFFLINE_SYNTHETIC_CONTROLLER_CALL_COUNTS_NOT_REAL_VISUM_WALL_TIME",
        "completed_small_fixture": comparison("COMPLETED_SMALL_FIXTURE", False),
        "accepted_state_stress_fixture": comparison("TWELVE_ACCEPTED_DEMAND_STATES", True),
        "interpretation": (
            "The small fixture has no enumeration saving because V2.4.7 deliberately spends "
            "fresh enumerations to certify demand and supply plateaus. The repeated-acceptance "
            "fixture isolates the intended benefit: accepted states reuse one path epoch until plateau."),
        "real_visum_speedup_claim": None,
    }
    out = Path(__file__).resolve().parent / "V247_PATH_ENUMERATION_BENCHMARK.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
