#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_12.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    local_modules = {p.stem: p for p in ROOT.glob("*.py")}
    seen: set[Path] = set()
    stack = [ENTRY]
    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    dynamic_imports: list[dict[str, Any]] = []

    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                top = module.split(".")[0]
                if top in local_modules:
                    target = local_modules[top]
                    edges.append({"source": path.name, "target": target.name, "line": getattr(node, "lineno", None)})
                    stack.append(target)
                elif top.startswith("r1_15a2_"):
                    unresolved.append({"source": path.name, "module": module, "line": getattr(node, "lineno", None)})
            if isinstance(node, ast.Call):
                fn = node.func
                name = ""
                if isinstance(fn, ast.Name):
                    name = fn.id
                elif isinstance(fn, ast.Attribute):
                    name = fn.attr
                if name in {"__import__", "import_module"}:
                    dynamic_imports.append({"source": path.name, "line": getattr(node, "lineno", None), "call": name})

    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_9_12.json").read_text(encoding="utf-8"))
    required_paths = {
        cfg["tg_dependency_contract_file"],
        cfg["td"]["long_authority_file"],
        cfg["12d_authority_csv"],
        cfg["12d_city_authority_csv"],
        "helpers/" + cfg["12d_helper_name"],
        "helpers/R1_11D_V1_3_COMPONENT_DIST_BEHAVIOR_DIAGNOSTICS.py",
        cfg["coupled_demand"]["finecdf_td"]["reference_script"],
        cfg["guard_contract_file"],
        cfg["runtime_bundle_manifest"],
    }
    required_paths.update(cfg["supply"]["fixed_input_hashes"].keys())
    missing_paths = sorted(rel for rel in required_paths if not (ROOT / rel).is_file())

    runtime_manifest_path = ROOT / cfg["runtime_bundle_manifest"]
    runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
    runtime_mismatches = []
    for row in runtime_manifest["files"]:
        path = ROOT / row["path"]
        if not path.is_file():
            runtime_mismatches.append({"path": row["path"], "reason": "MISSING"})
        elif path.stat().st_size != row["size"]:
            runtime_mismatches.append({"path": row["path"], "reason": "SIZE"})
        elif sha(path) != row["sha256"]:
            runtime_mismatches.append({"path": row["path"], "reason": "SHA256"})

    core_text = (ROOT / "r1_15a2_core.py").read_text(encoding="utf-8")
    result = {
        "schema": "R1_15A2_V24912_RUNTIME_AUDIT_V1",
        "release": cfg["release"],
        "package_revision": cfg.get("package_revision"),
        "entrypoint": ENTRY.name,
        "reachable_python_file_count": len(seen),
        "reachable_python_files": sorted(p.name for p in seen),
        "import_edge_count": len(edges),
        "unresolved_local_imports": unresolved,
        "dynamic_import_calls": dynamic_imports,
        "late_guard_policy_import_present": "from r1_15a2_guard_policy_v24912 import" in core_text,
        "policy_owner": "r1_15a2_core.py",
        "config_referenced_paths_checked": sorted(required_paths),
        "missing_config_referenced_paths": missing_paths,
        "runtime_manifest_sha256": sha(runtime_manifest_path),
        "runtime_manifest_file_count": runtime_manifest["file_count"],
        "runtime_manifest_mismatches": runtime_mismatches,
        "passes": not unresolved and not missing_paths and not runtime_mismatches and
                  "from r1_15a2_guard_policy_v24912 import" not in core_text,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    if not result["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
