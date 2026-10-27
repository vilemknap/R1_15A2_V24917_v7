# -*- coding: utf-8 -*-
"""Independent verifier for R1 15A2 V2.4.8.3 cache compatibility hotfix."""
from __future__ import annotations
import argparse, compileall, hashlib, importlib.util, json, os, subprocess, sys, time
from pathlib import Path

RELEASE = "R1_15A2_V2_4_8_3_CACHE_COMPAT_HOTFIX_20261016"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path); tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def verify(root, run_tests=False):
    root = Path(root).resolve(); started = time.monotonic(); errors = []
    manifest_path = root / "MANIFEST_V2483.json"
    if not manifest_path.is_file():
        return {"status": "FAILED", "errors": ["MANIFEST_V2483.json missing"]}
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

    config_result = launcher_result = None
    try:
        sys.path.insert(0, str(root))
        from r1_15a2_safety_v2483 import validate_v2483_config
        spec = importlib.util.spec_from_file_location(
            "verify_v2483_launcher",
            root / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_3.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cfg = module.load_config(); config_result = validate_v2483_config(cfg, root)
        if cfg.get("release") != RELEASE or module.RELEASE != RELEASE:
            errors.append("LAUNCHER_RELEASE_MISMATCH")
        zero = cfg.get("two_mode", {}).get("zero_share_residual_policy", {})
        compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
            "explicit_predecessor_read_compatibility", {})
        if zero.get("enabled") is not True or float(zero.get("max_dseg_relative_volume", -1)) != 0.01:
            errors.append("ZERO_SHARE_POLICY_NOT_LOCKED")
        if compat.get("enabled") is not True or compat.get("target_release") != RELEASE:
            errors.append("PREDECESSOR_CACHE_COMPATIBILITY_NOT_LOCKED")
        launcher_result = {
            "release": module.RELEASE,
            "implementation_hash": cfg.get("implementation_hash"),
            "config_sha256": cfg.get("config_sha256"),
            "zero_share_policy": zero,
            "predecessor_cache_compatibility": compat,
        }
    except Exception as exc:
        errors.append("CONFIG_OR_LAUNCHER:%s:%s" % (type(exc).__name__, exc))

    predecessor_result = None
    try:
        predecessor_result = json.loads((root / "V2483_PREDECESSOR_CACHE_COMPATIBILITY_VERIFICATION.json").read_text(encoding="utf-8"))
        if predecessor_result.get("status") != "PASS":
            errors.append("PREDECESSOR_COMPATIBILITY_VERIFICATION_FAILED")
    except Exception as exc:
        errors.append("PREDECESSOR_COMPATIBILITY_VERIFICATION:%s:%s" % (type(exc).__name__, exc))

    pycache = Path(os.environ.get("PYTHONPYCACHEPREFIX", root / ".verify_pycache"))
    old_env = os.environ.get("PYTHONPYCACHEPREFIX"); old_prefix = sys.pycache_prefix
    os.environ["PYTHONPYCACHEPREFIX"] = str(pycache); sys.pycache_prefix = str(pycache)
    try:
        compile_pass = compileall.compile_dir(str(root), quiet=1, force=True)
    finally:
        sys.pycache_prefix = old_prefix
        if old_env is None: os.environ.pop("PYTHONPYCACHEPREFIX", None)
        else: os.environ["PYTHONPYCACHEPREFIX"] = old_env
    if not compile_pass:
        errors.append("COMPILEALL_FAILED")

    test_result = None
    if run_tests:
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
            cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=dict(os.environ, PYTHONPYCACHEPREFIX=str(pycache)))
        test_result = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        if proc.returncode:
            errors.append("PYTEST_FAILED")

    return {
        "schema": "R1_15A2_V2483_PACKAGE_VERIFICATION_V1",
        "status": "PASS" if not errors else "FAILED",
        "release": RELEASE,
        "root": str(root),
        "manifest_sha256": sha256(manifest_path),
        "file_count": len(manifest.get("files", [])),
        "errors": errors,
        "config_validation": config_result,
        "launcher": launcher_result,
        "predecessor_compatibility_verification": predecessor_result,
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
    parser.add_argument("--out", default="V2483_VERIFICATION_RESULT.json")
    args = parser.parse_args()
    result = verify(args.root, args.run_tests)
    out = Path(args.out); out = out if out.is_absolute() else Path(args.root) / out
    atomic_json(out, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
