# -*- coding: utf-8 -*-
"""R1 STEP 15A2 V2.1 audited -- actual-path, multi-block generative calibration.

V2 extends V1 with identifiable calibration of:

* ADD_PROD_W / ADD_ATT_W / ADD_PROD_S / ADD_ATT_S,
* ADD_SALARY through a regularised income basis,
* ZAHR_PROD_WORK / ZAHR_ATR_WORK / ZAHR_PROD_SERV / ZAHR_ATR_SERV,
* component-specific Trip Distribution b/c for WORK, SERVICE, SCHOOL and LONG.

No OD matrix is ever written directly.  Generation candidates pass through the
live Trip Generation -> Trip Distribution -> realization -> assignment sequence.
Trip Distribution b/c candidates are evaluated in separate blocks.  Every block
has its own PRE checkpoint, backtracking line-search, fresh 12D/11D evaluation,
and exact rollback on rejection.  VALIDATION observations remain report-only.

Default is design-only.  Run manually inside PTV Visum with the accepted clean
pre-cluster .ver open.  Do not place this script inside Procedure Sequence.
"""
from __future__ import print_function

import gc
import hashlib
import json
import math
import os
import shutil
import sys
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

try:
    import numpy as np
except Exception:
    np = None

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(HERE))

import r1_15a2_core as core
import r1_15a2_multiblock as mb
import r1_15a2_runtime_v1 as rt
import r1_15a2_visum_parameters as vp

SCRIPT_ID = "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1"
CONFIG_NAME = "R1_15A2_CONFIG_V2_1.json"
OUT_ROOT = "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_V2_1"
EXPECTED_ZONES = 681


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    with Path(path).open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, obj):
    rt.write_json(path, obj)


def write_csv(path, rows, fields=None):
    rt.write_csv(path, rows, fields)


def compact_error(exc, limit=1200):
    return rt.compact_error(exc, limit)


def log(out_dir, message):
    rt.log_line(out_dir, message)


def env_bool(name, default=False):
    return rt.env_bool(name, default)


def env_int(name, default):
    return rt.env_int(name, default)




def connect_visum():
    """Bind Visum's injected script global into the imported runtime module.

    PTV Visum executes scripts with a module-local ``Visum`` object. Imported
    Python modules do not automatically see that global, so relying only on
    GetActiveObject breaks installations without pywin32 registration.
    """
    injected = globals().get("Visum")
    if injected is None:
        injected = globals().get("COM")
    if injected is not None:
        rt.Visum = injected
        return injected, "master injected Visum/COM global"
    return rt.get_visum()

def load_config():
    path = HERE / CONFIG_NAME
    if not path.is_file():
        raise RuntimeError("Missing configuration: %s" % path)
    cfg = read_json(path)
    cfg["apply"] = env_bool("R1_15A2_V21_APPLY", cfg.get("apply", False))
    cfg["run_procseq"] = env_bool("R1_15A2_V21_RUN_PROCSEQ", cfg.get("run_procseq", True))
    cfg["max_cycles"] = env_int("R1_15A2_V21_MAX_CYCLES", cfg.get("max_cycles", 2))
    cfg["max_accepted_blocks"] = env_int("R1_15A2_V21_MAX_ACCEPTED_BLOCKS", cfg.get("max_accepted_blocks", 1))
    dep_path = HERE / cfg.get("tg_dependency_contract_file", "authorities/R1_TG_PARAMETER_DEPENDENCY_CONTRACT_V2_1.json")
    if not dep_path.is_file():
        raise RuntimeError("TG dependency contract missing: %s" % dep_path)
    cfg["tg_dependency_contract"] = read_json(dep_path)
    cfg["tg_dependency_contract_path"] = str(dep_path)
    cfg["tg_dependency_contract_sha256"] = sha256_file(dep_path)
    long_path = HERE / cfg.get("td", {}).get("long_authority_file", "authorities/R1_LONG_AUTHORITY_CONTRACT_V2_1.json")
    if not long_path.is_file():
        raise RuntimeError("LONG authority missing: %s" % long_path)
    cfg["long_authority"] = read_json(long_path)
    cfg["long_authority_path"] = str(long_path)
    cfg["long_authority_sha256"] = sha256_file(long_path)
    cfg["config_path"] = str(path)
    cfg["config_sha256"] = sha256_file(path)
    return cfg


def zip_evidence(folder, target):
    folder = Path(folder); target = Path(target)
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(str(target), "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file() and p.suffix.lower() not in (".ver", ".verx"):
                zf.write(str(p), str(p.relative_to(folder)))


def zone_state_rows(visum, zones, cfg, zone_indices=None, retry_policy=None):
    required = list(cfg.get("tg_dependency_contract", {}).get("required_zone_attributes", []))
    required.extend(mb.GENERATION_ATTRS)
    required.extend([
        cfg.get("salary", {}).get("income_attr", "AV_INCOME"),
        cfg.get("zahr", {}).get("domestic_mask_attr", "NOT_ZAHR"),
    ])
    attrs = []
    seen = set()
    for name in required:
        name = mb.sval(name).strip()
        if name and name not in seen:
            seen.add(name); attrs.append(name)
    values = {}
    errors = []
    for name in attrs:
        try:
            values[name] = rt.read_zone_attr_strict(
                visum, name, zones, zone_indices=zone_indices, retry_policy=retry_policy)
        except Exception as exc:
            errors.append({"attr": name, "error": compact_error(exc)})
    if errors:
        raise RuntimeError("Required generation zone attributes are unreadable: %s" % errors)
    rows = []
    for i, z in enumerate(zones):
        row = {"zone_no": int(z)}
        for name in attrs:
            row[name] = float(values[name][i])
        rows.append(row)
    return rows, attrs


def generation_actuator_zone_scope(visum, zones, cfg, out_dir, zone_indices=None, retry_policy=None):
    """Resolve zones for which the current TG formulas expose a real actuator.

    Domestic zones use ADD_*; ZAHR zones require both ZAHR_SUSED and POP_ZP to
    be positive.  Explicit exclusions apply to both branches.  This scope is fed
    into the path-incidence variable builder so excluded endpoints cannot create
    unimplementable OD guidance.
    """
    zrows, _attrs = zone_state_rows(
        visum, zones, cfg, zone_indices=zone_indices, retry_policy=retry_policy)
    zcfg = cfg.get("zahr", {})
    mask_attr = mb.sval(zcfg.get("domestic_mask_attr", "NOT_ZAHR"))
    neighbour_attr = mb.sval(zcfg.get("neighbour_attr", "ZAHR_SUSED"))
    population_attr = mb.sval(zcfg.get("population_attr", "POP_ZP"))
    threshold = float(zcfg.get("domestic_threshold", 0.5))
    excluded = set(int(x) for x in cfg.get("explicit_excluded_zone_nos", []) or [])
    excluded.update(int(x) for x in zcfg.get("explicit_excluded_zone_nos", []) or [])
    eligible = []
    rows = []
    for row in zrows:
        z = int(row["zone_no"])
        domestic = float(mb.fval(row.get(mask_attr), 0.0) or 0.0) >= threshold
        if z in excluded:
            active = False; reason = "EXPLICIT_EXCLUSION"
        elif domestic:
            active = True; reason = "DOMESTIC_ADD_BRANCH"
        else:
            neigh = float(mb.fval(row.get(neighbour_attr), 0.0) or 0.0)
            pop = float(mb.fval(row.get(population_attr), 0.0) or 0.0)
            active = neigh > 0.0 and pop > 0.0
            reason = "ZAHR_BRANCH_ACTIVE" if active else "ZAHR_FORMULA_BASE_INACTIVE"
        if active:
            eligible.append(z)
        rows.append({"zone_no": z, "domestic_branch": int(domestic), "generation_actuatable": int(active), "reason": reason})
    write_csv(Path(out_dir) / "00_ZONE_ACTUATOR_SCOPE.csv", rows)
    summary = {"zone_count": len(rows), "eligible_zone_count": len(eligible), "excluded_zone_count": len(rows)-len(eligible), "passes": bool(eligible)}
    write_json(Path(out_dir) / "00_ZONE_ACTUATOR_SCOPE_SUMMARY.json", summary)
    if not eligible:
        raise RuntimeError("No generation-actuatable zones resolved")
    return eligible, summary


def block_matrix_scope(cfg, block):
    scope = (cfg.get("matrix_scope_by_block", {}) or {}).get(block, {}) or {}
    return list(scope.get("dseg_codes", []) or []), list(scope.get("matrix_nos", []) or [])


def block_matrix_fingerprints(visum, cfg, block):
    dsegs, matrix_nos = block_matrix_scope(cfg, block)
    return rt.matrix_fingerprints_for_scope(visum, dseg_codes=dsegs, matrix_nos=matrix_nos)


def td_snapshot(visum):
    state = vp.read_td_parameter_state(visum)
    return [{"component": r.get("component"), "current_b": r.get("current_b"), "current_c": r.get("current_c"), "status": r.get("status")} for r in state.get("rows", [])]


def compare_td_snapshot(before, after, tol=1.0e-10):
    bmap = {mb.sval(r.get("component")): r for r in before}
    amap = {mb.sval(r.get("component")): r for r in after}
    rows = []
    for comp in sorted(set(bmap) | set(amap)):
        b = bmap.get(comp, {}); a = amap.get(comp, {})
        bb = mb.fval(b.get("current_b"), None); ab = mb.fval(a.get("current_b"), None)
        bc = mb.fval(b.get("current_c"), None); ac = mb.fval(a.get("current_c"), None)
        same = bb is not None and ab is not None and bc is not None and ac is not None and abs(bb-ab) <= tol and abs(bc-ac) <= tol
        rows.append({"component": comp, "before_b": bb, "after_b": ab, "before_c": bc, "after_c": ac, "same": int(same)})
    return rows


def capture_pre_state(visum, zones, cfg, block):
    return {
        "matrix": block_matrix_fingerprints(visum, cfg, block),
        "zone": rt.zone_parameter_snapshot(visum, zones, mb.GENERATION_ATTRS),
        "td": td_snapshot(visum),
    }


def verify_loaded_checkpoint_state(visum, zones, cfg, block, pre_state, out_dir):
    out_dir = Path(out_dir)
    matrix_after = block_matrix_fingerprints(visum, cfg, block)
    matrix_cmp = rt.compare_explicit_matrix_fingerprints(pre_state["matrix"], matrix_after)
    zone_after = rt.zone_parameter_snapshot(visum, zones, mb.GENERATION_ATTRS)
    zone_cmp = rt.compare_parameter_snapshots(pre_state["zone"], zone_after)
    td_after = td_snapshot(visum)
    td_cmp = compare_td_snapshot(pre_state["td"], td_after)
    write_csv(out_dir / "98_ROLLBACK_MATRIX_VERIFY.csv", matrix_cmp)
    write_csv(out_dir / "98B_ROLLBACK_ZONE_VERIFY.csv", zone_cmp)
    write_csv(out_dir / "98C_ROLLBACK_TD_VERIFY.csv", td_cmp)
    passes = all(int(r.get("changed", 1)) == 0 and int(r.get("comparable", 0)) == 1 for r in matrix_cmp)
    passes = passes and all(int(r.get("same", 0)) == 1 for r in zone_cmp)
    passes = passes and all(int(r.get("same", 0)) == 1 for r in td_cmp)
    result = {"passes": passes, "matrix_rows": len(matrix_cmp), "zone_rows": len(zone_cmp), "td_rows": len(td_cmp)}
    write_json(out_dir / "98D_ROLLBACK_VERIFY_SUMMARY.json", result)
    if cfg.get("require_rollback_verification", True) and not passes:
        raise RuntimeError("Exact rollback verification failed")
    return result


def load_11d_sources(result):
    summary_path = Path(result["summary_path"])
    workspace = summary_path.parent
    summary_csv = rt.find_file_recursive(workspace, rt.D11_PREFIX + "component_model_dist_vs_idp_summary.csv")
    compare_csv = rt.find_file_recursive(workspace, rt.D11_PREFIX + "component_model_dist_vs_idp.csv")
    baseline_csv = rt.find_file_recursive(workspace, rt.D11_PREFIX + "component_model_dist_baseline.csv")
    if not summary_csv or not compare_csv or not baseline_csv:
        raise RuntimeError("11D component files incomplete under %s" % workspace)
    return {
        "workspace": str(workspace),
        "summary_rows": rt.read_csv_auto(summary_csv),
        "compare_rows": rt.read_csv_auto(compare_csv),
        "baseline_rows": rt.read_csv_auto(baseline_csv),
        "paths": {
            "summary": str(summary_csv), "compare": str(compare_csv), "baseline": str(baseline_csv),
        },
    }


def build_td_signals_from_11d(result, cfg):
    source = load_11d_sources(result)
    signals = mb.build_td_signals(
        source["summary_rows"], source["compare_rows"], source["baseline_rows"],
        long_authority=cfg.get("long_authority"), config=cfg,
    )
    return signals, source


def path_guidance_design(visum, out_dir, cfg, baseline_12d, zones, actuatable_zones,
                         incidence_and_export=None, progress_callback=None):
    """Build fresh actual-path incidence and P/A guidance for one generation block."""
    out_dir = Path(out_dir)
    if incidence_and_export is None:
        station_map, pair_authority = rt.load_kordon_inputs(cfg)
        incidence, export_summary = rt.export_actual_paths_and_build_incidence(
            visum, out_dir, cfg, baseline_12d["rows"], actuatable_zones,
            station_map=station_map, pair_authority=pair_authority,
        )
    else:
        incidence, export_summary = incidence_and_export
        if cfg.get("apply"):
            raise RuntimeError("PRECOMPUTED_DESIGN_INCIDENCE_FORBIDS_APPLY")
    write_json(out_dir / "05_INCIDENCE_SUMMARY.json", {
        k: v for k, v in incidence.items() if k not in (
            "profiles", "variables", "projection_base_variables", "q_current", "incidence",
            "incidence_share", "incidence_through", "full_profile_model_from_paths",
            "native_ws_profile_model_from_paths", "mutable_profile_model_from_paths", "pair_observations",
        )
    })
    write_csv(out_dir / "05A_VARIABLE_CATALOG.csv", incidence["variables"])
    write_csv(out_dir / "05AA_PROJECTION_BASE_VARIABLE_CATALOG.csv", incidence["projection_base_variables"])
    path_scope_fields = ["model_" + mb.sval(code) for code in export_summary.get("dsegs", [])]
    parity = core.path_parity_rows(
        baseline_12d["rows"], incidence["full_profile_model_from_paths"], model_fields=path_scope_fields,
    )
    parity_summary = core.summarize_path_parity(parity, cfg)
    write_csv(out_dir / "05B_PATH_VS_12D_PARITY.csv", parity)
    write_json(out_dir / "05C_PATH_PARITY_SUMMARY.json", parity_summary)
    coverage_ok = float(incidence.get("path_link_coverage", 0.0)) >= float(cfg.get("min_path_link_coverage", 0.98))
    volume_ok = float(incidence.get("path_link_volume_coverage", 0.0)) >= float(cfg.get("min_path_link_volume_coverage", 0.995))
    dseg_ok = bool(export_summary.get("dseg_path_volume_parity_passes", False))
    if cfg.get("apply", False):
        if cfg.get("require_path_parity_for_apply", True) and not (coverage_ok and volume_ok and parity_summary.get("passes", False)):
            raise RuntimeError("Actual-path incidence/parity gate failed")
        if cfg.get("require_dseg_path_volume_parity_for_apply", True) and not dseg_ok:
            raise RuntimeError("Saved path totals do not match OD matrix totals")
    if progress_callback: progress_callback("GENERATION_PREPARE_GUIDANCE")
    problem = core.prepare_guidance_problem(incidence, cfg, include_pair_observations=bool(cfg.get("enable_kordon_pairs", False)))
    if progress_callback: progress_callback("GENERATION_NUMERICAL_SOLVE")
    result = core.solve_guidance(problem, cfg)
    if progress_callback: progress_callback("GENERATION_PA_PROJECTION")
    projection = core.project_guidance_to_add(
        problem, result, zones, cfg, all_variable_meta=incidence["projection_base_variables"],
    )
    if progress_callback: progress_callback("GENERATION_DIAGNOSTIC_EXPORT")
    write_csv(out_dir / "06_OBJECTIVE_ROWS_LINEAR_FIT.csv", rt.objective_rows_with_fit(problem, result))
    write_csv(out_dir / "06B_DROPPED_OBJECTIVE_ROWS.csv", problem.dropped_objective_rows)
    write_json(out_dir / "06C_SELECTION_SUMMARY.json", problem.selection_summary)
    write_csv(out_dir / "07_OD_GUIDANCE.csv", rt.guidance_rows(problem, result))
    write_csv(out_dir / "08_PA_PROJECTION.csv", projection.rows)
    write_csv(out_dir / "08B_PA_PROJECTION_FAMILY_SUMMARY.csv", projection.family_summaries)
    solver_summary = {
        "objective_initial": result.objective_initial,
        "objective_final": result.objective_final,
        "iterations": result.iterations,
        "converged": result.converged,
        "lipschitz": result.lipschitz,
        "nonzero_guidance": int(sum(abs(float(x)) > 1.0e-10 for x in result.x.tolist())),
        "projection_weighted_rmse": projection.weighted_rmse,
        "projection_all_converged": all(bool(r.get("converged", False)) for r in projection.family_summaries) if projection.family_summaries else False,
        "history": result.history,
    }
    write_json(out_dir / "07B_SOLVER_SUMMARY.json", solver_summary)
    return {
        "incidence": incidence, "path_export_summary": export_summary,
        "parity_summary": parity_summary, "problem": problem, "result": result,
        "projection": projection, "solver_summary": solver_summary,
    }


def generation_candidate(visum, zones, projection, cfg, scale, reference_values=None, zone_indices=None, retry_policy=None):
    zrows, attrs = zone_state_rows(
        visum, zones, cfg, zone_indices=zone_indices, retry_policy=retry_policy)
    design = mb.design_generation_candidates(
        projection.rows, zrows, cfg, scale=scale,
        reference_values=reference_values)
    design["zone_attributes_read"] = attrs
    return design


def generation_apply_gate(design, cfg):
    reasons = []
    if not design.get("candidate_rows"):
        reasons.append("NO_GENERATION_CANDIDATE_ROWS")
    salary = design.get("summary", {}).get("salary", {})
    if salary.get("enabled") and salary.get("status") not in (
        "JOINT_RIDGE_OK", "ADD_ATT_ONLY_FALLBACK", "ADD_ATT_ONLY_DEGENERATE_SALARY_BASIS",
        "NO_ELIGIBLE_WORK_ATTRACTION_ROWS",
    ):
        reasons.append("SALARY_DESIGN_NOT_IDENTIFIED")
    max_error = float(design.get("summary", {}).get("max_abs_effect_log_error", 0.0) or 0.0)
    if max_error > float(cfg.get("max_generation_effect_log_error", 0.01)):
        reasons.append("GENERATION_EFFECT_PROJECTION_ERROR_TOO_LARGE")
    gaps = design.get("summary", {}).get("estimated_pa_delta_by_family", {})
    max_rel_gap = float(cfg.get("max_generation_pa_relative_gap", 0.02))
    for family, row in gaps.items():
        p = abs(float(row.get("estimated_prod_delta", 0.0) or 0.0))
        a = abs(float(row.get("estimated_att_delta", 0.0) or 0.0))
        rel = float(row.get("estimated_abs_gap", 0.0) or 0.0) / max(1.0, p, a)
        row["estimated_relative_gap"] = rel
        if rel > max_rel_gap:
            reasons.append("GENERATION_PA_GAP_%s" % family)
    return {"passes": not reasons, "reasons": reasons}


def td_acceptance_decision(before_12d, after_12d, before_11d, after_11d,
                           before_signals, after_signals, components, cfg):
    """Fail-closed TD acceptance with V2.4.9.6 early Pareto exploration.

    During the explicitly configured early cycles, GEH20/30 transitions are
    continuous diagnostics rather than binary walls.  A TD candidate must still
    materially improve the selected distribution objective, stay within the
    reviewed CAL-GEH loss budget, satisfy a benefit/cost ratio, and pass the
    catastrophic GEH40/protected/authority guards.  Later cycles inherit the
    exact V2.4.9.5 acceptance contract.
    """
    td_cfg = cfg.get("td", {})
    early = core.early_exploration_policy(cfg, "TD")
    early_td = early["scoped"] if early is not None else {}
    input_selected = list(dict.fromkeys(mb.sval(x) for x in components if mb.sval(x)))
    selected = mb.collapse_td_acceptance_components(input_selected, cfg)
    before_metric = mb.td_component_metrics(before_signals, selected, cfg)
    after_metric = mb.td_component_metrics(after_signals, selected, cfg)
    bobj = float(before_metric.get("weighted_objective", float("inf")))
    aobj = float(after_metric.get("weighted_objective", float("inf")))
    rel_improvement = ((bobj - aobj) / max(core.EPS, abs(bobj))
                       if math.isfinite(bobj) else -float("inf"))
    bmap = {r.get("component"): r for r in before_metric.get("components", [])}
    amap = {r.get("component"): r for r in after_metric.get("components", [])}
    component_checks = []
    selected_failures = []
    if early is not None:
        min_rel = float(early_td.get("min_selected_relative_improvement", 0.0025))
        max_rel_deg = float(early_td.get("max_selected_component_relative_degradation", 0.20))
        max_nonselected_deg = float(early_td.get("max_nonselected_component_relative_degradation", 0.20))
    else:
        min_rel = float(td_cfg.get("min_selected_component_relative_improvement", 0.002))
        max_rel_deg = float(td_cfg.get("max_selected_component_relative_degradation", 0.0))
        max_nonselected_deg = float(td_cfg.get("max_nonselected_component_objective_degradation", 0.01))
    for comp in selected:
        b = bmap.get(comp); a = amap.get(comp)
        if not b or not a:
            component_checks.append({"component": comp, "passes": False, "reason": "AUTHORITY_OR_METRIC_MISSING"})
            selected_failures.append(comp)
            continue
        bo = float(b["objective"]); ao = float(a["objective"])
        ri = (bo - ao) / max(core.EPS, abs(bo))
        rel_deg = (ao - bo) / max(core.EPS, abs(bo))
        passes = ri >= min_rel or rel_deg <= max_rel_deg
        component_checks.append({"component": comp, "before_objective": bo,
                                 "after_objective": ao, "relative_improvement": ri,
                                 "relative_degradation": rel_deg, "passes": passes})
        if not passes:
            selected_failures.append(comp)

    nonselected_checks = []
    for comp, bsig in sorted(before_signals.items()):
        if comp in selected or not bool(bsig.get("calibratable", False)):
            continue
        asig = after_signals.get(comp)
        if not asig or not bool(asig.get("calibratable", False)):
            continue
        bm = mb.td_component_metrics(before_signals, [comp], cfg)
        am = mb.td_component_metrics(after_signals, [comp], cfg)
        bo = float(bm.get("weighted_objective", float("inf")))
        ao = float(am.get("weighted_objective", float("inf")))
        deg = ((ao - bo) / max(core.EPS, abs(bo))
               if math.isfinite(bo) else float("inf"))
        passes = deg <= max_nonselected_deg
        nonselected_checks.append({"component": comp, "before_objective": bo,
                                   "after_objective": ao, "relative_degradation": deg,
                                   "passes": passes})

    bcal = core.csd_metrics(before_12d, "CALIBRATION", True)
    acal = core.csd_metrics(after_12d, "CALIBRATION", True)
    cal_metric = core.csd_objective_metric(cfg)
    cal_key = core.csd_objective_key(cfg)
    bcal_objective = core.csd_objective_value(bcal, cfg)
    acal_objective = core.csd_objective_value(acal, cfg)
    csd_rel_degradation = ((acal_objective - bcal_objective) /
                           max(core.EPS, abs(bcal_objective))
                           if math.isfinite(bcal_objective) else float("inf"))
    bgeh = float(bcal.get("objective_geh_mean_weighted", float("inf")))
    ageh = float(acal.get("objective_geh_mean_weighted", float("inf")))
    geh_rel_degradation = ((ageh - bgeh) / max(core.EPS, abs(bgeh))
                           if math.isfinite(bgeh) else float("inf"))
    bgeh2 = float(bcal.get("objective_geh2_mean", float("inf")))
    ageh2 = float(acal.get("objective_geh2_mean", float("inf")))
    geh2_rel_degradation = ((ageh2 - bgeh2) / max(core.EPS, abs(bgeh2))
                            if math.isfinite(bgeh2) else float("inf"))
    obs_guard = core.observation_set_guard(before_12d, after_12d)
    protect = core.protected_profile_guard(before_12d, after_12d, cfg, "TD")
    severity = core.severity_transition_guard(before_12d, after_12d, cfg, "TD")
    bidp = core.idp_metrics(before_11d)
    aidp = core.idp_metrics(after_11d)
    reasons = []
    if before_metric.get("n", 0) != len(selected) or after_metric.get("n", 0) != len(selected):
        reasons.append("SELECTED_TD_COMPONENT_AUTHORITY_MISSING")
    aggregate_min = (float(early_td.get("min_selected_relative_improvement", 0.0025))
                     if early is not None else
                     float(td_cfg.get("min_selected_component_relative_improvement", 0.002)))
    if not math.isfinite(aobj) or rel_improvement < aggregate_min:
        reasons.append("SELECTED_TD_OBJECTIVE_NOT_IMPROVED")
    if selected_failures:
        reasons.append("SELECTED_COMPONENT_NOT_IMPROVED:%s" % ",".join(selected_failures))
    bad_nonselected = [r["component"] for r in nonselected_checks if not r["passes"]]
    if bad_nonselected:
        reasons.append("NONSELECTED_COMPONENT_DEGRADED:%s" % ",".join(bad_nonselected))
    if early is not None:
        max_cal_degradation = float(early_td.get("max_cal_relative_degradation", 0.05))
        min_ratio = float(early_td.get("min_benefit_cost_ratio", 1.5))
    elif cal_metric == core.CSD_OBJECTIVE_WEIGHTED_MEAN_GEH:
        max_cal_degradation = float(td_cfg.get(
            "max_cal_geh_relative_degradation",
            td_cfg.get("max_cal_geh2_relative_degradation", 0.005)))
        min_ratio = None
    else:
        max_cal_degradation = float(td_cfg.get("max_cal_geh2_relative_degradation", 0.005))
        min_ratio = None
    positive_cost = max(0.0, csd_rel_degradation)
    benefit_cost_ratio = (float("inf") if positive_cost <= core.EPS and rel_improvement >= 0.0
                          else rel_improvement / max(core.EPS, positive_cost))
    if csd_rel_degradation > max_cal_degradation + core.EPS:
        reasons.append("CAL_CSD_DEGRADED_TOO_MUCH")
    if early is not None and positive_cost > core.EPS and benefit_cost_ratio < min_ratio:
        reasons.append("TD_BENEFIT_COST_RATIO_TOO_LOW")
    if not obs_guard.get("passes", False):
        reasons.append("OBSERVATION_AUTHORITY_CHANGED")
    if not protect.get("passes", False):
        reasons.append("PROTECTED_PROFILE_GUARD_FAILED")
    if not severity.get("passes", False):
        reasons.append("NEW_SEVERE_GEH_PROFILE")
    mean_degradation = float(aidp.get("mean_relative_error", 0.0)) - float(bidp.get("mean_relative_error", 0.0))
    max_degradation = float(aidp.get("max_relative_error", 0.0)) - float(bidp.get("max_relative_error", 0.0))
    if bidp.get("component_set") != aidp.get("component_set"):
        reasons.append("IDP_COMPONENT_AUTHORITY_CHANGED")
    if mean_degradation > float(td_cfg.get("max_global_idp_mean_degradation", 0.002)):
        reasons.append("GLOBAL_IDP_MEAN_DEGRADED")
    if max_degradation > float(td_cfg.get("max_global_idp_component_degradation", 0.01)):
        reasons.append("GLOBAL_IDP_COMPONENT_DEGRADED")
    return {
        "accepted": not reasons, "reasons": reasons,
        "active_acceptance_stage": ("EARLY_EXPLORATION" if early is not None else "INHERITED"),
        "acceptance_path": ("EARLY_EXPLORATION_PARETO" if early is not None else "INHERITED_TD_SOFT_REFERENCE"),
        "early_exploration_policy": early,
        "input_selected_components": input_selected, "selected_components": selected,
        "long_component_collapse": {
            "enabled": mb.long_composite_enabled(cfg),
            "input_long_components": [x for x in input_selected
                                      if x == "LONG_COMPOSITE" or
                                      mb.COMPONENT_REGISTRY.get(x, {}).get("family") == "LONG"],
            "acceptance_component": ("LONG_COMPOSITE" if "LONG_COMPOSITE" in selected else None),
        },
        "selected_before": before_metric, "selected_after": after_metric,
        "selected_component_checks": component_checks,
        "nonselected_component_checks": nonselected_checks,
        "selected_relative_improvement": rel_improvement,
        "selected_minimum_relative_improvement": aggregate_min,
        "benefit_cost_ratio": benefit_cost_ratio,
        "minimum_benefit_cost_ratio": min_ratio,
        "cal_before": bcal, "cal_after": acal,
        "cal_csd_objective_metric": cal_metric, "cal_csd_objective_key": cal_key,
        "cal_csd_objective_before": bcal_objective,
        "cal_csd_objective_after": acal_objective,
        "cal_csd_relative_degradation": csd_rel_degradation,
        "cal_csd_max_relative_degradation": max_cal_degradation,
        "cal_geh_relative_degradation": geh_rel_degradation,
        "cal_geh2_relative_degradation": geh2_rel_degradation,
        "validation_before_report_only": core.csd_metrics(before_12d, "VALIDATION", True),
        "validation_after_report_only": core.csd_metrics(after_12d, "VALIDATION", True),
        "validation_used_for_design_or_acceptance": False,
        "idp_before": bidp, "idp_after": aidp,
        "global_idp_mean_degradation": mean_degradation,
        "global_idp_max_component_degradation": max_degradation,
        "observation_set_guard": obs_guard, "protected_guard": protect,
        "severity_transition_guard": severity,
    }


def block_family(block):
    return {
        "TD_WORK": "WORK", "TD_COMPONENT_WORK": "WORK",
        "TD_SERVICE": "SERVICE", "TD_COMPONENT_SERVICE": "SERVICE",
        "TD_SCHOOL": "SCHOOL", "TD_COMPONENT_SCHOOL": "SCHOOL",
        "TD_LONG": "LONG", "TD_COMPONENT_LONG": "LONG",
    }.get(block)


def design_td_block(visum, baseline_11d, family, cfg, scale, out_dir):
    signals, source = build_td_signals_from_11d(baseline_11d, cfg)
    state = vp.read_td_parameter_state(visum)
    current = vp.td_parameter_map(state)
    design = mb.design_td_candidates(signals, current, family, cfg, scale=scale)
    write_csv(Path(out_dir) / "11_TD_PARAMETER_STATE.csv", state["rows"])
    write_csv(Path(out_dir) / "11B_TD_OPERATION_AUDIT.csv", state["operation_rows"])
    write_json(Path(out_dir) / "11C_TD_SIGNAL_SOURCE.json", source["paths"])
    write_csv(Path(out_dir) / "12_TD_SIGNALS.csv", [dict(v) for _, v in sorted(signals.items())])
    return design, signals, state


def matrix_change_gate(visum, cfg, block, before_fp, out_dir):
    after_fp = block_matrix_fingerprints(visum, cfg, block)
    compare = rt.compare_explicit_matrix_fingerprints(before_fp, after_fp)
    write_csv(Path(out_dir) / "16_MUTABLE_MATRIX_FINGERPRINT_AFTER.csv", after_fp)
    write_csv(Path(out_dir) / "16B_MUTABLE_MATRIX_CHANGE.csv", compare)
    changed = sum(int(r.get("changed", 0) or 0) for r in compare if int(r.get("comparable", 0) or 0) == 1)
    failed = [r for r in compare if int(r.get("comparable", 0) or 0) != 1]
    return compare, changed, failed


def run_design_only(visum, run_dir, cfg, zones, actuatable_zones, baseline_12d, baseline_11d):
    design_root = Path(run_dir) / "DESIGN_ONLY"
    design_root.mkdir(parents=True, exist_ok=False)
    gen_dir = design_root / "GENERATION"
    gen_dir.mkdir()
    generation = path_guidance_design(visum, gen_dir, cfg, baseline_12d, zones, actuatable_zones)
    gen_design = generation_candidate(visum, zones, generation["projection"], cfg, 1.0)
    write_csv(gen_dir / "09_GENERATION_CANDIDATE.csv", gen_design["candidate_rows"])
    write_csv(gen_dir / "09B_GENERATION_SKIPPED.csv", gen_design["skipped_rows"])
    write_csv(gen_dir / "09C_GENERATION_EFFECT_ROWS.csv", gen_design.get("effect_rows", []))
    write_json(gen_dir / "09D_GENERATION_SUMMARY.json", gen_design["summary"])
    write_json(gen_dir / "09E_GENERATION_APPLY_GATE.json", generation_apply_gate(gen_design, cfg))

    td_summary = []
    for block in cfg.get("block_schedule", []):
        family = block_family(block)
        if not family:
            continue
        td_dir = design_root / block
        td_dir.mkdir()
        design, signals, state = design_td_block(visum, baseline_11d, family, cfg, 1.0, td_dir)
        write_csv(td_dir / "13_TD_CANDIDATE.csv", design["candidate_rows"])
        write_csv(td_dir / "13B_TD_SKIPPED.csv", design["skipped_rows"])
        write_json(td_dir / "13C_TD_DESIGN_SUMMARY.json", design["summary"])
        td_summary.append({"block": block, "family": family, **design["summary"]})
    return {
        "generation_candidate_count": len(gen_design["candidate_rows"]),
        "generation_attrs": gen_design["summary"].get("attrs_changed", []),
        "td_blocks": td_summary,
    }


def main():
    cfg = load_config()
    root = HERE / OUT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / ("run_" + stamp())
    run_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(str(HERE / CONFIG_NAME), str(run_dir / CONFIG_NAME))
    shutil.copy2(cfg["tg_dependency_contract_path"], str(run_dir / Path(cfg["tg_dependency_contract_path"]).name))
    shutil.copy2(cfg["long_authority_path"], str(run_dir / Path(cfg["long_authority_path"]).name))
    summary = {
        "script_id": SCRIPT_ID,
        "started_at": now_iso(),
        "status": "STARTED",
        "apply": bool(cfg.get("apply", False)),
        "config_sha256": cfg["config_sha256"],
        "tg_dependency_contract_sha256": cfg["tg_dependency_contract_sha256"],
        "long_authority_sha256": cfg["long_authority_sha256"],
        "accepted_blocks": [],
        "block_runs": [],
        "writes_direct_od_matrix": False,
        "validation_used_for_design_or_acceptance": False,
    }
    try:
        if np is None:
            raise RuntimeError("NumPy is required")
        visum, connection = connect_visum()
        summary["connection"] = connection
        zones = rt.zone_numbers(visum)
        if len(zones) != EXPECTED_ZONES:
            raise RuntimeError("Expected %d zones" % EXPECTED_ZONES)
        actuatable_zones, actuator_scope = generation_actuator_zone_scope(visum, zones, cfg, run_dir)
        summary["generation_actuator_scope"] = actuator_scope

        procseq = rt.audit_procseq(visum, run_dir, cfg)
        summary["procseq"] = procseq
        if cfg.get("apply", False) and not procseq.get("passes", False):
            raise RuntimeError("Procedure Sequence gate failed: %s" % procseq.get("reasons"))

        tg_audit = vp.audit_trip_generation_contract(visum, cfg)
        write_json(run_dir / "00_TG_DEPENDENCY_AUDIT.json", tg_audit)
        write_csv(run_dir / "00_TG_ROW_AUDIT.csv", tg_audit.get("rows", []))
        write_csv(run_dir / "00_TG_ZONE_ATTRIBUTE_AUDIT.csv", tg_audit.get("zone_attribute_rows", []))
        if cfg.get("apply", False) and cfg.get("require_tg_dependency_contract_for_apply", True) and not tg_audit.get("passes", False):
            raise RuntimeError("TG dependency audit failed: %s" % tg_audit.get("failures"))

        baseline_dir = run_dir / "BASELINE"
        baseline_dir.mkdir()
        baseline_12d, baseline_11d = rt.run_diagnostics(visum, baseline_dir, "CURRENT", cfg)
        summary["baseline_12d_gate"] = baseline_12d["row_gate"]

        if not cfg.get("apply", False):
            summary["design_only"] = run_design_only(visum, run_dir, cfg, zones, actuatable_zones, baseline_12d, baseline_11d)
            summary["status"] = "PASS_DESIGN_ONLY_MULTIBLOCK"
            return

        accepted_count = 0
        max_accepted = max(1, int(cfg.get("max_accepted_blocks", 1)))
        max_cycles = max(1, int(cfg.get("max_cycles", 1)))
        schedule = list(cfg.get("block_schedule", []))
        for cycle in range(1, max_cycles + 1):
            if accepted_count >= max_accepted:
                break
            for block in schedule:
                if accepted_count >= max_accepted:
                    break
                block_dir = run_dir / ("CYCLE_%02d_%s" % (cycle, block))
                block_dir.mkdir(parents=True, exist_ok=False)
                block_record = {"cycle": cycle, "block": block, "status": "STARTED", "attempts": []}
                summary["block_runs"].append(block_record)
                log(run_dir, "Design block %s cycle %d" % (block, cycle))

                generation_context = None
                baseline_signals = None
                td_state = None
                if block == "GENERATION":
                    generation_context = path_guidance_design(visum, block_dir, cfg, baseline_12d, zones, actuatable_zones)
                    if cfg.get("require_solver_convergence_for_apply", True) and not generation_context["result"].converged:
                        block_record["status"] = "SKIP_SOLVER_NOT_CONVERGED"; continue
                    if cfg.get("require_projection_convergence_for_apply", True):
                        fams = generation_context["projection"].family_summaries
                        if not fams or not all(bool(x.get("converged", False)) for x in fams):
                            block_record["status"] = "SKIP_PA_PROJECTION_NOT_CONVERGED"; continue
                else:
                    family = block_family(block)
                    if family is None:
                        block_record["status"] = "SKIP_UNKNOWN_BLOCK"; continue
                    baseline_signals, _src = build_td_signals_from_11d(baseline_11d, cfg)
                    td_state = vp.read_td_parameter_state(visum)
                    write_csv(block_dir / "11_TD_PARAMETER_STATE_BASELINE.csv", td_state["rows"])

                pre = rt.save_version(visum, block_dir / "PRE.ver")
                block_record["pre_checkpoint"] = pre
                pre_state = capture_pre_state(visum, zones, cfg, block)
                before_fp = pre_state["matrix"]
                write_csv(block_dir / "16_MUTABLE_MATRIX_FINGERPRINT_BEFORE.csv", before_fp)
                write_csv(block_dir / "16C_GENERATION_PARAMETER_SNAPSHOT_BEFORE.csv", pre_state["zone"])
                write_csv(block_dir / "16D_TD_PARAMETER_SNAPSHOT_BEFORE.csv", pre_state["td"])
                if any(r.get("status") != "OK" for r in before_fp):
                    raise RuntimeError("Could not fingerprint block matrices")

                accepted = False
                for attempt_no, scale in enumerate(cfg.get("backtracking_scales", [1.0, 0.5, 0.25]), start=1):
                    attempt_dir = block_dir / ("ATTEMPT_%02d_SCALE_%s" % (attempt_no, str(scale).replace(".", "p")))
                    attempt_dir.mkdir()
                    attempt = {"attempt": attempt_no, "scale": float(scale), "status": "STARTED"}
                    block_record["attempts"].append(attempt)
                    try:
                        if block == "GENERATION":
                            design = generation_candidate(visum, zones, generation_context["projection"], cfg, float(scale))
                            write_csv(attempt_dir / "09_GENERATION_CANDIDATE.csv", design["candidate_rows"])
                            write_csv(attempt_dir / "09B_GENERATION_SKIPPED.csv", design["skipped_rows"])
                            write_csv(attempt_dir / "09C_GENERATION_EFFECT_ROWS.csv", design.get("effect_rows", []))
                            write_json(attempt_dir / "09D_GENERATION_SUMMARY.json", design["summary"])
                            gate = generation_apply_gate(design, cfg)
                            write_json(attempt_dir / "09E_GENERATION_APPLY_GATE.json", gate)
                            if not gate["passes"]:
                                raise RuntimeError("Generation design gate failed: %s" % gate["reasons"])
                            candidates = design["candidate_rows"]
                            apply_audit = rt.apply_add_candidate(visum, candidates, zones)
                            write_csv(attempt_dir / "10_GENERATION_APPLY_AUDIT.csv", apply_audit)
                            if any(r.get("status") != "OK" for r in apply_audit):
                                raise RuntimeError("Generation readback mismatch")
                        else:
                            family = block_family(block)
                            current = vp.td_parameter_map(td_state)
                            design = mb.design_td_candidates(baseline_signals, current, family, cfg, scale=float(scale))
                            candidates = design["candidate_rows"]
                            write_csv(attempt_dir / "13_TD_CANDIDATE.csv", candidates)
                            write_csv(attempt_dir / "13B_TD_SKIPPED.csv", design["skipped_rows"])
                            write_json(attempt_dir / "13C_TD_DESIGN_SUMMARY.json", design["summary"])
                            if not candidates:
                                attempt["status"] = "NO_EFFECTIVE_CANDIDATE"
                                continue
                            apply_audit = vp.apply_td_candidates(visum, candidates)
                            write_csv(attempt_dir / "14_TD_APPLY_AUDIT.csv", apply_audit)
                            if any(r.get("status") != "OK" for r in apply_audit):
                                raise RuntimeError("TD parameter readback mismatch or write failure")

                        if cfg.get("run_procseq", True):
                            rt.execute_procseq(visum, attempt_dir)
                        if block == "GENERATION":
                            persistence = rt.verify_add_candidate_persistence(visum, candidates, zones)
                            write_csv(attempt_dir / "15_GENERATION_POST_PROCSEQ_READBACK.csv", persistence)
                        else:
                            persistence = vp.verify_td_persistence(visum, candidates)
                            write_csv(attempt_dir / "15_TD_POST_PROCSEQ_READBACK.csv", persistence)
                        if cfg.get("require_parameter_persistence_after_procseq", True) and any(r.get("status") != "OK" for r in persistence):
                            raise RuntimeError("Procedure Sequence overwrote candidate parameters")

                        matrix_compare, changed_n, matrix_failures = matrix_change_gate(visum, cfg, block, before_fp, attempt_dir)
                        if matrix_failures:
                            raise RuntimeError("Block matrix fingerprint comparison failed: %s" % matrix_failures)
                        min_changed = int((cfg.get("min_changed_matrices_by_block", {}) or {}).get(block, 1))
                        if changed_n < min_changed:
                            raise RuntimeError("Candidate did not change required block matrices: block=%s changed=%d required=%d" % (block, changed_n, min_changed))
                        after_12d, after_11d = rt.run_diagnostics(visum, attempt_dir, "AFTER", cfg)
                        if block == "GENERATION":
                            decision = core.acceptance_decision(
                                baseline_12d["rows"], after_12d["rows"],
                                baseline_11d["summary"], after_11d["summary"], cfg,
                            )
                        else:
                            after_signals, _after_src = build_td_signals_from_11d(after_11d, cfg)
                            components = [mb.sval(r.get("component")) for r in candidates]
                            decision = td_acceptance_decision(
                                baseline_12d["rows"], after_12d["rows"],
                                baseline_11d["summary"], after_11d["summary"],
                                baseline_signals, after_signals, components, cfg,
                            )
                        write_json(attempt_dir / "17_ACCEPTANCE.json", decision)
                        attempt["acceptance"] = decision
                        attempt["mutable_matrix_changed_count"] = changed_n
                        if decision.get("accepted", False):
                            accepted_ver = rt.save_version(visum, attempt_dir / "ACCEPTED.ver")
                            attempt["accepted_checkpoint"] = accepted_ver
                            attempt["status"] = "ACCEPTED"
                            block_record["status"] = "ACCEPTED"
                            summary["accepted_blocks"].append({
                                "cycle": cycle, "block": block, "attempt": attempt_no,
                                "scale": float(scale), "checkpoint": accepted_ver,
                            })
                            baseline_12d, baseline_11d = after_12d, after_11d
                            accepted_count += 1
                            accepted = True
                            break
                        attempt["status"] = "REJECTED"
                    except Exception as exc:
                        attempt["status"] = "FAILED"
                        attempt["error"] = compact_error(exc)
                        with (attempt_dir / "99_TRACEBACK.txt").open("w", encoding="utf-8") as f:
                            f.write(traceback.format_exc())
                    if not accepted:
                        gc.collect()
                        rt.load_version(visum, pre["path"])
                        attempt["rolled_back_to"] = pre["path"]
                        visum, _ = connect_visum()
                        zones = rt.zone_numbers(visum)
                        verify_loaded_checkpoint_state(visum, zones, cfg, block, pre_state, attempt_dir)
                        if block != "GENERATION":
                            td_state = vp.read_td_parameter_state(visum)
                if not accepted:
                    block_record["status"] = "NO_ACCEPTED_ATTEMPT"

        summary["accepted_block_count"] = accepted_count
        summary["status"] = "PASS_APPLY_ACCEPTED_%d_BLOCKS" % accepted_count if accepted_count else "PASS_APPLY_NO_BLOCK_ACCEPTED"
    except Exception as exc:
        summary["status"] = "FAIL"
        summary["error"] = compact_error(exc)
        with (run_dir / "99_TRACEBACK.txt").open("w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
    finally:
        summary["finished_at"] = now_iso()
        write_json(run_dir / "00_SUMMARY.json", summary)
        zip_evidence(run_dir, run_dir.parent / (run_dir.name + ".zip"))
        log(run_dir, "FINISHED %s" % summary.get("status"))


if __name__ == "__main__":
    main()
