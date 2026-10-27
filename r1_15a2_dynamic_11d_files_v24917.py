# -*- coding: utf-8 -*-
"""V24917 fix: dynamic 11D overlay must publish the 11D component CSV files.

Defect (V24916, first live run 2026-10-25 02:48):
``VisumAdapter._dynamic_11d_overlay`` moves ``d11["summary_path"]`` into a new
folder ``11D_DYNAMIC_ASSIGNMENT_SKIM_<label>`` that only contains the dynamic
JSON/CSV summaries, then calls ``build_td_signals_from_11d``.  That function
reads three 11D CSV files next to ``summary_path``:
    r1_step11d_v1_3_component_dist_behavior_component_model_dist_vs_idp_summary.csv
    r1_step11d_v1_3_component_dist_behavior_component_model_dist_vs_idp.csv
    r1_step11d_v1_3_component_dist_behavior_component_model_dist_baseline.csv
so BASELINE diagnostics failed with "11D component files incomplete".

Fix (sealed V24916 file unchanged):
1. ``stage_static_files`` copies the three CSVs of the static 11D run into the
   dynamic folder BEFORE the inherited overlay runs (it can then complete).
2. ``publish_dynamic_files`` afterwards rewrites
   - the summary CSV with the dynamic component summary rows,
   - the baseline CSV with model bin shares computed on the fresh assignment
     DIS skims (same edges / same formulas as the FineCDF dynamic metrics),
     only where the bin set matches exactly; otherwise the static bins of that
     component are kept and reported;
   - the target (vs_idp) CSV is unchanged: targets do not depend on distance,
   and rebuilds the TD signals from the dynamic files.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import numpy as np

import r1_15a2_runtime_v1 as rt
import r1_15a2_runtime_io_hotfix_profile488 as io

RELEASE = "R1_15A2_V24917_DYNAMIC_11D_FILES_FIX_V1_20261025"
SUFFIXES = {
    "summary": "component_model_dist_vs_idp_summary.csv",
    "compare": "component_model_dist_vs_idp.csv",
    "baseline": "component_model_dist_baseline.csv",
}


def dynamic_folder(folder, label) -> Path:
    return Path(folder) / ("11D_DYNAMIC_ASSIGNMENT_SKIM_" + str(label))


def short_root() -> Path:
    r"""Short working root: trial folders + 81-char 11D file names exceed MAX_PATH.

    Live run 2026-10-25: ...\DEMAND_CYCLE_01_GENERATION\TRY_01\DIAGNOSTICS\
    11D_DYNAMIC_ASSIGNMENT_SKIM_AFTER\r1_step11d_..._summary.csv -> WinError 3.
    """
    base = Path(os.environ.get("R1_D11_SHORT_ROOT", "") or
                Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "R1DF" / "D11")
    return base


def new_short_folder() -> Path:
    folder = short_root() / uuid.uuid4().hex[:8]
    os.makedirs(io._native_path(folder), exist_ok=True)
    return folder


def _logical(native: str) -> str:
    if native.startswith("\\\\?\\UNC\\"):
        return "\\\\" + native[8:]
    if native.startswith("\\\\?\\"):
        return native[4:]
    return native


def find_long(workspace, name):
    """Long-path-safe recursive file search (newest match)."""
    best, best_mtime = None, None
    root = io._native_path(workspace)
    if not os.path.isdir(root):
        return None
    for dirpath, _dirs, files in os.walk(root):
        if name in files:
            full = os.path.join(dirpath, name)
            mtime = os.stat(full).st_mtime
            if best is None or mtime > best_mtime:
                best, best_mtime = full, mtime
    return Path(_logical(best)) if best else None


def mirror(src_folder: Path, dst_folder: Path) -> Dict[str, Any]:
    """Best-effort long-path-safe copy of the published files into the run evidence tree."""
    copied, errors = [], []
    native = io._native_path(src_folder)
    for name in sorted(os.listdir(native)) if os.path.isdir(native) else []:
        try:
            io.critical_copy_if_file(Path(src_folder) / name, Path(dst_folder) / name)
            copied.append(name)
        except Exception as exc:
            errors.append({"file": name, "error": repr(exc)[:300]})
    return {"source": str(src_folder), "destination": str(dst_folder),
            "copied": copied, "errors": errors}


def stage_static_files(static_summary_path, out: Path) -> Dict[str, str]:
    workspace = Path(static_summary_path).parent
    os.makedirs(io._native_path(out), exist_ok=True)
    staged = {}
    missing = []
    for key, suffix in SUFFIXES.items():
        src = find_long(workspace, rt.D11_PREFIX + suffix)
        if not src:
            missing.append(suffix)
            continue
        dst = out / (rt.D11_PREFIX + suffix)
        if io._native_path(src) != io._native_path(dst):
            io.critical_copy_if_file(src, dst)
        staged[key] = str(dst)
    if missing:
        raise RuntimeError("V24917_STATIC_11D_FILES_MISSING_UNDER_%s:%s" % (workspace, ",".join(missing)))
    return staged


def _key(lo, hi) -> str:
    try:
        lo = float(lo)
        hi = float("inf") if str(hi).strip().upper() in ("INF", "INFINITY") else float(hi)
    except Exception:
        return ""
    return "%.6f|%.6f" % (lo, hi)


def dynamic_baseline_rows(static_rows: Sequence[Mapping[str, Any]], metrics: Mapping[str, Mapping[str, Any]],
                          targets: Mapping[str, Mapping[str, Any]]):
    by_comp: Dict[str, list] = {}
    order = []
    for row in static_rows:
        comp = str(row.get("component", "")).strip()
        if comp not in by_comp:
            by_comp[comp] = []
            order.append(comp)
        by_comp[comp].append(dict(row))
    audit = {}
    out = []
    for comp in order:
        rows = by_comp[comp]
        metric = metrics.get(comp)
        target = targets.get(comp)
        if metric is None or target is None:
            audit[comp] = "STATIC_NO_DYNAMIC_METRIC"
            out.extend(rows)
            continue
        edges = [float(x) for x in target["edges"]]
        hist = np.asarray(metric["bin_volumes"], dtype=float)
        shares = np.asarray(metric["shares"], dtype=float)
        total = float(metric.get("total_volume_diagnostic", 0.0) or 0.0)
        dyn = {_key(edges[i], edges[i + 1]): i for i in range(len(edges) - 1)}
        keys = [_key(r.get("bin_low"), r.get("bin_high")) for r in rows]
        if not keys or any(k not in dyn for k in keys) or len(set(keys)) != len(dyn):
            audit[comp] = "STATIC_BINS_RETAINED_EDGE_MISMATCH"
            out.extend(rows)
            continue
        for row, k in zip(rows, keys):
            i = dyn[k]
            row["volume"] = float(hist[i])
            row["share_conditioned"] = float(shares[i])
            row["share_total"] = float(hist[i] / total) if total > 0 else 0.0
            row["metric"] = "DYNAMIC_ASSIGNMENT_DIS_KM"
        audit[comp] = "DYNAMIC_BINS"
        out.extend(rows)
    return out, audit


def publish_dynamic_files(adapter, diag: Dict[str, Any], out: Path, cfg) -> Dict[str, Any]:
    """Rewrite summary/baseline CSVs from dynamic metrics; rebuild TD signals."""
    import r1_15a2_supply_visum as supply_visum
    from r1_15a2_finecdf_bridge_v24916 import load_reference, DynamicFamilyMetrics
    from types import SimpleNamespace
    epoch = adapter.v24916_dynamic_skims.require_current()
    fine_cfg = (cfg.get("coupled_demand", {}) or {}).get("finecdf_td", {}) or {}
    ref, _path, _sha = load_reference(adapter._v24916_package_root, fine_cfg)
    needed = sorted({int(no) for t in ref.TARGETS.values() for no in t["matrix_nos"]})
    matrices = {no: np.asarray(adapter.visum.Net.Matrices.ItemByKey(int(no)).GetValues(),
                               dtype=np.float64) for no in needed}
    metrics = DynamicFamilyMetrics(SimpleNamespace(dynamic_skim_epoch=epoch), ref).evaluate(matrices)

    d11 = diag["d11"]
    summary_rows = list((d11.get("summary") or {}).get("component_dist_summary_rows") or [])
    summary_path = out / (rt.D11_PREFIX + SUFFIXES["summary"])
    baseline_path = out / (rt.D11_PREFIX + SUFFIXES["baseline"])
    static_baseline = rt.read_csv_auto(baseline_path)
    rows, audit = dynamic_baseline_rows(static_baseline, metrics, ref.TARGETS)
    if summary_rows:
        rt.write_csv(summary_path, summary_rows)
    rt.write_csv(baseline_path, rows)
    signals, _source = supply_visum.base.build_td_signals_from_11d(d11, cfg)
    diag["signals"] = signals
    report = {"release": RELEASE, "folder": str(out), "component_bins": audit,
              "summary_rows": len(summary_rows), "baseline_rows": len(rows),
              "dynamic_skim_epoch": int(epoch.epoch), "dynamic_skim_epoch_hash": epoch.epoch_hash,
              "target_file": "UNCHANGED_TARGETS_DO_NOT_DEPEND_ON_DISTANCE"}
    try:
        io.critical_atomic_json(out / "V24917_DYNAMIC_11D_FILES.json", report)
    except Exception:
        pass
    return report


__all__ = ["RELEASE", "dynamic_folder", "short_root", "new_short_folder", "find_long", "mirror", "stage_static_files", "dynamic_baseline_rows",
           "publish_dynamic_files"]
