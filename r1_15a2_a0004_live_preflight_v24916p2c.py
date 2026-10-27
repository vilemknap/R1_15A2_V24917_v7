# -*- coding: utf-8 -*-
"""Live read-only V24916 preflight bound to exact PROFILE488 A0004 recovery."""
from __future__ import annotations
import copy
from pathlib import Path
from typing import Any, Mapping

import r1_15a2_demand_continuation_profile488_a0004 as recovery
from r1_15a2_fresh_baseline_live_preflight_v24916p2c import (
    SCHEMA as _BASE_SCHEMA,
    build_live_authority as _build_base,
    require_live_authority_current as _require_base,
    write_live_authority,
)
from r1_15a2_active_targeting_runtime_v24916_a0004 import (
    AUTHORITY_FILE, RELEASE, EXPECTED_ACCEPTED_COUNT, EXPECTED_MAX_OUTER_CYCLES,
    EXPECTED_OUTER_CYCLE, EXPECTED_PARENT_CHECKPOINT,
    EXPECTED_PARENT_SEMANTIC_STATE_HASH, EXPECTED_RESUME_SUBSTEP,
)

SCHEMA = "R1_15A2_V24916_PROFILE488_A0004_LIVE_AUTHORITY_V1"


def _resolved_from_report(report: Mapping[str, Any], root: Path) -> dict[str, Any]:
    semantic = {
        "semantic_state_hash": report.get("source_semantic_state_hash"),
        "semantic_hashes": copy.deepcopy(report.get("source_semantic_hashes") or {}),
    }
    return recovery.resolve_continuation(
        Path(str(report.get("current_version_file"))), semantic, root)


def build_live_authority(visum: Any, base_cfg: Mapping[str, Any], root: Path) -> dict[str, Any]:
    root = Path(root)
    report = _build_base(visum, base_cfg, root)
    resolved = _resolved_from_report(report, root)
    if report.get("source_semantic_state_hash") != EXPECTED_PARENT_SEMANTIC_STATE_HASH:
        raise RuntimeError("V24916_A0004_PREFLIGHT_SEMANTIC_MISMATCH")
    if Path(str(report.get("current_version_file"))).name != EXPECTED_PARENT_CHECKPOINT:
        raise RuntimeError("V24916_A0004_PREFLIGHT_CHECKPOINT_NAME_MISMATCH")
    report["schema"] = SCHEMA
    report["release"] = RELEASE
    report["activation_stage"] = "PREFLIGHT_FOR_A0004_CYCLE3_TD_RESUME_ACTIVE_TARGETING"
    report["parent_recovery"] = {
        "passes": True,
        "checkpoint": EXPECTED_PARENT_CHECKPOINT,
        "semantic_state_hash": EXPECTED_PARENT_SEMANTIC_STATE_HASH,
        "accepted_count": EXPECTED_ACCEPTED_COUNT,
        "outer_cycle": EXPECTED_OUTER_CYCLE,
        "resume_substep": EXPECTED_RESUME_SUBSTEP,
        "resume_generation_completed": True,
        "max_outer_cycles": EXPECTED_MAX_OUTER_CYCLES,
        "cross_run_path_cache_restore_allowed": False,
        "fresh_recovery_path_epoch_required": True,
        "resolved_continuation": resolved,
    }
    report.pop("fresh_lineage", None)
    report["lineage_context"] = {
        "new_lineage": False,
        "continuation_from_a0004": True,
        "accepted_count_start": EXPECTED_ACCEPTED_COUNT,
        "outer_cycle_start": EXPECTED_OUTER_CYCLE,
        "resume_substep": EXPECTED_RESUME_SUBSTEP,
        "generation_targeting_first_possible_substep": "NEXT_GENERATION_AFTER_RESUMED_CYCLE3_TD",
        "td_targeting_first_possible_substep": "RESUMED_CYCLE3_TD_AFTER_FRESH_PATH_ENUMERATION",
    }
    report["active_v24916_actuators"] = []
    report["certifies_next_step_actuators"] = [
        "GENERATION_FLOWBUNDLE_TARGETING", "TD_COMPONENT_MASK"
    ]
    # Caller recomputes authority_hash after adding package gates.
    report.pop("authority_hash", None)
    return report


def require_live_authority_current(visum: Any, base_cfg: Mapping[str, Any], root: Path,
                                   authority: Mapping[str, Any]) -> dict[str, Any]:
    if authority.get("passes") is not True or authority.get("schema") != SCHEMA:
        raise RuntimeError("V24916_A0004_LIVE_AUTHORITY_NOT_PASSED")
    shadow = copy.deepcopy(dict(authority))
    shadow["schema"] = _BASE_SCHEMA
    base = _require_base(visum, base_cfg, Path(root), shadow)
    current_file = Path(str(visum.IO.CurrentVersionFile))
    if current_file.name != EXPECTED_PARENT_CHECKPOINT:
        raise RuntimeError("V24916_A0004_MODEL_CHANGED_TO_DIFFERENT_CHECKPOINT")
    if base.get("semantic_state_hash") != EXPECTED_PARENT_SEMANTIC_STATE_HASH:
        raise RuntimeError("V24916_A0004_MODEL_SEMANTIC_CHANGED_SINCE_PREFLIGHT")
    return {
        "schema": "R1_15A2_V24916_A0004_REVALIDATION_V1",
        "passes": True,
        "checkpoint": current_file.name,
        "semantic_state_hash": base.get("semantic_state_hash"),
        "zone_order_sha256": base.get("zone_order_sha256"),
        "dist_km_identity_hash": base.get("dist_km_identity_hash"),
        "authority_hash": authority.get("authority_hash"),
        "accepted_count_start": EXPECTED_ACCEPTED_COUNT,
        "outer_cycle_start": EXPECTED_OUTER_CYCLE,
        "resume_substep": EXPECTED_RESUME_SUBSTEP,
    }


__all__ = ["SCHEMA", "AUTHORITY_FILE", "build_live_authority",
           "require_live_authority_current", "write_live_authority"]
