# -*- coding: utf-8 -*-
"""Live, read-only bootstrap preflight for a NEW calibration lineage.

This preflight is intentionally separate from calibration.  It binds the
currently opened Visum model, seals its semantic identity, zone order,
static OSRM distance as reference-only provenance, the six configured native
assignment-path DIS skim slots, and DSeg roles, then exercises the sealed FlowBundle COM signature on
small representative samples.  It never executes Procedure Sequence,
assignment or coefficient writes.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import r1_15a2_runtime_io_hotfix_profile488 as runtime_io_hotfix
from typing import Any, Iterable, Mapping, Sequence

import r1_15a2_com_compat as com
import r1_15a2_restart_v2494 as restart
import r1_15a2_runtime_v1 as rt
from r1_15a2_flowbundle_v24916 import (
    FlowBundleContract, contract_hash, discover_dsegs, dseg_role,
)
from r1_15a2_flowbundle_v24916p2c import (
    FlowBundleMatrixReducer, ordered_zone_hash,
)
from r1_15a2_skim_v24916 import zone_numbers
from r1_15a2_skim_v24916p2c import seal_dist_km
from r1_15a2_dynamic_skim_v24916p2c import (
    REQUIRED_NATIVE_DSEGS, active_native_skim_positions, _native_dis_rows,
)
from r1_15a2_trial_adapter_v24916p2c import VisumAdapter
from r1_15a2_active_targeting_runtime_v24916_fresh0isolated import (
    AUTHORITY_FILE, RELEASE, apply_active_runtime_delta,
)

# Historical function name retained internally; this preflight now validates the
# exact ACTIVE PROFILE488 overlay configuration.
apply_fresh_runtime_delta = apply_active_runtime_delta

SCHEMA = "R1_15A2_V24916_FRESH_EE_BASELINE_LIVE_AUTHORITY_V1"
EXACT_DISTANCE_CODES = ("R1_OSRM_DIST_KM", "DIST_KM")


def _preflight_adapter_cfg(base_cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Build a V24916 adapter config that is safe before any RUN_* exists.

    PersistentPathCacheManager requires ``runtime_persistent_path_cache_root``
    when enabled.  That root is intentionally created only by the calibration
    launcher after it has allocated the new RUN_* folder.  The live preflight
    needs only read-only snapshot/FlowBundle/skim access, so persistent-cache
    initialization is disabled here instead of inventing an early cache root.
    This does not alter the later calibration config or path-epoch policy.
    """
    cfg = apply_fresh_runtime_delta(base_cfg)
    perf = cfg.setdefault("performance", {})
    persistent = perf.setdefault("persistent_path_cache", {})
    persistent["enabled"] = False
    cfg.pop("runtime_persistent_path_cache_root", None)
    cfg["runtime_legacy_path_cache_roots"] = []
    cfg["v24916_preflight_path_cache_policy"] = {
        "enabled": False,
        "reason": "NO_RUN_ROOT_EXISTS_DURING_READ_ONLY_PREFLIGHT",
        "calibration_policy_changed": False,
    }
    return cfg


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _as_int(value: Any) -> int:
    return int(round(float(value)))


def _call(fn, label: str, cfg: Mapping[str, Any]):
    return com.com_call_with_retry(
        fn, label=label, retry_policy=(cfg.get("com_resilience", {}) or {}))


def _att(obj: Any, name: str) -> Any:
    return obj.AttValue(name)


def _exact_link(visum: Any, *, link_no: int | None, from_no: int, to_no: int,
                cfg: Mapping[str, Any]) -> tuple[Any, dict[str, int]]:
    link = _call(lambda: visum.Net.Links.ItemByKey(int(from_no), int(to_no)),
                 f"Links.ItemByKey({from_no},{to_no})", cfg)
    got = {
        "link_no": _as_int(_att(link, "NO")),
        "from_node_no": _as_int(_att(link, "FROMNODENO")),
        "to_node_no": _as_int(_att(link, "TONODENO")),
    }
    if got["from_node_no"] != int(from_no) or got["to_node_no"] != int(to_no):
        raise RuntimeError("V24916_PREFLIGHT_LINK_DIRECTION_READBACK_MISMATCH")
    if link_no is not None and got["link_no"] != int(link_no):
        raise RuntimeError(
            f"V24916_PREFLIGHT_LINK_NO_READBACK_MISMATCH:{got['link_no']}!={link_no}")
    return link, got


def _read_flowbundle_matrix(visum: Any, link: Any, dseg_obj: Any,
                            dseg_code: str, cfg: Mapping[str, Any]) -> Any:
    fb = visum.Net.FlowBundle
    _call(lambda: fb.Clear(), "FlowBundle.Clear[pre]", cfg)
    try:
        _call(lambda: setattr(fb, "DemandSegments", str(dseg_code)),
              f"FlowBundle.DemandSegments[{dseg_code}]", cfg)
        _call(lambda: fb.CreateCondition(link, None, False, False, 0, 0),
              "FlowBundle.CreateCondition[sealed]", cfg)
        _call(lambda: fb.ExecuteCurrentConditions(),
              "FlowBundle.ExecuteCurrentConditions[sealed]", cfg)
        matrix = _call(lambda: fb.GetOrCreateFlowBundleMatrix(dseg_obj),
                       f"FlowBundle.GetOrCreateFlowBundleMatrix[{dseg_code}]", cfg)
        return _call(lambda: matrix.GetValues(),
                     f"FlowBundleMatrix.GetValues[{dseg_code}]", cfg)
    finally:
        try:
            _call(lambda: fb.Clear(), "FlowBundle.Clear[post]", cfg)
        except Exception:
            pass


def _minimal_matrix_inventory(visum: Any, cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    matrices = visum.Net.Matrices
    policy = cfg.get("com_resilience", {}) or {}
    no_rows = com.get_multi_att_values(matrices, "NO", policy)
    code_rows = com.get_multi_att_values(matrices, "CODE", policy)
    def plain(rows):
        return [r[1] if isinstance(r, (tuple, list)) and len(r) >= 2 else r for r in (rows or [])]
    nos, codes = plain(no_rows), plain(code_rows)
    out=[]
    for i, raw_no in enumerate(nos):
        try: no=int(round(float(raw_no)))
        except Exception: continue
        code=str(codes[i] if i < len(codes) else "").strip().upper()
        out.append({"matrix_no_int":no,"matrix_code_norm":code})
    return out


def _matrix_meta_exact(visum: Any, cfg: Mapping[str, Any]) -> tuple[dict[str, Any], Any]:
    inventory = _minimal_matrix_inventory(visum, cfg)
    exact = []
    for code in EXACT_DISTANCE_CODES:
        exact = [row for row in inventory if row.get("matrix_code_norm") == code]
        if exact:
            break
    if len(exact) != 1:
        candidates = [r for r in inventory
                      if any(token in str(r.get("matrix_code_norm", ""))
                             for token in ("DIST", "DIS"))]
        raise RuntimeError(
            "V24916_DIST_KM_EXACT_IDENTITY_NOT_UNIQUE:" +
            json.dumps(candidates[:20], ensure_ascii=False, default=str))
    row = exact[0]
    no = int(row["matrix_no_int"])
    matrix = _call(lambda: visum.Net.Matrices.ItemByKey(no),
                   f"Matrices.ItemByKey({no})", cfg)
    return row, matrix


def _dseg_role_authority(visum: Any, required_native: Sequence[str],
                         cfg: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    found = discover_dsegs(visum, list(required_native), ())
    by_code = {str(row["canonical_code"]): row for row in found}
    missing = [str(code) for code in required_native if str(code).upper() not in by_code]
    # canonical_dseg in this model normalizes to upper-case codes; keep exact
    # requested spellings in the public authority but verify by normalized key.
    if missing:
        # Retry via normalized comparison for mixed-case donor codes.
        upper = {str(k).upper(): v for k, v in by_code.items()}
        missing = [str(code) for code in required_native if str(code).upper() not in upper]
        by_code = upper
    if missing:
        raise RuntimeError("V24916_REQUIRED_NATIVE_DSEG_MISSING:" + ",".join(missing))
    roles = {str(code): "TARGET_NATIVE" for code in required_native}
    payload = {
        "schema": "R1_15A2_V24916_FRESH_DSEG_ROLE_AUTHORITY_V1",
        "roles": roles,
        "required_native_dsegs": list(required_native),
    }
    payload["authority_hash"] = _canonical_hash(payload)
    return roles, payload


def _native_objects(visum: Any, required_native: Sequence[str]) -> list[dict[str, Any]]:
    rows = discover_dsegs(visum, list(required_native), ())
    return [row for row in rows if row.get("role") == "TARGET_NATIVE"]


PROFILE488_CSD_REL = "authorities/R1_CSD2022_COUNTLOCATION_AUTHORITY_CURRENT_362_20261022.csv"
PROFILE488_CITY_REL = "authorities/R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_CURRENT_126_20261022.csv"
PROFILE488_XLSX_REL = "authorities/COUNTLOCATION-2026-10-22-02-23-34.xlsx"
PROFILE488_CSD_SHA256 = "86319e09010e2c4c261437a805541f9ff45b6bd0a3fe48d0757123f595c112ba"
PROFILE488_CITY_SHA256 = "2154cfd4fb080f63ec3f6e233d27bb8d7787a0598febf38c14e7851f3f66a7e0"
PROFILE488_XLSX_SHA256 = "0244e311488e88f754a691e8c1d535608a13360e91086ee116d6d9e71bf7f860"

def _sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def _profile488_authority(root: Path) -> dict[str, Any]:
    csd_path=root/PROFILE488_CSD_REL
    city_path=root/PROFILE488_CITY_REL
    xlsx_path=root/PROFILE488_XLSX_REL
    required=((csd_path,PROFILE488_CSD_SHA256),(city_path,PROFILE488_CITY_SHA256),(xlsx_path,PROFILE488_XLSX_SHA256))
    for path,expected in required:
        if not path.is_file() or _sha256_file(path)!=expected:
            raise RuntimeError("V24916_PROFILE488_AUTHORITY_HASH_MISMATCH:"+str(path))
    csd=_read_csv(csd_path); city=_read_csv(city_path)
    if len(csd)!=362 or len(city)!=126:
        raise RuntimeError(f"V24916_PROFILE488_AUTHORITY_ROW_COUNT:{len(csd)}+{len(city)}")
    if any(str(r.get("role","")).upper()!="CALIBRATION" for r in csd+city):
        raise RuntimeError("V24916_PROFILE488_NONCALIBRATION_ROW")
    return {
        "rows":488,"calibration":488,"validation":0,
        "csd_rows":362,"city_rows":126,
        "source_xlsx":PROFILE488_XLSX_REL,"source_xlsx_sha256":PROFILE488_XLSX_SHA256,
        "csd_csv":PROFILE488_CSD_REL,"csd_sha256":PROFILE488_CSD_SHA256,
        "city_csv":PROFILE488_CITY_REL,"city_sha256":PROFILE488_CITY_SHA256,
        "zero_observation_rows":sum(1 for r in csd+city if float(r.get("observed_passenger_cars_O") or 0.0)<=0.0),
    }

def _live_profile488_compatibility(visum: Any, root: Path, cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only proof that the opened model can host the sealed PROFILE488 authority.

    R1_ACTIVE/R1_ROLE are intentionally not required on the source model because
    the parent fresh launcher writes them only on its isolated working copy.
    Identity, observation and edge geometry must already match the authority.
    """
    _profile488_authority(root)
    rows = _read_csv(root / PROFILE488_CSD_REL) + _read_csv(root / PROFILE488_CITY_REL)
    coll = visum.Net.CountLocations
    checked = []
    errors = []
    for row in rows:
        no = _as_int(row["countlocation_no"])
        try:
            obj = _call(lambda no=no: coll.ItemByKey(no), f"CountLocations.ItemByKey({no})", cfg)
            got_no = _as_int(_att(obj, "NO"))
            observed = float(_att(obj, "R1_OBS_RPDI"))
            expected_observed = float(row.get("observed_passenger_cars_O") or 0.0)
            edge = tuple(_as_int(_att(obj, a)) for a in ("LINKNO", "FROMNODENO", "TONODENO"))
            expected_edge = tuple(_as_int(row[k]) for k in (
                "current_link_no", "current_from_node_no", "current_to_node_no"))
            if got_no != no:
                raise RuntimeError(f"NO_READBACK:{got_no}!={no}")
            if abs(observed - expected_observed) > 1.0e-6:
                raise RuntimeError(f"OBS:{observed}!={expected_observed}")
            if edge != expected_edge:
                raise RuntimeError(f"EDGE:{edge}!={expected_edge}")
            checked.append(no)
        except Exception as exc:
            errors.append({
                "countlocation_no": no,
                "profile_id": row.get("profile_id"),
                "error": type(exc).__name__ + ":" + str(exc),
            })
    if errors:
        preview = ";".join(
            f"{e['countlocation_no']}:{e['error']}" for e in errors[:12])
        raise RuntimeError(
            f"V24916_PROFILE488_LIVE_MODEL_INCOMPATIBLE:{len(errors)}:" + preview)
    if len(checked) != 488 or len(set(checked)) != 488:
        raise RuntimeError("V24916_PROFILE488_LIVE_MODEL_COUNT_MISMATCH")
    return {
        "schema": "R1_15A2_V24916_PROFILE488_LIVE_COMPATIBILITY_V1",
        "passes": True,
        "checked_rows": len(checked),
        "calibration_rows": 488,
        "validation_rows": 0,
        "source_model_mutated": False,
        "R1_ACTIVE_R1_ROLE_required_on_source": False,
        "R1_ACTIVE_R1_ROLE_written_only_to_working_copy": True,
    }


def _profile_samples(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    _profile488_authority(root)
    csd = _read_csv(root / PROFILE488_CSD_REL)
    city = _read_csv(root / PROFILE488_CITY_REL)
    directed = [r for r in csd
                if str(r.get("role", "")).upper() == "CALIBRATION"
                and str(r.get("observation_direction", "DIRECTIONAL")).upper() == "DIRECTIONAL"]
    both = [r for r in city
            if str(r.get("role", "")).upper() == "CALIBRATION"
            and str(r.get("observation_direction", "")).upper() == "BOTH"]
    if not directed or not both:
        raise RuntimeError("V24916_PROFILE488_SAMPLE_SCOPE_EMPTY")
    return directed[:8], both[:4]


def _directed_live_sample(visum: Any, cfg: Mapping[str, Any], root: Path,
                          zones: Sequence[int], dsegs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    directed_profiles, _ = _profile_samples(root)
    reducer = FlowBundleMatrixReducer(zones, top_k=128)
    attempts = []
    for profile in directed_profiles:
        link_no = _as_int(profile["current_link_no"])
        fr = _as_int(profile["current_from_node_no"])
        to = _as_int(profile["current_to_node_no"])
        try:
            link, link_ev = _exact_link(
                visum, link_no=link_no, from_no=fr, to_no=to, cfg=cfg)
        except Exception as exc:
            attempts.append({"profile_id": profile.get("profile_id"), "status": "LINK_FAIL",
                             "error": type(exc).__name__ + ":" + str(exc)})
            continue
        for dseg in dsegs[:4]:
            code = str(dseg["code"])
            try:
                raw = _read_flowbundle_matrix(visum, link, dseg["object"], code, cfg)
                reduced = reducer.reduce(raw, source_directions=("DIRECTED",))
                raw = None
                row = {
                    "profile_id": profile.get("profile_id"),
                    "countlocation_no": profile.get("countlocation_no"),
                    "dseg_code": code,
                    "link": link_ev,
                    "n_zones": reduced.n_zones,
                    "total": reduced.total,
                    "retained_total": reduced.retained_total,
                    "tail_total": reduced.tail_total,
                    "payload_hash": reduced.payload_hash,
                    "positive": reduced.total > 0.0,
                    "status": "PASS" if reduced.total > 0.0 else "ZERO_FLOW",
                }
                attempts.append(row)
                if reduced.total > 0.0:
                    return {"passes": True, "selected": row, "attempts": attempts}
            except Exception as exc:
                attempts.append({"profile_id": profile.get("profile_id"), "dseg_code": code,
                                 "status": "FLOWBUNDLE_FAIL",
                                 "error": type(exc).__name__ + ":" + str(exc)})
    return {"passes": False, "selected": None, "attempts": attempts,
            "error": "NO_POSITIVE_NATIVE_DIRECTED_FLOWBUNDLE_SAMPLE"}


def _both_live_sample(visum: Any, cfg: Mapping[str, Any], root: Path,
                      zones: Sequence[int], dsegs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    _, both_profiles = _profile_samples(root)
    if not both_profiles:
        return {"passes": True, "status": "NOT_APPLICABLE_NO_ACTIVE_BOTH_PROFILE"}
    if not dsegs:
        return {"passes": False, "status": "NO_NATIVE_DSEG"}
    reducer = FlowBundleMatrixReducer(zones, top_k=64)
    attempts = []
    dseg = dsegs[0]
    code = str(dseg["code"])
    for profile in both_profiles:
        link_no = _as_int(profile["current_link_no"])
        fr = _as_int(profile["current_from_node_no"])
        to = _as_int(profile["current_to_node_no"])
        try:
            fwd, fwd_ev = _exact_link(visum, link_no=link_no, from_no=fr, to_no=to, cfg=cfg)
            rev, rev_ev = _exact_link(visum, link_no=None, from_no=to, to_no=fr, cfg=cfg)
            raw_f = _read_flowbundle_matrix(visum, fwd, dseg["object"], code, cfg)
            raw_r = _read_flowbundle_matrix(visum, rev, dseg["object"], code, cfg)
            reduced = reducer.reduce(raw_f, raw_r, source_directions=("FORWARD", "REVERSE"))
            raw_f = raw_r = None
            row = {
                "profile_id": profile.get("profile_id"),
                "countlocation_no": profile.get("countlocation_no"),
                "dseg_code": code,
                "forward_link": fwd_ev,
                "reverse_link": rev_ev,
                "n_zones": reduced.n_zones,
                "total": reduced.total,
                "retained_total": reduced.retained_total,
                "tail_total": reduced.tail_total,
                "payload_hash": reduced.payload_hash,
                "status": "PASS",
            }
            attempts.append(row)
            return {"passes": True, "status": "PASS", "selected": row,
                    "attempts": attempts}
        except Exception as exc:
            attempts.append({"profile_id": profile.get("profile_id"), "status": "FAIL",
                             "error": type(exc).__name__ + ":" + str(exc)})
    return {"passes": False, "status": "NO_BOTH_SAMPLE_PASSED", "attempts": attempts}


def build_live_authority(visum: Any, base_cfg: Mapping[str, Any], root: Path) -> dict[str, Any]:
    root = Path(root)
    cfg = _preflight_adapter_cfg(base_cfg)
    source_ver = Path(str(visum.IO.CurrentVersionFile))
    if not source_ver.is_file():
        raise RuntimeError("V24916_CURRENT_VERSION_FILE_NOT_FOUND")
    source_sha = rt.sha256_file(source_ver)

    # Snapshot before any FlowBundle analysis. No candidate/readback context is active.
    adapter = VisumAdapter(visum, cfg, None)
    skim_positions, skim_group_positions = active_native_skim_positions(visum)
    native_dis_rows = _native_dis_rows(adapter)
    dynamic_skim_structure = {
        "schema": "R1_15A2_V24916_DYNAMIC_SKIM_STRUCTURE_AUTHORITY_V1",
        "active_prt_skim_operation_positions": list(skim_positions),
        "active_prt_skim_operation_count": len(skim_positions),
        "required_native_dsegs": list(REQUIRED_NATIVE_DSEGS),
        "dis_matrices": {
            code: {
                "matrix_no": int(native_dis_rows[code]["matrix_no_int"]),
                "matrix_code": str(native_dis_rows[code].get("matrix_code", "DIS")),
                "dseg_code": str(native_dis_rows[code].get("dseg_code", code)),
            } for code in REQUIRED_NATIVE_DSEGS
        },
        "distance_semantics": "ASSIGNMENT_PATH_DISTANCE_KM",
        "required_path_aggregation": "MEAN_OVER_PATH_VOLUME",
        "refresh_policy": "EVERY_TD_FINECDF_EVALUATION_AND_EVERY_FRESH_ASSIGNMENT",
        "static_r1_osrm_dist_km_role": "REFERENCE_ONLY_NOT_ACTIVE_CALIBRATION",
        "procedure_sequence_executed_by_preflight": False,
        "configuration_readback_note": (
            "Operation count and exact resulting DIS DSeg matrix identities are sealed here; "
            "each live calibration refresh revalidates all six result matrices and assignment epoch."
        ),
    }
    dynamic_skim_structure["authority_hash"] = _canonical_hash(dynamic_skim_structure)
    before = adapter.snapshot()
    before_semantic = restart.build_authority(
        before, version_path=source_ver, raw_ver_sha256=source_sha,
        origin="V24916_FRESH_BASELINE_LIVE_PREFLIGHT_BEFORE")
    perf2c_parity = dict(getattr(adapter, "last_perf2c_snapshot_parity", {}) or {})
    if perf2c_parity.get("status") not in {"EXACT_PARITY_PASS", "NOT_RUN"}:
        raise RuntimeError("V24916_PARENT_PERF2C_SNAPSHOT_PARITY_NOT_CERTIFIED:" +
                           str(perf2c_parity.get("status")))

    profile488_live = _live_profile488_compatibility(visum, root, cfg)
    zones = zone_numbers(visum, cfg.get("com_resilience", {}) or {})
    zone_hash = ordered_zone_hash(zones)
    inv_before = _minimal_matrix_inventory(visum, cfg)
    inv_key_before = [(r.get("matrix_no_int"), r.get("matrix_code_norm"))
                      for r in inv_before]

    dist_row, dist_matrix = _matrix_meta_exact(visum, cfg)
    dist_values = _call(lambda: dist_matrix.GetValues(),
                        f"Matrix.GetValues[DIST_KM:{dist_row['matrix_no_int']}]", cfg)
    dist_identity = seal_dist_km(
        matrix_no=int(dist_row["matrix_no_int"]),
        matrix_code=str(dist_row["matrix_code_norm"]),
        unit="km", values=dist_values, zone_nos=zones,
        exact_expected_code=str(dist_row["matrix_code_norm"]),
    )
    dist_values = None

    required_native = [str(v) for v in cfg.get("path_export_dsegs", [])]
    roles, role_authority = _dseg_role_authority(visum, required_native, cfg)
    dsegs = _native_objects(visum, required_native)
    if len(dsegs) != len(required_native):
        raise RuntimeError("V24916_NATIVE_DSEG_OBJECT_COUNT_MISMATCH")

    contract = FlowBundleContract()
    fb_contract_hash = contract_hash(contract)
    directed = _directed_live_sample(visum, cfg, root, zones, dsegs)
    if not directed.get("passes"):
        raise RuntimeError("V24916_DIRECTED_FLOWBUNDLE_PREFLIGHT_FAILED")
    both = _both_live_sample(visum, cfg, root, zones, dsegs)
    if not both.get("passes"):
        raise RuntimeError("V24916_BOTH_FLOWBUNDLE_PREFLIGHT_FAILED")

    inv_after = _minimal_matrix_inventory(visum, cfg)
    inv_key_after = [(r.get("matrix_no_int"), r.get("matrix_code_norm"))
                     for r in inv_after]
    # FlowBundle helper objects are allowed internally, but the persistent Net.Matrices
    # inventory must not change on the opened source model.
    if inv_key_after != inv_key_before:
        raise RuntimeError("V24916_PREFLIGHT_PERSISTENT_MATRIX_INVENTORY_CHANGED")

    after = adapter.snapshot()
    after_semantic = restart.build_authority(
        after, version_path=source_ver, raw_ver_sha256=source_sha,
        origin="V24916_FRESH_BASELINE_LIVE_PREFLIGHT_AFTER")
    semantic_check = restart.require_authority_match(
        before_semantic, after_semantic, label="V24916_PREFLIGHT_SEMANTIC_NO_CHANGE")

    report = {
        "schema": SCHEMA,
        "passes": True,
        "release": RELEASE,
        "activation_stage": "P1A_LIVE_IO_PREFLIGHT_CERTIFIED_ACTUATORS_OFF",
        "current_version_file": str(source_ver),
        "source_raw_ver_sha256_provenance_only": source_sha,
        "source_semantic_state_hash": before_semantic["semantic_state_hash"],
        "source_semantic_hashes": dict(before_semantic["semantic_hashes"]),
        "semantic_before_after": semantic_check,
        "perf2c_single_pass_parity": perf2c_parity,
        "zone_order": {
            "count": len(zones), "sha256": zone_hash,
            "first": zones[:5], "last": zones[-5:],
        },
        "dist_km": dict(dist_identity.as_dict(),
                        role="REFERENCE_ONLY_NOT_ACTIVE_CALIBRATION"),
        "dynamic_assignment_skims": dynamic_skim_structure,
        "dseg_role_authority": role_authority,
        "flowbundle_contract": contract.as_dict(),
        "flowbundle_contract_sha256": fb_contract_hash,
        "directed_sample": directed,
        "both_sample": both,
        "matrix_inventory_unchanged": True,
        "parent_acceptance_authority_changed": False,
        "assignment_executed": False,
        "procedure_sequence_executed": False,
        "coefficient_writes": 0,
        "direct_od_writes": 0,
        "preflight_path_cache_policy": dict(cfg.get("v24916_preflight_path_cache_policy", {})),
        "active_v24916_actuators": [],
        "countlocation_authority": _profile488_authority(root),
        "countlocation_live_compatibility": profile488_live,
        "fresh100_parent_contract": {
            "profile_rows": 488,
            "calibration_rows": 488,
            "validation_rows": 0,
            "outer_cycle_cap": 100,
            "wall_clock_limit_disabled": True,
            "cross_run_path_cache_restore": False,
        },
        "fresh_lineage": {
            "accepted_count_start": 0,
            "outer_cycle_start": 1,
            "historical_checkpoint_inherited": False,
            "historical_path_cache_restore_allowed": False,
            "fresh_path_epoch_required": True,
        },
    }
    report["authority_hash"] = _canonical_hash(report)
    return report


def require_live_authority_current(visum: Any, base_cfg: Mapping[str, Any], root: Path,
                                   authority: Mapping[str, Any]) -> dict[str, Any]:
    """Cheap fail-closed revalidation immediately before calibration start."""
    if authority.get("passes") is not True or authority.get("schema") != SCHEMA:
        raise RuntimeError("V24916_FRESH_BASELINE_LIVE_AUTHORITY_NOT_PASSED")
    root = Path(root)
    cfg = _preflight_adapter_cfg(base_cfg)
    source_ver = Path(str(visum.IO.CurrentVersionFile))
    if not source_ver.is_file():
        raise RuntimeError("V24916_CURRENT_VERSION_FILE_NOT_FOUND")
    adapter = VisumAdapter(visum, cfg, None)
    snap = adapter.snapshot()
    current = restart.build_authority(
        snap, version_path=source_ver, raw_ver_sha256=rt.sha256_file(source_ver),
        origin="V24916_FRESH_BASELINE_PRE_CALIBRATION_REVALIDATION")
    if current.get("semantic_state_hash") != authority.get("source_semantic_state_hash"):
        raise RuntimeError("V24916_FRESH_BASELINE_MODEL_CHANGED_SINCE_PREFLIGHT")
    zones = zone_numbers(visum, cfg.get("com_resilience", {}) or {})
    if ordered_zone_hash(zones) != (authority.get("zone_order") or {}).get("sha256"):
        raise RuntimeError("V24916_FRESH_BASELINE_ZONE_ORDER_CHANGED_SINCE_PREFLIGHT")
    skim_positions, _skim_groups = active_native_skim_positions(visum)
    native_dis_rows = _native_dis_rows(adapter)
    expected_dynamic = authority.get("dynamic_assignment_skims") or {}
    if list(skim_positions) != list(expected_dynamic.get("active_prt_skim_operation_positions") or []):
        raise RuntimeError("V24916_DYNAMIC_SKIM_OPERATION_SET_CHANGED_SINCE_PREFLIGHT")
    current_native_dis = {
        code: int(native_dis_rows[code]["matrix_no_int"]) for code in REQUIRED_NATIVE_DSEGS
    }
    expected_native_dis = {
        code: int((expected_dynamic.get("dis_matrices") or {}).get(code, {}).get("matrix_no", -1))
        for code in REQUIRED_NATIVE_DSEGS
    }
    if current_native_dis != expected_native_dis:
        raise RuntimeError("V24916_DYNAMIC_SKIM_MATRIX_BINDING_CHANGED_SINCE_PREFLIGHT")
    dist_row, matrix = _matrix_meta_exact(visum, cfg)
    values = _call(lambda: matrix.GetValues(),
                   f"Matrix.GetValues[DIST_KM:{dist_row['matrix_no_int']}]", cfg)
    ident = seal_dist_km(
        matrix_no=int(dist_row["matrix_no_int"]),
        matrix_code=str(dist_row["matrix_code_norm"]), unit="km",
        values=values, zone_nos=zones,
        exact_expected_code=str(dist_row["matrix_code_norm"]),
    )
    if ident.identity_hash != (authority.get("dist_km") or {}).get("identity_hash"):
        raise RuntimeError("V24916_FRESH_BASELINE_DIST_KM_CHANGED_SINCE_PREFLIGHT")
    return {
        "schema": "R1_15A2_V24916_FRESH_EE_BASELINE_REVALIDATION_V1",
        "passes": True,
        "semantic_state_hash": current["semantic_state_hash"],
        "zone_order_sha256": ordered_zone_hash(zones),
        "dist_km_identity_hash": ident.identity_hash,
        "dist_km_role": "REFERENCE_ONLY_NOT_ACTIVE_CALIBRATION",
        "dynamic_assignment_skim_operation_positions": list(skim_positions),
        "dynamic_assignment_skim_matrix_nos": current_native_dis,
        "authority_hash": authority.get("authority_hash"),
    }


def write_live_authority(path: Path, report: Mapping[str, Any]) -> None:
    runtime_io_hotfix.critical_atomic_json(path, report)


__all__ = [
    "SCHEMA", "EXACT_DISTANCE_CODES", "build_live_authority",
    "require_live_authority_current", "write_live_authority",
]
