# -*- coding: utf-8 -*-
"""Retry-safe, deterministic FlowBundle evidence adapter for V2.4.9.16.

Scientific boundary:
* frozen path incidence remains the numerical count-response authority;
* FlowBundle is read-only OD attribution / targeting evidence;
* NATIVE demand segments may target demand, EXOG_EE are diagnostic-only;
* failed profile×DSeg extractions fall back locally to PATH_ONLY;
* the production path uses one sealed COM signature and never probes invalid
  overloads that would pollute the Visum Messages window.
"""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import r1_15a2_com_compat as com
import r1_15a2_core as core


SEALED_CONTRACT_ID = "PTV_VISUM_2026_FLOWBUNDLE_LINK_DSEG_V24916_V1"


def fval(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
            if not value or value.lower() in ("nan", "none", "null"):
                return default
        result = float(value)
        return result if math.isfinite(result) else default
    except Exception:
        return default


def ival(value: Any, default: Optional[int] = None) -> Optional[int]:
    value = fval(value, None)
    return default if value is None else int(round(value))


def canonical_dseg(code: Any) -> str:
    return core.norm_code(code)


def dseg_family(code: Any) -> str:
    return core.family_from_dseg(canonical_dseg(code))


def dseg_role(code: Any) -> str:
    code = canonical_dseg(code)
    if code.startswith("NATIVE_"):
        return "TARGET_NATIVE"
    if code.startswith("EXOG_EE_"):
        return "DIAGNOSTIC_EXOG_EE"
    return "OTHER"


def _att(obj: Any, names: Sequence[str], default: Any = None) -> Any:
    for name in names:
        try:
            return obj.AttValue(str(name))
        except Exception:
            try:
                return getattr(obj, str(name))
            except Exception:
                pass
    return default


def _iter_collection(collection: Any, limit: int = 10000) -> Iterable[Any]:
    try:
        values = getattr(collection, "GetAll")
        values = values() if callable(values) else values
        for i, item in enumerate(values):
            if i >= limit:
                return
            yield item
        return
    except Exception:
        pass
    try:
        for i, item in enumerate(collection):
            if i >= limit:
                return
            yield item
        return
    except Exception:
        pass
    count = None
    for name in ("Count", "count"):
        try:
            count = getattr(collection, name)
            count = count() if callable(count) else count
            count = int(count)
            break
        except Exception:
            pass
    if count is None:
        return
    for i in range(1, min(count, limit) + 1):
        for name in ("ItemByKey", "Item", "GetItemByKey"):
            try:
                yield getattr(collection, name)(i)
                break
            except Exception:
                pass


def _profile_id(row: Mapping[str, Any]) -> str:
    for name in ("countlocation_no", "profile_id", "obs_id", "code"):
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def _profile_family(row: Mapping[str, Any]) -> str:
    raw = str(row.get("primary_family", row.get("family", "")) or "").upper()
    if raw.startswith("CW") or raw == "WORK":
        return "WORK"
    if raw.startswith("CS") or raw in ("SERV", "SERVICE"):
        return "SERVICE"
    return "OTHER"


def profile_directed_keys(row: Mapping[str, Any]) -> Tuple[Tuple[int, int, int], ...]:
    try:
        raw_keys = tuple(core._profile_link_keys(row))
    except Exception:
        return ()
    result: List[Tuple[int, int, int]] = []
    seen = set()
    for raw in raw_keys:
        try:
            key = tuple(int(x) for x in raw)
        except Exception:
            return ()
        if len(key) != 3:
            return ()
        if key not in seen:
            seen.add(key)
            result.append(key)
    return tuple(result)


def driver_profile_audit(rows: Sequence[Mapping[str, Any]], max_profiles: int,
                         min_geh: float, min_abs_residual: float) -> List[Dict[str, Any]]:
    staged: List[Dict[str, Any]] = []
    for index, raw in enumerate(rows or []):
        row = dict(raw)
        profile_id = _profile_id(row)
        role = str(row.get("role", "CALIBRATION") or "CALIBRATION").upper()
        active = row.get("active", row.get("r1_active", 1))
        active = str(active).strip().lower() not in ("0", "false", "no", "inactive")
        observed = fval(row.get("observed"), 0.0) or 0.0
        model = fval(row.get("model"), 0.0) or 0.0
        residual = observed - model
        geh = fval(row.get("geh"), 0.0) or 0.0
        family = _profile_family(row)
        conflict = bool(row.get("v249_duplicate_conflicted_driver", False))
        keys = profile_directed_keys(row)
        metadata_present = any(row.get(name) not in (None, "") for name in (
            "link_no", "link_link_no", "from_node_no", "link_from_node_no",
            "to_node_no", "link_to_node_no"))
        score = geh * 10.0 + abs(residual) / 100.0
        reason = "ELIGIBLE"
        if not active:
            reason = "INACTIVE"
        elif role != "CALIBRATION":
            reason = "NOT_CALIBRATION"
        elif conflict:
            reason = "DUPLICATE_CONFLICTED_DRIVER_EXCLUDED"
        elif metadata_present and not keys:
            reason = "INVALID_OR_UNRESOLVED_DIRECTED_SCOPE"
        elif family not in ("WORK", "SERVICE"):
            reason = "NON_WORK_SERVICE_FAMILY"
        elif observed <= 0.0:
            reason = "NONPOSITIVE_OBSERVED"
        elif residual <= 0.0:
            reason = "NOT_UNDERLOAD_POSITIVE_ONLY"
        elif geh < float(min_geh) and abs(residual) < float(min_abs_residual):
            reason = "BELOW_DRIVER_THRESHOLD"
        staged.append({
            "_source_index": index,
            "profile_id": profile_id,
            "countlocation_no": row.get("countlocation_no", ""),
            "role": role,
            "active": int(active),
            "observed": observed,
            "model": model,
            "residual": residual,
            "geh": geh,
            "scope_kind": str(row.get("observation_direction", "DIRECTED")).upper(),
            "edge_scope_hash": hashlib.sha256(repr(keys).encode("ascii", "replace")).hexdigest() if keys else "",
            "condition_count": len(keys),
            "driver_score": score,
            "selected": 0,
            "selection_rank": "",
            "selection_reason": reason,
            "driver_weight": fval(row.get("weight", row.get("objective_weight")), 1.0) or 1.0,
            "family_hint": family,
            "_v24916_family": family,
            "_v24916_residual": residual,
            "_v24916_score": score,
            "_v24916_profile_id": profile_id,
            "_source_row": row,
        })
    eligible = sorted((r for r in staged if r["selection_reason"] == "ELIGIBLE"),
                      key=lambda r: (-float(r["driver_score"]), r["profile_id"]))
    for rank, row in enumerate(eligible, 1):
        if rank <= int(max_profiles):
            row["selected"] = 1
            row["selection_rank"] = rank
            row["selection_reason"] = "SELECTED_UNDERLOAD_CAL_DRIVER"
        else:
            row["selection_reason"] = "EXCLUDED_BY_MAX_PROFILE_CAP"
    staged.sort(key=lambda r: (-float(r["driver_score"]), r["profile_id"], r["_source_index"]))
    return staged


def select_driver_profiles(rows: Sequence[Mapping[str, Any]], max_profiles: int,
                           min_geh: float, min_abs_residual: float) -> List[Dict[str, Any]]:
    selected = []
    for audit in driver_profile_audit(rows, max_profiles, min_geh, min_abs_residual):
        if not audit.get("selected"):
            continue
        source = dict(audit["_source_row"])
        source.update(
            _v24916_family=audit["_v24916_family"],
            _v24916_residual=audit["_v24916_residual"],
            _v24916_score=audit["_v24916_score"],
            _v24916_profile_id=audit["_v24916_profile_id"],
            _v249_profile_id=audit["_v24916_profile_id"],
            _v24916_condition_count=audit["condition_count"],
            _v24916_edge_scope_hash=audit["edge_scope_hash"],
        )
        selected.append(source)
    selected.sort(key=lambda r: (-float(r["_v24916_score"]), r["_v24916_profile_id"]))
    return selected


def _dseg_collection(visum: Any) -> Any:
    """Return the canonical PTV Visum 2026 demand-segment collection.

    The production runtime intentionally does not probe legacy aliases because
    failed COM member access can still be recorded in the Visum Messages
    window.  Compatibility probing belongs only in the separate live preflight.
    """
    try:
        return visum.Net.DemandSegments
    except Exception as exc:
        raise RuntimeError("V24916_DEMAND_SEGMENT_COLLECTION_UNAVAILABLE") from exc


def discover_dsegs(visum: Any, target_codes: Sequence[str],
                    diagnostic_codes: Sequence[str] = ()) -> List[Dict[str, Any]]:
    requested = {canonical_dseg(x): "TARGET_NATIVE" for x in target_codes}
    requested.update({canonical_dseg(x): "DIAGNOSTIC_EXOG_EE" for x in diagnostic_codes})
    collection = _dseg_collection(visum)
    out = []
    try:
        objects = com.collection_items(collection, "DemandSegments")
    except Exception as exc:
        raise RuntimeError("V24916_DEMAND_SEGMENT_ENUMERATION_FAILED") from exc
    for obj in objects:
        try:
            code = str(obj.AttValue("CODE") or "")
        except Exception as exc:
            raise RuntimeError("V24916_DEMAND_SEGMENT_CODE_UNREADABLE") from exc
        canonical = canonical_dseg(code)
        if canonical not in requested:
            continue
        out.append({
            "code": code,
            "canonical_code": canonical,
            "family": dseg_family(canonical),
            "object": obj,
            "role": requested[canonical],
        })
    out.sort(key=lambda r: (r["role"] != "TARGET_NATIVE", r["family"], r["canonical_code"]))
    return out


def _link_by_exact_key(visum: Any, key: Tuple[int, int, int]) -> Any:
    """Resolve a directed link by its official Visum external key.

    PTV Visum identifies a link in ``Links.ItemByKey`` by
    ``(FromNodeNo, ToNodeNo)``.  ``Link.No`` is verified afterwards as an
    additional R1 physical-link authority; it is not passed as a third key
    argument.  This avoids the invalid overload probing used in early drafts.
    """
    no, fr, to = map(int, key)
    links = visum.Net.Links
    try:
        obj = com.com_call_with_retry(
            lambda: links.ItemByKey(fr, to),
            "Links.ItemByKey(%s,%s)" % (fr, to),
        )
    except Exception:
        return None
    try:
        got = (
            ival(obj.AttValue("NO"), None),
            ival(obj.AttValue("FROMNODENO"), None),
            ival(obj.AttValue("TONODENO"), None),
        )
    except Exception:
        return None
    return obj if got == (no, fr, to) else None


def _link_objects(visum: Any, profile: Mapping[str, Any]) -> List[Any]:
    keys = profile_directed_keys(profile)
    if not keys:
        return []
    result = []
    for key in keys:
        obj = _link_by_exact_key(visum, key)
        if obj is None:
            return []
        result.append(obj)
    return result


@dataclass(frozen=True)
class FlowBundleContract:
    contract_id: str = SEALED_CONTRACT_ID
    demand_mode: str = "code"
    execution_method: str = "CreateCondition+ExecuteCurrentConditions"
    set_mode: str = "none"
    matrix_mode: str = "object"

    def as_dict(self) -> Dict[str, str]:
        return {
            "contract_id": self.contract_id,
            "demand_mode": self.demand_mode,
            "execution_method": self.execution_method,
            "set_mode": self.set_mode,
            "matrix_mode": self.matrix_mode,
        }


@dataclass
class FlowBundleExtraction:
    status: str
    rows: List[Dict[str, Any]]
    profile_status: List[Dict[str, Any]]
    selected_profiles: List[Dict[str, Any]]
    state_hash: str
    contract: FlowBundleContract
    fallback_reason: Optional[str] = None


def contract_hash(contract: Optional[FlowBundleContract]) -> str:
    if contract is None:
        return ""
    payload = "|".join(str(contract.as_dict()[k]) for k in sorted(contract.as_dict()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FlowBundleAdapter:
    def __init__(self, visum: Any, cfg: Mapping[str, Any]):
        self.visum = visum
        self.cfg = cfg
        self.contract = FlowBundleContract()
        self.retry_policy = cfg.get("com_resilience", {}) or {}
        self._cache: Dict[Tuple[str, int, int, int, str], Tuple[List[List[float]], float]] = {}
        self.retry_events: List[Dict[str, Any]] = []

    def _call(self, function, label: str):
        return com.com_call_with_retry(
            function,
            label=label,
            retry_policy=self.retry_policy,
            on_retry=lambda event: self.retry_events.append(dict(event)),
            on_exhausted=lambda event: self.retry_events.append(dict(event)),
        )

    def _flowbundle_object(self) -> Any:
        return self.visum.Net.FlowBundle

    def _clear(self, fb: Any) -> None:
        self._call(lambda: fb.Clear(), "FlowBundle.Clear")

    def _matrix_for_directed_link(self, state_hash: str, link_key: Tuple[int, int, int],
                                  link: Any, dseg: Mapping[str, Any]) -> Tuple[List[List[float]], float]:
        cache_key = (str(state_hash), int(link_key[0]), int(link_key[1]), int(link_key[2]),
                     canonical_dseg(dseg["canonical_code"]))
        if cache_key in self._cache:
            values, total = self._cache[cache_key]
            return values, total
        fb = self._flowbundle_object()
        self._clear(fb)
        try:
            code = str(dseg["code"])
            self._call(lambda: setattr(fb, "DemandSegments", code),
                       "FlowBundle.DemandSegments[%s]" % code)
            self._call(lambda: fb.CreateCondition(link, None, False, False, 0, 0),
                       "FlowBundle.CreateCondition[%s]" % repr(link_key))
            self._call(lambda: fb.ExecuteCurrentConditions(),
                       "FlowBundle.ExecuteCurrentConditions[%s]" % repr(link_key))
            matrix = self._call(
                lambda: fb.GetOrCreateFlowBundleMatrix(dseg["object"]),
                "FlowBundle.GetOrCreateFlowBundleMatrix[%s]" % code,
            )
            raw = self._call(lambda: matrix.GetValues(),
                             "FlowBundleMatrix.GetValues[%s]" % code)
            values: List[List[float]] = []
            total = 0.0
            for raw_row in raw:
                row = []
                for raw_value in raw_row:
                    value = fval(raw_value, 0.0) or 0.0
                    if value < 0.0:
                        raise RuntimeError("V24916_NEGATIVE_FLOWBUNDLE_VALUE")
                    row.append(value)
                    total += value
                values.append(row)
            self._cache[cache_key] = (values, total)
            return values, total
        finally:
            try:
                self._clear(fb)
            except Exception:
                pass

    def extract_snapshot(self, profile_rows: Sequence[Mapping[str, Any]], state_hash: str,
                         zone_numbers: Sequence[int], distance_lookup: Any = None) -> FlowBundleExtraction:
        cfg = self.cfg.get("demand_evidence_targeting", {}) or {}
        fcfg = cfg.get("flowbundle", {}) or {}
        selected = select_driver_profiles(
            profile_rows,
            int(fcfg.get("max_profiles", 30)),
            float(fcfg.get("min_profile_geh", 10.0)),
            float(fcfg.get("min_profile_abs_residual", 300.0)),
        )
        if not selected:
            return FlowBundleExtraction("PATH_ONLY_FALLBACK", [], [], [], str(state_hash),
                                        self.contract, "NO_ELIGIBLE_UNDERLOAD_DRIVERS")
        dsegs = discover_dsegs(
            self.visum,
            cfg.get("flowbundle_target_dsegs", fcfg.get("target_dsegs", [])),
            cfg.get("flowbundle_optional_diagnostic_dsegs", fcfg.get("optional_diagnostic_dsegs", [])),
        )
        target_requested = {canonical_dseg(x) for x in cfg.get("flowbundle_target_dsegs", fcfg.get("target_dsegs", []))}
        available_target = {d["canonical_code"] for d in dsegs if d["role"] == "TARGET_NATIVE"}
        if not (target_requested & available_target):
            return FlowBundleExtraction("PATH_ONLY_FALLBACK", [], [], selected, str(state_hash),
                                        self.contract, "TARGET_ASSIGNMENT_DSEGS_UNAVAILABLE")
        min_volume = float(fcfg.get("min_od_volume", 0.01))
        max_rows = int(fcfg.get("max_od_rows_per_profile", 3000))
        retained_target = float(fcfg.get("retained_volume_coverage", 0.90))
        minimum_coverage = float(fcfg.get("minimum_profile_coverage", 0.70))
        if not (0.0 < minimum_coverage <= retained_target <= 1.0):
            raise RuntimeError("V24916_INVALID_FLOWBUNDLE_COVERAGE_POLICY")
        if len(zone_numbers) != len(set(int(z) for z in zone_numbers)):
            raise RuntimeError("V24916_DUPLICATE_ZONE_ORDER")
        zones = [int(z) for z in zone_numbers]
        rows: List[Dict[str, Any]] = []
        status: List[Dict[str, Any]] = []
        for profile in selected:
            family = profile.get("_v24916_family") or _profile_family(profile)
            links = _link_objects(self.visum, profile)
            keys = profile_directed_keys(profile)
            if not links or len(links) != len(keys):
                status.append({"profile_id": _profile_id(profile), "status": "LINK_NOT_FOUND",
                               "targeting_mode": "PATH_ONLY_PROFILE_FALLBACK"})
                continue
            for dseg in [d for d in dsegs if d["family"] == family]:
                started = time.perf_counter()
                try:
                    combined: Dict[Tuple[int, int], float] = {}
                    full_total = 0.0
                    for key, link in zip(keys, links):
                        values, directional_total = self._matrix_for_directed_link(
                            str(state_hash), key, link, dseg)
                        if len(values) != len(zones) or any(len(r) != len(zones) for r in values):
                            raise RuntimeError("V24916_FLOWBUNDLE_MATRIX_SHAPE_MISMATCH")
                        full_total += directional_total
                        for oi, row_values in enumerate(values):
                            for di, volume in enumerate(row_values):
                                if volume < min_volume:
                                    continue
                                od = (zones[oi], zones[di])
                                combined[od] = combined.get(od, 0.0) + volume
                    detail = []
                    for (origin, destination), volume in combined.items():
                        rec = {
                            "profile_id": _profile_id(profile),
                            "countlocation_no": profile.get("countlocation_no", ""),
                            "family": family,
                            "dseg_code": dseg["canonical_code"],
                            "dseg_source_code": dseg["code"],
                            "dseg_role": dseg["role"],
                            "targeting_eligible": int(dseg["role"] == "TARGET_NATIVE"),
                            "origin": int(origin),
                            "destination": int(destination),
                            "flowbundle_volume": float(volume),
                            "observed": fval(profile.get("observed"), 0.0) or 0.0,
                            "model": fval(profile.get("model"), 0.0) or 0.0,
                            "residual": fval(profile.get("_v24916_residual"), 0.0) or 0.0,
                            "geh": fval(profile.get("geh"), 0.0) or 0.0,
                            "scope_kind": str(profile.get("observation_direction", "DIRECTED")).upper(),
                            "condition_count": len(links),
                            "edge_scope_hash": profile.get("_v24916_edge_scope_hash", ""),
                        }
                        if distance_lookup is not None:
                            rec["distance_km"] = distance_lookup(origin, destination)
                        detail.append(rec)
                    detail.sort(key=lambda r: (-r["flowbundle_volume"], r["origin"], r["destination"]))
                    kept = []
                    retained_volume = 0.0
                    for rec in detail:
                        if len(kept) >= max_rows:
                            break
                        kept.append(rec)
                        retained_volume += float(rec["flowbundle_volume"])
                        if retained_volume / max(full_total, 1.0e-12) >= retained_target:
                            break
                    coverage = retained_volume / max(full_total, 1.0e-12)
                    if full_total <= 0.0 or coverage < minimum_coverage:
                        status.append({
                            "profile_id": _profile_id(profile),
                            "dseg_code": dseg["canonical_code"],
                            "dseg_role": dseg["role"],
                            "status": "PATH_ONLY_PROFILE_FALLBACK",
                            "reason": "NO_POSITIVE_FLOW_OR_INSUFFICIENT_COVERAGE",
                            "flowbundle_total": full_total,
                            "retained_coverage": coverage,
                            "runtime_seconds": time.perf_counter() - started,
                        })
                        continue
                    for rec in kept:
                        rec["flowbundle_total"] = full_total
                        rec["retained_volume"] = retained_volume
                        rec["retained_coverage"] = coverage
                        rec["tail_volume"] = max(0.0, full_total - retained_volume)
                    rows.extend(kept)
                    status.append({
                        "profile_id": _profile_id(profile),
                        "dseg_code": dseg["canonical_code"],
                        "dseg_role": dseg["role"],
                        "scope_kind": str(profile.get("observation_direction", "DIRECTED")).upper(),
                        "condition_count": len(links),
                        "com_contract_id": SEALED_CONTRACT_ID,
                        "contract_sha256": contract_hash(self.contract),
                        "status": "OK",
                        "targeting_mode": ("FLOWBUNDLE_TARGETED" if dseg["role"] == "TARGET_NATIVE"
                                           else "DIAGNOSTIC_ONLY"),
                        "flowbundle_total": full_total,
                        "nonzero_od_rows": len(detail),
                        "retained_od_rows": len(kept),
                        "retained_volume": retained_volume,
                        "tail_volume": max(0.0, full_total - retained_volume),
                        "retained_coverage": coverage,
                        "runtime_seconds": time.perf_counter() - started,
                    })
                except Exception as exc:
                    status.append({
                        "profile_id": _profile_id(profile),
                        "dseg_code": dseg["canonical_code"],
                        "dseg_role": dseg["role"],
                        "status": "ERROR",
                        "targeting_mode": "PATH_ONLY_PROFILE_FALLBACK",
                        "runtime_seconds": time.perf_counter() - started,
                        "error": repr(exc)[:1200],
                    })
        target_rows = [r for r in rows if r.get("dseg_role") == "TARGET_NATIVE"]
        if not target_rows:
            return FlowBundleExtraction("PATH_ONLY_FALLBACK", rows, status, selected,
                                        str(state_hash), self.contract,
                                        "NO_POSITIVE_TARGET_FLOWBUNDLE_OD")
        return FlowBundleExtraction("ACTIVE", rows, status, selected,
                                    str(state_hash), self.contract)


__all__ = [
    "SEALED_CONTRACT_ID", "FlowBundleAdapter", "FlowBundleExtraction",
    "FlowBundleContract", "select_driver_profiles", "driver_profile_audit",
    "profile_directed_keys", "canonical_dseg", "dseg_role", "contract_hash",
]
