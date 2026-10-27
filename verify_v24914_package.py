#!/usr/bin/env python3
"""Independent offline verifier for the complete V24914 deployment tree."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "MANIFEST_V24914.json"
RELEASE = "R1_15A2_V2_4_9_14_DEMAND_CONTINUATION_SUPPLY_READY_20261019"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(code: str) -> None:
    raise SystemExit(code)


def main() -> int:
    if not MANIFEST.is_file():
        fail("V24914_PACKAGE_MANIFEST_MISSING")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema") != "R1_15A2_V24914_PACKAGE_MANIFEST_V1":
        fail("V24914_PACKAGE_MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("release") != RELEASE:
        fail("V24914_PACKAGE_RELEASE_MISMATCH")
    failures = []
    for row in manifest.get("files", []):
        rel = row.get("path")
        path = ROOT / str(rel)
        if not path.is_file():
            failures.append({"path": rel, "reason": "MISSING"})
            continue
        if path.stat().st_size != int(row.get("size", -1)):
            failures.append({"path": rel, "reason": "SIZE_MISMATCH"})
            continue
        if sha256(path) != row.get("sha256"):
            failures.append({"path": rel, "reason": "SHA256_MISMATCH"})
    if failures:
        fail("V24914_PACKAGE_MANIFEST_INVALID:" + json.dumps(failures, sort_keys=True))

    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "v24914_verify_launcher",
        ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_14.py",
    )
    if spec is None or spec.loader is None:
        fail("V24914_LAUNCHER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cfg = module.load_config()
    from r1_15a2_safety_v24914 import validate_v24914_config, validate_v24914_runtime_bundle
    config_result = validate_v24914_config(cfg, ROOT)
    runtime_result = validate_v24914_runtime_bundle(cfg, ROOT)
    result = {
        "schema": "R1_15A2_V24914_PACKAGE_VERIFICATION_V1",
        "release": RELEASE,
        "passes": True,
        "package_files_checked": len(manifest.get("files", [])),
        "runtime_files_checked": runtime_result.get("files_checked"),
        "accepted_count_start": config_result.get("accepted_count_start"),
        "next_outer_cycle": config_result.get("next_outer_cycle"),
        "supply_policy_preserved": runtime_result.get("supply_policy_preserved"),
        "real_visum_tested": False,
        "production_ready": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
