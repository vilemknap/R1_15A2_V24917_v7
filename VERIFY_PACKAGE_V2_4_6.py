# -*- coding: utf-8 -*-
"""Independent verifier for the R1 15A2 V2.4.6 delivery."""
from __future__ import annotations

import argparse
import compileall
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def verify(root, run_tests=False):
    root = Path(root).resolve()
    started = time.monotonic()
    errors = []
    manifest_path = root / "MANIFEST_V246.json"
    if not manifest_path.is_file():
        return {"status": "FAILED", "errors": ["MANIFEST_V246.json missing"]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
    config_result = None
    launcher_result = None
    try:
        sys.path.insert(0, str(root))
        from r1_15a2_safety_v246 import validate_v246_config
        cfg = json.loads((root / "R1_15A2_CONFIG_V2_4_6.json").read_text(encoding="utf-8"))
        config_result = validate_v246_config(cfg, root)
        spec = importlib.util.spec_from_file_location(
            "verify_v246_launcher", root / "R1_15A2_FULL_OVERNIGHT_ADAPTIVE_V2_4_6.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded = module.load_config()
        launcher_result = {
            "release": loaded.get("release"),
            "implementation_hash": loaded.get("implementation_hash"),
            "implementation_file_count": len(loaded.get("implementation_files", {})),
        }
    except Exception as exc:
        errors.append("CONFIG_OR_LAUNCHER:%s:%s" % (type(exc).__name__, exc))
    compile_pass = compileall.compile_dir(str(root), quiet=1, force=True)
    if not compile_pass:
        errors.append("COMPILEALL_FAILED")
    test_result = None
    if run_tests:
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
            cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        test_result = {"returncode": proc.returncode,
                       "stdout": proc.stdout, "stderr": proc.stderr}
        if proc.returncode:
            errors.append("PYTEST_FAILED")
    result = {
        "schema": "R1_15A2_V246_PACKAGE_VERIFICATION_V1",
        "status": "PASS" if not errors else "FAILED",
        "root": str(root),
        "manifest_sha256": sha256(manifest_path),
        "file_count": len(manifest.get("files", [])),
        "errors": errors,
        "config_validation": config_result,
        "launcher": launcher_result,
        "compileall_pass": compile_pass,
        "tests": test_result,
        "real_visum_tested": False,
        "elapsed_seconds": round(time.monotonic()-started, 3),
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--out", default="V246_VERIFICATION_RESULT.json")
    args = parser.parse_args()
    result = verify(args.root, args.run_tests)
    out = Path(args.out)
    if not out.is_absolute():
        out = Path(args.root) / out
    atomic_json(out, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
