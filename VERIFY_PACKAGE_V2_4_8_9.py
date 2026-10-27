# -*- coding: utf-8 -*-
"""Independent offline verifier for R1 15A2 V2.4.8.9."""
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

RELEASE = "R1_15A2_V2_4_8_9_TD_REALIZATION_STABILIZATION_20261016"
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_9.py"
MANIFEST = "MANIFEST_V2489.json"
V2488 = "R1_15A2_V2_4_8_8_PATH_CACHE_SEMANTIC_COMPAT_20261016"


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
    cfg_result = root_result = td_result = None
    probe_root = Path(tempfile.mkdtemp(prefix="v2489_verify_"))
    try:
        sys.path.insert(0, str(root)); inserted = True
        from r1_15a2_safety_v2489 import validate_v2489_config
        from r1_15a2_overnight_controller_v242 import _td_rows_at_scale
        spec = importlib.util.spec_from_file_location("verify_v2489_launcher", root / LAUNCHER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cfg = module.load_config()
        cfg_result = validate_v2489_config(cfg, root)
        if module.RELEASE != RELEASE or cfg.get("release") != RELEASE:
            errors.append("LAUNCHER_RELEASE_MISMATCH")

        fine = cfg["coupled_demand"]["finecdf_td"]
        if fine.get("realization_backtracking_scales") != [1.0, .5, .25, .125, .0625]:
            errors.append("TD_REALIZATION_SCALES")
        if fine.get("ipf_tolerance_policy") != "UNCHANGED_NEVER_RELAXED_BY_CALIBRATOR":
            errors.append("IPF_TOLERANCE_POLICY")
        compat = cfg["performance"]["persistent_path_cache"][
            "explicit_predecessor_read_compatibility"]
        v2488 = [r for r in compat["predecessors"] if r["source_release"] == V2488]
        if len(v2488) != 1 or len(v2488[0].get("source_path_implementation_files", {})) != 7:
            errors.append("V2488_PREDECESSOR_NOT_PINNED")

        before = {"td_values": [{"component": "WORK", "current_b": 1.0, "current_c": -0.2}]}
        target = [{"component": "WORK", "candidate_b": 1.2, "candidate_c": -0.05}]
        half = _td_rows_at_scale(before, target, 0.5)[0]
        expected_c = -math.sqrt(0.2 * 0.05)
        td_result = {"b": half["candidate_b"], "c": half["candidate_c"],
                     "expected_c": expected_c, "coordinate": half["coordinate_system"]}
        if abs(half["candidate_b"] - 1.1) > 1e-12 or abs(half["candidate_c"] - expected_c) > 1e-12:
            errors.append("TD_LOG_NEG_C_INTERPOLATION")

        project = probe_root / "PROJECT"
        nested = _probe(project / "R1_15A2_V2481_RUNS" / "RUN_A" / "CALIBRATION" /
                        "CHECKPOINTS" / "R1_15A2_V2483_RUNS" / "RUN_B" /
                        "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED.ver")
        layout = module._stable_project_layout(nested)
        new_run = project / "R1_15A2_V2489_RUNS" / "RUN_TEST"
        module._assert_new_run_is_not_nested(new_run, layout["detected_run_roots_nearest_first"])
        root_result = {"project_base": str(layout["project_base"]),
                       "expected": str(project.resolve()),
                       "normalization_depth": len(layout["detected_run_roots_nearest_first"]),
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
        "schema": "R1_15A2_V2489_PACKAGE_VERIFICATION_V1",
        "release": RELEASE,
        "status": "PASS" if not errors else "FAILED",
        "errors": errors,
        "manifest_file_count": len(manifest.get("files", [])),
        "manifest_sha256": sha256(manifest_path),
        "compileall_pass": bool(compile_ok),
        "config_validation": cfg_result,
        "td_coordinate_validation": td_result,
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
