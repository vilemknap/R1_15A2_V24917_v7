"""Read-only live preflight for FlowBundle/DIST_KM shadow activation."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Mapping, Sequence
import hashlib, json

from r1_15a2_flowbundle_v24916p2c import ordered_zone_hash
from r1_15a2_safety_v24916p2c import build_safety_contract
from r1_15a2_skim_v24916p2c import SealedSkimIdentity

SCHEMA = "R1_15A2_V24916_PERF2C_LIVE_PREFLIGHT_V1"


def _hash(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreflightResult:
    schema: str
    passes: bool
    checks: tuple[Mapping[str, Any], ...]
    report_hash: str

    def as_dict(self):
        return asdict(self)


def run_read_only_preflight(
    *,
    config: Mapping[str, Any],
    zone_nos: Sequence[int],
    expected_zone_order_hash: str,
    skim_identity: SealedSkimIdentity | None,
    dseg_roles: Mapping[str, str],
    required_native_dsegs: Sequence[str],
    flowbundle_contract_hash: str,
    expected_flowbundle_contract_hash: str,
    reverse_link_proof: Mapping[str, Any] | None = None,
) -> PreflightResult:
    checks: list[dict[str, Any]] = []
    def add(name: str, passes: bool, **evidence: Any) -> None:
        checks.append({"name": name, "passes": bool(passes), "evidence": evidence})

    safety = build_safety_contract(config)
    add("SAFETY_CONTRACT", True, contract_hash=safety.contract_hash)
    actual_zone_hash = ordered_zone_hash(zone_nos)
    add("ZONE_ORDER", actual_zone_hash == expected_zone_order_hash, expected=expected_zone_order_hash, actual=actual_zone_hash, n=len(zone_nos))
    add("FLOWBUNDLE_CONTRACT", str(flowbundle_contract_hash) == str(expected_flowbundle_contract_hash), expected=expected_flowbundle_contract_hash, actual=flowbundle_contract_hash)
    missing = [d for d in required_native_dsegs if dseg_roles.get(d) != "TARGET_NATIVE"]
    add("NATIVE_DSEG_ROLES", not missing, missing=missing)
    add("DIST_KM_SEALED", skim_identity is not None, identity_hash=getattr(skim_identity, "identity_hash", None))
    if reverse_link_proof is not None:
        ev = dict(reverse_link_proof)
        passed = bool(ev.pop("passes", False))
        add("BOTH_REVERSE_LINK_PROOF", passed, **ev)

    passes = all(bool(c["passes"]) for c in checks)
    payload = {"schema": SCHEMA, "passes": passes, "checks": checks}
    return PreflightResult(schema=SCHEMA, passes=passes, checks=tuple(checks), report_hash=_hash(payload))
