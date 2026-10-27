"""Safety contracts for the V24916/PERF2C integration."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Mapping
import hashlib, json

SCHEMA = "R1_15A2_V24916_PERF2C_SAFETY_CONTRACT_V1"

HARD_INVARIANTS = {
    "candidate_math_changed": False,
    "candidate_order_changed": False,
    "assignment_method_changed": False,
    "assignment_gap_changed": False,
    "native_ipf_tolerance_changed": False,
    "live_12d_11d_acceptance_changed": False,
    "geh_acceptance_changed": False,
    "idp_acceptance_changed": False,
    "direct_od_matrix_writes": False,
    "flowbundle_is_acceptance_authority": False,
    "skim_is_acceptance_authority": False,
    "supply_targeting_enabled": False,
    "shortest_imp_oracle_enabled": False,
    "cross_run_evidence_cache": False,
    "production_com_probing": False,
}


def _hash(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class V24916SafetyContract:
    schema: str
    invariants: Mapping[str, bool]
    contract_hash: str


def build_safety_contract(config: Mapping[str, Any]) -> V24916SafetyContract:
    section = dict(config.get("v24916_flowbundle_skim_runtime") or config.get("performance", {}).get("v24916_flowbundle_skim", {}))
    actual = dict(HARD_INVARIANTS)
    actual["supply_targeting_enabled"] = bool(section.get("supply_targeting_enabled", False))
    actual["shortest_imp_oracle_enabled"] = bool(section.get("shortest_imp_oracle_enabled", False))
    actual["cross_run_evidence_cache"] = bool(section.get("cross_run_evidence_cache", False))
    actual["production_com_probing"] = bool(section.get("production_com_probing", False))
    violations = [k for k, v in actual.items() if bool(v) is not bool(HARD_INVARIANTS[k])]
    if violations:
        raise RuntimeError("V24916_SAFETY_CONTRACT_VIOLATION:" + ",".join(sorted(violations)))
    payload = {"schema": SCHEMA, "invariants": actual}
    return V24916SafetyContract(schema=SCHEMA, invariants=actual, contract_hash=_hash(payload))


def assert_feature_off_exact(config: Mapping[str, Any]) -> None:
    s = dict(config.get("performance", {}).get("v24916_flowbundle_skim", {}))
    if bool(s.get("enabled", False)):
        raise RuntimeError("V24916_FEATURE_OFF_GATE_EXPECTED_DISABLED")
    for key in ("generation_targeting_enabled", "td_mask_enabled", "combined_enabled"):
        if bool(s.get(key, False)):
            raise RuntimeError(f"V24916_FEATURE_OFF_GATE_{key.upper()}_MUST_BE_FALSE")
