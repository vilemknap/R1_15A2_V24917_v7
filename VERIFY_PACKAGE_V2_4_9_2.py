# -*- coding: utf-8 -*-
"""Independent offline verifier for R1 15A2 V2.4.9.2."""
from __future__ import annotations

import argparse
import compileall
import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RELEASE = "R1_15A2_V2_4_9_2_SIGNED_GENERATION_REFINEMENT_20261018"
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_2.py"
MANIFEST = "MANIFEST_V2492.json"
V2490 = "R1_15A2_V2_4_9_0_TD_SOFT_REFERENCE_20261017"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"probe")
    return path


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
            errors.append("MISSING:" + row["path"]); continue
        if path.stat().st_size != int(row["bytes"]):
            errors.append("SIZE:" + row["path"]); continue
        if sha256(path) != row["sha256"]:
            errors.append("SHA256:" + row["path"])

    inserted = False
    cfg_result = root_result = signed_result = None
    probe_root = Path(tempfile.mkdtemp(prefix="v2492_verify_"))
    try:
        sys.path.insert(0, str(root)); inserted = True
        from r1_15a2_safety_v2492 import validate_v2492_config
        import r1_15a2_multiblock as mb
        from r1_15a2_overnight_controller_v242 import _generation_counts_cfg
        spec = importlib.util.spec_from_file_location("verify_v2492_launcher", root / LAUNCHER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cfg = module.load_config()
        cfg_result = validate_v2492_config(cfg, root)
        if module.RELEASE != RELEASE or cfg.get("release") != RELEASE:
            errors.append("LAUNCHER_RELEASE_MISMATCH")
        if cfg.get("guidance_mode") != "SIGNED" or cfg.get("allow_signed_apply") is not True:
            errors.append("SIGNED_GUIDANCE_DISABLED")

        # Mechanical signed redistribution proof with zero total volume change.
        test_cfg = json.loads(json.dumps(cfg))
        test_cfg["salary"]["enabled"] = False
        test_cfg["min_add_log_step"] = 1.0e-10
        zones = []
        for z in range(1, 5):
            zones.append({
                "zone_no": z, "NOT_ZAHR": 1, "ZAHR_SUSED": 0, "POP_ZP": 100.0,
                "AV_INCOME": 1500.0, "ADD_PROD_W": 1.0, "ADD_ATT_W": 1.0,
                "ADD_PROD_S": 1.0, "ADD_ATT_S": 1.0, "ADD_SALARY": 1.0,
                "ZAHR_PROD_WORK": 10.0, "ZAHR_ATR_WORK": 8.0,
                "ZAHR_PROD_SERV": 10.0, "ZAHR_ATR_SERV": 8.0,
            })
        a = 0.015; b = math.log(2.0 - math.exp(a))
        def row(z, role, step):
            return {"zone_no": z, "family": "WORK", "role": role,
                    "log_step": step, "base_margin_volume": 1000.0,
                    "guided_margin_delta": 1000.0 * math.expm1(step),
                    "projected_margin_delta": 1000.0 * math.expm1(step)}
        design = mb.design_generation_candidates(
            [row(1,"PROD",a), row(2,"PROD",b), row(3,"ATT",a), row(4,"ATT",b)],
            zones, test_cfg)
        effects = [float(r.get("actual_attr_log_effect", 0.0))
                   for r in design["candidate_rows"]]
        work = design["summary"]["estimated_pa_delta_by_family"]["WORK"]
        signed_result = {
            "positive_effect_present": any(x > 0 for x in effects),
            "negative_effect_present": any(x < 0 for x in effects),
            "prod_delta": work["estimated_prod_delta"],
            "att_delta": work["estimated_att_delta"],
            "pa_gap": work["estimated_abs_gap"],
            "audit_mode": design["summary"]["signed_generation_refinement"]["mode"],
        }
        if not signed_result["positive_effect_present"] or not signed_result["negative_effect_present"]:
            errors.append("SIGNED_BIDIRECTIONAL_EFFECT_MISSING")
        if abs(float(work["estimated_prod_delta"])) > 1e-6 or \
           abs(float(work["estimated_att_delta"])) > 1e-6 or \
           float(work["estimated_abs_gap"]) > 1e-6:
            errors.append("SIGNED_ZERO_TOTAL_CENTERING_FAILED")

        early = _generation_counts_cfg(cfg, 1)
        late = _generation_counts_cfg(cfg, 5)
        if early["max_add_log_up"] != 0.06 or early["max_add_log_down"] != 0.06:
            errors.append("SIGNED_EARLY_STAGE")
        if late["max_add_log_up"] != 0.02 or late["max_add_log_down"] != 0.02 or \
           late["generation_signed_refinement"]["max_family_global_log_up"] != 0.005:
            errors.append("DISTRIBUTION_FOCUS_STAGE")

        compat = cfg["performance"]["persistent_path_cache"][
            "explicit_predecessor_read_compatibility"]
        v2490 = [r for r in compat["predecessors"] if r["source_release"] == V2490]
        if len(v2490) != 1 or len(v2490[0].get("source_path_implementation_files", {})) != 7:
            errors.append("V2490_PREDECESSOR_NOT_PINNED")

        if cfg["td_soft_reference_policy"].get("exact_curve_match_required") is not False:
            errors.append("TD_SOFT_REFERENCE_LOST")
        if cfg["coupled_demand"]["finecdf_td"].get("ipf_tolerance_policy") != \
                "UNCHANGED_NEVER_RELAXED_BY_CALIBRATOR":
            errors.append("IPF_TOLERANCE_POLICY")

        project = probe_root / "PROJECT"
        nested = _probe(project / "R1_15A2_V2489_RUNS" / "RUN_A" / "CALIBRATION" /
                        "CHECKPOINTS" / "ACCEPTED.ver")
        layout = module._stable_project_layout(nested)
        new_run = project / "R1_15A2_V2492_RUNS" / "RUN_TEST"
        module._assert_new_run_is_not_nested(new_run,
                                             layout["detected_run_roots_nearest_first"])
        root_result = {"project_base": str(layout["project_base"]),
                       "expected": str(project.resolve()),
                       "new_run_postcondition": True}
        if layout["project_base"] != project.resolve():
            errors.append("PROJECT_ROOT_NORMALIZATION")
    except Exception as exc:
        errors.append("CONFIG_OR_LAUNCHER:%s:%s" % (type(exc).__name__, exc))
    finally:
        if inserted:
            try: sys.path.remove(str(root))
            except ValueError: pass
        shutil.rmtree(probe_root, ignore_errors=True)

    compile_ok = compileall.compile_dir(str(root), quiet=1, force=True)
    if not compile_ok:
        errors.append("COMPILEALL")

    test_result = None
    if run_tests:
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=str(root),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace")
        lines = proc.stdout.splitlines()
        test_result = {"returncode": proc.returncode, "tail": lines[-20:]}
        if proc.returncode != 0:
            errors.append("PYTEST")

    return {
        "schema": "R1_15A2_V2492_PACKAGE_VERIFICATION_V1",
        "release": RELEASE,
        "status": "PASS" if not errors else "FAILED",
        "errors": errors,
        "manifest_file_count": len(manifest.get("files", [])),
        "manifest_sha256": sha256(manifest_path),
        "compileall_pass": bool(compile_ok),
        "config_validation": cfg_result,
        "signed_generation_validation": signed_result,
        "run_root_validation": root_result,
        "pytest": test_result,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "real_visum_tested": False,
        "production_ready": False,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--run-tests", action="store_true")
    ap.add_argument("--output")
    args = ap.parse_args()
    result = verify(args.root, args.run_tests)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
