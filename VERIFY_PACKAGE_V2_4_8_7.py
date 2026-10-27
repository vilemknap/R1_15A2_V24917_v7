# -*- coding: utf-8 -*-
"""Independent verifier for R1 15A2 V2.4.8.7 live coefficient authority."""
from __future__ import annotations

import argparse
import compileall
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RELEASE = "R1_15A2_V2_4_8_7_LIVE_COEFFICIENT_AUTHORITY_20261016"
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_7.py"
MANIFEST = "MANIFEST_V2487.json"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _probe(root, parts):
    path = root.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"probe")
    return path


def _generation_contract(root, cfg):
    import r1_15a2_multiblock as mb

    syn_cfg = {
        "preserve_zero_add": True,
        "add_min": 0.0,
        "add_max": None,
        "min_add_log_step": 1.0e-8,
        "explicit_excluded_zone_nos": [],
        "generation_coefficient_authority": cfg["generation_coefficient_authority"],
        "generation_bound_constrained_projection":
            cfg["generation_bound_constrained_projection"],
        "zahr": {
            "domestic_mask_attr": "NOT_ZAHR",
            "domestic_threshold": 0.5,
            "neighbour_attr": "ZAHR_SUSED",
            "population_attr": "POP_ZP",
            "min": 0.0,
            "max": None,
            "preserve_zero": True,
            "seed_floor": 0.0,
            "explicit_excluded_zone_nos": [],
        },
        "salary": {"enabled": False, "salary_min": None, "salary_max": None},
    }
    zones = [
        {"zone_no": 1, "NOT_ZAHR": 1, "ZAHR_SUSED": 0, "POP_ZP": 100,
         "ADD_PROD_W": 4.5, "ADD_ATT_W": 1.0, "ADD_PROD_S": 1.0, "ADD_ATT_S": 1.0,
         "ZAHR_PROD_WORK": 1.0, "ZAHR_ATR_WORK": 1.0,
         "ZAHR_PROD_SERV": 1.0, "ZAHR_ATR_SERV": 1.0},
        {"zone_no": 2, "NOT_ZAHR": 1, "ZAHR_SUSED": 0, "POP_ZP": 100,
         "ADD_PROD_W": 1.0, "ADD_ATT_W": 5.0, "ADD_PROD_S": 1.0, "ADD_ATT_S": 1.0,
         "ZAHR_PROD_WORK": 1.0, "ZAHR_ATR_WORK": 1.0,
         "ZAHR_PROD_SERV": 1.0, "ZAHR_ATR_SERV": 1.0},
        {"zone_no": 619, "NOT_ZAHR": 0, "ZAHR_SUSED": 1, "POP_ZP": 100,
         "ADD_PROD_W": 1.0, "ADD_ATT_W": 1.0, "ADD_PROD_S": 1.0, "ADD_ATT_S": 1.0,
         "ZAHR_PROD_WORK": 12.5, "ZAHR_ATR_WORK": 11.0,
         "ZAHR_PROD_SERV": 14.0, "ZAHR_ATR_SERV": 13.0},
    ]
    prod_dom = math.expm1(0.02) * 1000.0
    prod_zahr = math.expm1(0.08) * 1000.0
    att_step = math.log1p((prod_dom + prod_zahr) / 1000.0)
    projection = [
        {"zone_no": 1, "family": "WORK", "role": "PROD", "log_step": 0.02,
         "base_margin_volume": 1000.0, "guided_margin_delta": prod_dom,
         "projected_margin_delta": prod_dom},
        {"zone_no": 619, "family": "WORK", "role": "PROD", "log_step": 0.08,
         "base_margin_volume": 1000.0, "guided_margin_delta": prod_zahr,
         "projected_margin_delta": prod_zahr},
        {"zone_no": 2, "family": "WORK", "role": "ATT", "log_step": att_step,
         "base_margin_volume": 1000.0, "guided_margin_delta": prod_dom + prod_zahr,
         "projected_margin_delta": prod_dom + prod_zahr},
    ]
    design = mb.design_generation_candidates(projection, zones, syn_cfg, 1.0)
    audit = design["summary"]["bound_constrained_projection"]
    work = design["summary"]["estimated_pa_delta_by_family"]["WORK"]
    rel_gap = work["estimated_abs_gap"] / max(
        1.0, abs(work["estimated_prod_delta"]), abs(work["estimated_att_delta"]))
    zahr = next((row for row in design["candidate_rows"]
                 if row.get("zone_no") == 619 and row.get("attr") == "ZAHR_PROD_WORK"), None)
    domestic_prod = next((row for row in design["candidate_rows"]
                          if row.get("zone_no") == 1 and row.get("attr") == "ADD_PROD_W"), None)
    domestic_att = next((row for row in design["candidate_rows"]
                         if row.get("zone_no") == 2 and row.get("attr") == "ADD_ATT_W"), None)
    passes = bool(
        audit.get("enabled") is True and
        audit.get("coefficient_authority") == "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP" and
        audit.get("legacy_absolute_upper_bounds_enforced") is False and
        audit.get("clipped_count") == 0 and
        zahr and zahr["current"] == 12.5 and zahr["proposed"] > 12.5 and
        zahr["proposed"] > 10.0 and
        domestic_prod and domestic_prod["current"] == 4.5 and domestic_prod["proposed"] > 4.5 and
        domestic_att and domestic_att["current"] == 5.0 and domestic_att["proposed"] > 5.0 and
        rel_gap < 1.0e-9 and
        design["summary"]["max_abs_effect_log_error"] < 1.0e-9
    )
    return {
        "passes": passes,
        "authority": audit.get("coefficient_authority"),
        "legacy_absolute_upper_bounds_enforced":
            audit.get("legacy_absolute_upper_bounds_enforced"),
        "clipped_count": audit.get("clipped_count"),
        "zahr_current": zahr and zahr.get("current"),
        "zahr_proposed": zahr and zahr.get("proposed"),
        "domestic_prod_current": domestic_prod and domestic_prod.get("current"),
        "domestic_prod_proposed": domestic_prod and domestic_prod.get("proposed"),
        "domestic_att_current": domestic_att and domestic_att.get("current"),
        "domestic_att_proposed": domestic_att and domestic_att.get("proposed"),
        "work_relative_gap": rel_gap,
        "max_abs_effect_log_error": design["summary"]["max_abs_effect_log_error"],
    }

def verify(root, run_tests=False):
    root = Path(root).resolve()
    started = time.monotonic()
    errors = []
    manifest_path = root / MANIFEST
    if not manifest_path.is_file():
        return {"status": "FAILED", "errors": [MANIFEST + " missing"]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("release") != RELEASE:
        errors.append("MANIFEST_RELEASE_IDENTITY")
    for row in manifest.get("files", []):
        path = root / row["path"]
        if not path.is_file():
            errors.append("MISSING:" + row["path"])
            continue
        if path.stat().st_size != int(row["bytes"]):
            errors.append("SIZE:" + row["path"])
            continue
        if sha256(path) != row["sha256"]:
            errors.append("SHA256:" + row["path"])

    config_result = launcher_result = root_result = generation_result = None
    probe_root = Path(tempfile.mkdtemp(prefix="v2486_contract_"))
    inserted = False
    try:
        sys.path.insert(0, str(root))
        inserted = True
        from r1_15a2_safety_v2487 import validate_v2487_config
        spec = importlib.util.spec_from_file_location("verify_v2486_launcher", root / LAUNCHER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cfg = module.load_config()
        config_result = validate_v2487_config(cfg, root)
        if cfg.get("release") != RELEASE or module.RELEASE != RELEASE:
            errors.append("LAUNCHER_RELEASE_MISMATCH")

        compat = cfg["performance"]["persistent_path_cache"][
            "explicit_predecessor_read_compatibility"]
        predecessor_releases = {row["source_release"] for row in compat["predecessors"]}
        required_predecessors = {
            "R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016",
            "R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016",
            "R1_15A2_V2_4_8_3_CACHE_COMPAT_HOTFIX_20261016",
            "R1_15A2_V2_4_8_4_RUN_ROOT_HOTFIX_20261016",
            "R1_15A2_V2_4_8_5_STABLE_PROJECT_ROOT_20261016",
            "R1_15A2_V2_4_8_5_GENERATION_SATURATION_HOTFIX_20261016",
            "R1_15A2_V2_4_8_6_UNIFIED_ROOT_SATURATION_20261016",
        }
        if predecessor_releases != required_predecessors:
            errors.append("PREDECESSOR_CACHE_SET_NOT_LOCKED")

        project = probe_root / "PROJECT"
        single = _probe(project, ["R1_15A2_V2481_RUNS", "RUN_A", "CALIBRATION",
                                  "CHECKPOINTS", "ACCEPTED_A.ver"])
        double = _probe(project, ["R1_15A2_V2481_RUNS", "RUN_A", "CALIBRATION",
                                  "CHECKPOINTS", "R1_15A2_V2483_RUNS", "RUN_B",
                                  "CALIBRATION", "CHECKPOINTS", "ACCEPTED_B.ver"])
        triple = _probe(project, ["R1_15A2_V2481_RUNS", "RUN_A", "CALIBRATION",
                                  "CHECKPOINTS", "R1_15A2_V2483_RUNS", "RUN_B",
                                  "CALIBRATION", "CHECKPOINTS", "R1_15A2_V2484_RUNS",
                                  "RUN_C", "CALIBRATION", "CHECKPOINTS", "ACCEPTED_C.ver"])
        checks = []
        for name, source, depth in (("single", single, 1), ("double", double, 2),
                                    ("triple", triple, 3)):
            layout = module._stable_project_layout(source)
            ok = (
                layout["project_base"] == project.resolve() and
                layout["mode"] == "OUTERMOST_PRIOR_RUN_TREE_NORMALIZED" and
                len(layout["detected_run_roots_nearest_first"]) == depth
            )
            checks.append({"case": name, "expected_depth": depth,
                           "observed_depth": len(layout["detected_run_roots_nearest_first"]),
                           "project_base": str(layout["project_base"]), "passes": ok})
            if not ok:
                errors.append("RUN_ROOT_NORMALIZATION_FAILED:" + name)
        module._assert_new_run_is_not_nested(
            project / "R1_15A2_V2487_RUNS" / "RUN_TEST",
            module._run_tree_ancestors(triple))
        root_result = {
            "selection": "OUTERMOST_QUALIFYING_RUNS_ANCESTOR_PARENT",
            "cases": checks,
            "new_run_outside_prior_tree_postcondition": True,
        }

        generation_result = _generation_contract(root, cfg)
        if not generation_result["passes"]:
            errors.append("LIVE_COEFFICIENT_AUTHORITY_CONTRACT_FAILED")

        launcher_result = {
            "release": module.RELEASE,
            "implementation_hash": cfg.get("implementation_hash"),
            "config_sha256": cfg.get("config_sha256"),
            "stable_project_root": cfg["performance"].get("stable_project_root"),
            "generation_bound_constrained_projection":
                cfg.get("generation_bound_constrained_projection"),
            "predecessor_releases": sorted(predecessor_releases),
        }
    except Exception as exc:
        errors.append("CONFIG_OR_LAUNCHER:%s:%s" % (type(exc).__name__, exc))
    finally:
        if inserted:
            try:
                sys.path.remove(str(root))
            except ValueError:
                pass
        shutil.rmtree(probe_root, ignore_errors=True)

    with tempfile.TemporaryDirectory(prefix="v2487_pycache_") as cache_dir:
        old_env = os.environ.get("PYTHONPYCACHEPREFIX")
        old_prefix = sys.pycache_prefix
        os.environ["PYTHONPYCACHEPREFIX"] = cache_dir
        sys.pycache_prefix = cache_dir
        try:
            compile_pass = compileall.compile_dir(str(root), quiet=1, force=True)
        finally:
            sys.pycache_prefix = old_prefix
            if old_env is None:
                os.environ.pop("PYTHONPYCACHEPREFIX", None)
            else:
                os.environ["PYTHONPYCACHEPREFIX"] = old_env
    if not compile_pass:
        errors.append("COMPILEALL_FAILED")

    test_result = None
    if run_tests:
        with tempfile.TemporaryDirectory(prefix="v2487_testcache_") as cache_dir:
            proc = subprocess.run(
                [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=dict(os.environ, PYTHONPYCACHEPREFIX=cache_dir))
        test_result = {"returncode": proc.returncode, "stdout": proc.stdout,
                       "stderr": proc.stderr}
        if proc.returncode:
            errors.append("PYTEST_FAILED")

    return {
        "schema": "R1_15A2_V2487_PACKAGE_VERIFICATION_V1",
        "status": "PASS" if not errors else "FAILED",
        "release": RELEASE,
        "root": str(root),
        "manifest_sha256": sha256(manifest_path),
        "file_count": len(manifest.get("files", [])),
        "errors": errors,
        "config_validation": config_result,
        "launcher": launcher_result,
        "stable_project_root": root_result,
        "live_coefficient_authority": generation_result,
        "compileall_pass": compile_pass,
        "tests": test_result,
        "real_visum_tested": False,
        "production_ready": False,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--out", default="V2487_VERIFICATION_RESULT.json")
    args = parser.parse_args()
    result = verify(args.root, args.run_tests)
    out = Path(args.out)
    out = out if out.is_absolute() else Path(args.root) / out
    atomic_json(out, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
