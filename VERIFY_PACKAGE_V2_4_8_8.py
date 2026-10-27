# -*- coding: utf-8 -*-
"""Independent offline verifier for R1 15A2 V2.4.8.8."""
from __future__ import annotations

import argparse
import compileall
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RELEASE = "R1_15A2_V2_4_8_8_PATH_CACHE_SEMANTIC_COMPAT_20261016"
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_8.py"
MANIFEST = "MANIFEST_V2488.json"


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
            errors.append("MISSING:" + row["path"])
            continue
        if path.stat().st_size != int(row["bytes"]):
            errors.append("SIZE:" + row["path"])
            continue
        if sha256(path) != row["sha256"]:
            errors.append("SHA256:" + row["path"])

    inserted = False
    cfg_result = root_result = None
    probe_root = Path(tempfile.mkdtemp(prefix="v2488_verify_"))
    try:
        sys.path.insert(0, str(root)); inserted = True
        from r1_15a2_safety_v2488 import validate_v2488_config
        spec = importlib.util.spec_from_file_location("verify_v2488_launcher", root / LAUNCHER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cfg = module.load_config()
        cfg_result = validate_v2488_config(cfg, root)
        if module.RELEASE != RELEASE or cfg.get("release") != RELEASE:
            errors.append("LAUNCHER_RELEASE_MISMATCH")

        compat = cfg["performance"]["persistent_path_cache"][
            "explicit_predecessor_read_compatibility"]
        releases = {r["source_release"] for r in compat["predecessors"]}
        required = {
            "R1_15A2_V2_4_8_PERSISTENT_PATH_CACHE_20261016",
            "R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016",
            "R1_15A2_V2_4_8_2_ZERO_VOLUME_SUPPORT_HOTFIX_20261016",
            "R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016",
            "R1_15A2_V2_4_8_3_CACHE_COMPAT_HOTFIX_20261016",
            "R1_15A2_V2_4_8_4_RUN_ROOT_HOTFIX_20261016",
            "R1_15A2_V2_4_8_5_STABLE_PROJECT_ROOT_20261016",
            "R1_15A2_V2_4_8_5_GENERATION_SATURATION_HOTFIX_20261016",
            "R1_15A2_V2_4_8_6_UNIFIED_ROOT_SATURATION_20261016",
            "R1_15A2_V2_4_8_7_LIVE_COEFFICIENT_AUTHORITY_20261016",
        }
        if releases != required:
            errors.append("PREDECESSOR_SET_NOT_LOCKED")
        v2482 = next((r for r in compat["predecessors"] if r["source_release"] ==
                      "R1_15A2_V2_4_8_2_ZERO_VOLUME_SUPPORT_HOTFIX_20261016"), None)
        if not v2482 or v2482.get("source_config_sha256s") != [
                "339dc5d273e780e2d6edf0785353483a7e1a03ed459875feacc15cb17c33d6ec"]:
            errors.append("ACTUAL_V2482_ZERO_VOLUME_IDENTITY_NOT_PINNED")
        if compat.get("incompatible_candidate_policy") != \
                "REJECT_CACHE_AS_PERFORMANCE_MISS_THEN_LEGACY_OR_FRESH_ENUMERATION":
            errors.append("CACHE_FALLBACK_POLICY")

        project = probe_root / "PROJECT"
        nested = _probe(project / "R1_15A2_V2481_RUNS" / "RUN_A" / "CALIBRATION" /
                        "CHECKPOINTS" / "R1_15A2_V2483_RUNS" / "RUN_B" /
                        "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED.ver")
        layout = module._stable_project_layout(nested)
        new_run = project / "R1_15A2_V2488_RUNS" / "RUN_TEST"
        module._assert_new_run_is_not_nested(
            new_run, layout["detected_run_roots_nearest_first"])
        root_result = {
            "project_base": str(layout["project_base"]),
            "expected": str(project.resolve()),
            "normalization_depth": len(layout["detected_run_roots_nearest_first"]),
            "new_run_postcondition": True,
        }
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
        test_result = {
            "returncode": proc.returncode,
            "tail": lines[-20:],
        }
        if proc.returncode != 0:
            errors.append("PYTEST")

    return {
        "schema": "R1_15A2_V2488_PACKAGE_VERIFICATION_V1",
        "release": RELEASE,
        "status": "PASS" if not errors else "FAILED",
        "errors": errors,
        "manifest_file_count": len(manifest.get("files", [])),
        "manifest_sha256": sha256(manifest_path),
        "compileall_pass": bool(compile_ok),
        "config_validation": cfg_result,
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
