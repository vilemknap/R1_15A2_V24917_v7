# -*- coding: utf-8 -*-
"""Verified V24912/V24913 demand-convergence handoff into route-choice supply.

The physical start state is always the version currently opened in Visum.  A
nearby DEMAND_CONVERGED.json is used only as an authority that this exact state
completed the configured coupled TG/TD fixed-point criterion.  No rejected or
in-memory candidate is ever loaded or promoted.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from r1_15a2_supply import SupplyContractError
from r1_15a2_overnight_controller_v240 import atomic_json, run_overnight_calibration

CRITERION = "CONSECUTIVE_COMPLETE_SUCCESSFUL_CONFIGURED_TG_TD_SEARCHES_WITH_NO_CHANGE"


def _candidate_authority_paths(source_version: Path):
    source_version = Path(source_version).resolve()
    seen = set()
    for anc in (source_version.parent,) + tuple(source_version.parent.parents):
        for path in (anc / "DEMAND_CONVERGED.json",
                     anc / "CALIBRATION" / "DEMAND_CONVERGED.json"):
            key = str(path)
            if key not in seen:
                seen.add(key)
                yield path


def discover_demand_convergence_authority(source_version: Path) -> Mapping[str, Any]:
    candidates = []
    for path in _candidate_authority_paths(Path(source_version)):
        if not path.is_file():
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            candidates.append({"path": str(path), "valid": False, "error": str(exc)})
            continue
        valid = (
            str(obj.get("criterion", "")) == CRITERION
            and int(obj.get("stationary_cycle_streak", 0) or 0) >= 2
            and isinstance(obj.get("state_hash"), str)
            and len(obj.get("state_hash")) == 64
        )
        candidates.append({"path": str(path), "valid": valid, "authority": obj})
        if valid:
            return {"path": str(path), "authority": obj, "candidates_checked": candidates}
    raise SupplyContractError(
        "V24913_SUPPLY_ONLY_REQUIRES_VALID_DEMAND_CONVERGENCE_AUTHORITY:" +
        json.dumps(candidates, sort_keys=True))


def run_verified_supply_only(adapter, cfg: Mapping[str, Any], folder: Path,
                             control, source_version: Path) -> Mapping[str, Any]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    handoff = discover_demand_convergence_authority(Path(source_version))
    before = adapter.snapshot()
    authority = handoff["authority"]
    if before.get("state_hash") != authority.get("state_hash"):
        raise SupplyContractError(
            "V24913_OPEN_MODEL_DOES_NOT_MATCH_DEMAND_CONVERGED_STATE:%s:%s" %
            (before.get("state_hash"), authority.get("state_hash")))

    evidence = {
        "schema": "R1_15A2_V24913_VERIFIED_DEMAND_TO_SUPPLY_HANDOFF_V1",
        "source_version": str(Path(source_version).resolve()),
        "demand_convergence_authority_path": handoff["path"],
        "demand_convergence_authority": authority,
        "live_state_hash": before.get("state_hash"),
        "matrix_hash": before.get("matrix_hash"),
        "generation_hash": before.get("generation_hash"),
        "td_hash": before.get("td_hash"),
        "criterion_verified": True,
        "supply_only": True,
        "demand_parameters_frozen_during_supply": True,
    }
    atomic_json(folder / "VERIFIED_DEMAND_TO_SUPPLY_HANDOFF.json", evidence)

    supply_cfg = copy.deepcopy(dict(cfg))
    supply_cfg["runtime_execution_mode"] = "SUPPLY_ONLY_FROM_VERIFIED_DEMAND_CONVERGENCE"
    supply_cfg["block_schedule"] = ["SUPPLY_ADDVAL1"]
    supply_cfg.setdefault("trial_calibration", {})["max_cycles"] = int(
        supply_cfg.get("supply_route_choice_acceptance", {}).get("max_supply_cycles", 100))
    supply_cfg["calibration_phases"] = []
    result = run_overnight_calibration(adapter, supply_cfg, folder / "SUPPLY_ROUTE_CHOICE", control)
    result = dict(result)
    result["execution_mode"] = "SUPPLY_ONLY_FROM_VERIFIED_DEMAND_CONVERGENCE"
    result["demand_convergence_handoff"] = evidence

    after = adapter.snapshot()
    for name in ("matrix_hash", "generation_hash", "td_hash"):
        if after.get(name) != before.get(name):
            raise SupplyContractError("V24913_SUPPLY_MUTATED_CONVERGED_DEMAND:" + name)
    result["converged_demand_hashes_preserved"] = True
    return result


__all__ = ["CRITERION", "discover_demand_convergence_authority",
           "run_verified_supply_only"]
