# -*- coding: utf-8 -*-
"""Independent offline verifier for R1 15A2 V2.4.9.4."""
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
from types import SimpleNamespace

RELEASE = "R1_15A2_V2_4_9_4_PATH_EXPORT_RETRY_SEMANTIC_RESTART_20261018"
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_4.py"
MANIFEST = "MANIFEST_V2494.json"
V2493 = "R1_15A2_V2_4_9_3_METHOD_AND_COM_CORRECTIONS_20261018"
V2493_CONFIG_SHA256 = "35b6397a562c9f40cd12e9cb1f429a31ef9120a92a86d0b0bde6a665ed0e974d"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _cal_row(code, observed, model, weight=1.0):
    return {"role": "CALIBRATION", "countlocation_no": code,
            "observed": observed, "model": model, "profile_weight": weight}


def _semantic_snapshot(restart, seed="a"):
    result = {
        name: hashlib.sha256((seed + ":" + name).encode("ascii")).hexdigest()
        for name in restart.SEMANTIC_FIELDS
    }
    result["state_hash"] = hashlib.sha256((seed + ":state").encode("ascii")).hexdigest()
    return result


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
    old_modules = {name: module for name, module in sys.modules.items()
                   if name.startswith("r1_15a2_")}
    cfg_result = None
    method_result = None
    path_retry_result = None
    restart_result = None
    root_result = None
    checkpoint_result = None
    temp = Path(tempfile.mkdtemp(prefix="v2494_verify_"))
    try:
        for name in list(sys.modules):
            if name.startswith("r1_15a2_"):
                del sys.modules[name]
        sys.path.insert(0, str(root)); inserted = True

        import r1_15a2_com_compat as com
        import r1_15a2_core as core
        import r1_15a2_multiblock as mb
        import r1_15a2_restart_v2494 as restart
        import r1_15a2_runtime_v1 as rt
        import r1_15a2_overnight_controller_v240 as overnight
        from r1_15a2_safety_v2494 import (
            V2493_PATH_IMPLEMENTATION_FILES, validate_v2494_config)
        from r1_15a2_supply import SupplyContractError
        from r1_15a2_overnight_controller_v242 import _generation_counts_cfg

        spec = importlib.util.spec_from_file_location("verify_v2494_launcher", root / LAUNCHER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cfg = module.load_config()
        cfg_result = validate_v2494_config(cfg, root)
        if module.RELEASE != RELEASE or cfg.get("release") != RELEASE:
            errors.append("LAUNCHER_RELEASE_MISMATCH")

        # Preserve V2.4.9.3 methodology: weighted GEH, global LONG and signed Generation.
        rows = [_cal_row("A", 100.0, 121.0, 1.0),
                _cal_row("B", 400.0, 361.0, 3.0)]
        metrics = core.csd_metrics(rows)
        expected_geh = (core.geh(121.0, 100.0) +
                        3.0 * core.geh(361.0, 400.0)) / 4.0
        selected_geh = core.csd_objective_value(metrics, cfg)

        long_components = [name for name, reg in mb.COMPONENT_REGISTRY.items()
                           if reg.get("family") == "LONG"]
        summaries = []
        baselines = []
        total = first_num = 0.0
        for i, component in enumerate(long_components, 1):
            volume = float(100 * i); share = float(i) / 10.0
            summaries.append({"component": component, "conditioned_volume": volume,
                              "total_volume": volume,
                              "target_status": "NO_COMPONENT_TARGET"})
            baselines.extend([
                {"component": component, "bin_low": 100.0, "bin_high": 110.0,
                 "share_conditioned": share},
                {"component": component, "bin_low": 110.0, "bin_high": 120.0,
                 "share_conditioned": 1.0 - share},
            ])
            total += volume; first_num += volume * share
        authority = {"authority_id": "GLOBAL_LONG_VERIFY", "component_targets": {},
                     "aggregate_cl_guard": {"bins": [
                         {"bin_low": 100.0, "bin_high": 110.0, "target_share": 0.4},
                         {"bin_low": 110.0, "bin_high": 120.0, "target_share": 0.6},
                     ]}}
        signals = mb.build_td_signals(summaries, [], baselines, authority, cfg)
        composite = signals["LONG_COMPOSITE"]
        collapsed = mb.collapse_td_acceptance_components(long_components, cfg)
        actual_first = next(row["model_share"] for row in composite["model_bins"]
                            if row["bin_low"] == 100.0)

        signed_cfg = json.loads(json.dumps(cfg))
        signed_cfg["salary"]["enabled"] = False
        signed_cfg["min_add_log_step"] = 1.0e-10
        zones = [{"zone_no": z, "NOT_ZAHR": 1, "ZAHR_SUSED": 0,
                  "POP_ZP": 100.0, "AV_INCOME": 1500.0,
                  "ADD_PROD_W": 1.0, "ADD_ATT_W": 1.0,
                  "ADD_PROD_S": 1.0, "ADD_ATT_S": 1.0,
                  "ADD_SALARY": 1.0, "ZAHR_PROD_WORK": 10.0,
                  "ZAHR_ATR_WORK": 8.0, "ZAHR_PROD_SERV": 10.0,
                  "ZAHR_ATR_SERV": 8.0} for z in range(1, 5)]
        a = 0.015; b = math.log(2.0 - math.exp(a))
        def grow(z, role, step):
            return {"zone_no": z, "family": "WORK", "role": role,
                    "log_step": step, "base_margin_volume": 1000.0,
                    "guided_margin_delta": 1000.0 * math.expm1(step),
                    "projected_margin_delta": 1000.0 * math.expm1(step)}
        design = mb.design_generation_candidates(
            [grow(1, "PROD", a), grow(2, "PROD", b),
             grow(3, "ATT", a), grow(4, "ATT", b)], zones, signed_cfg)
        effects = [float(row.get("actual_attr_log_effect", 0.0))
                   for row in design["candidate_rows"]]
        work = design["summary"]["estimated_pa_delta_by_family"]["WORK"]
        early = _generation_counts_cfg(cfg, 1)
        late = _generation_counts_cfg(cfg, 5)
        method_result = {
            "weighted_mean_geh": selected_geh,
            "expected_weighted_mean_geh": expected_geh,
            "profile_sum_role": metrics["profile_sum_role"],
            "long_collapsed": collapsed,
            "long_composite_calibratable": composite.get("calibratable"),
            "long_first_share": actual_first,
            "long_expected_first_share": first_num / total,
            "signed_positive": any(x > 0 for x in effects),
            "signed_negative": any(x < 0 for x in effects),
            "signed_prod_delta": work["estimated_prod_delta"],
            "signed_att_delta": work["estimated_att_delta"],
            "early_stage": early.get("generation_step_stage", {}).get("name"),
            "late_stage": late.get("generation_step_stage", {}).get("name"),
        }
        if abs(selected_geh - expected_geh) > 1e-12:
            errors.append("WEIGHTED_GEH_REGRESSION")
        if collapsed != ["LONG_COMPOSITE"] or composite.get("calibratable") is not True:
            errors.append("LONG_COMPOSITE_REGRESSION")
        if abs(actual_first - first_num / total) > 1e-12:
            errors.append("LONG_COMPOSITE_MIX")
        if not method_result["signed_positive"] or not method_result["signed_negative"]:
            errors.append("SIGNED_GENERATION_REGRESSION")
        if abs(work["estimated_prod_delta"]) > 1e-6 or abs(work["estimated_att_delta"]) > 1e-6:
            errors.append("SIGNED_CENTERING_REGRESSION")

        # Mechanical reproduction of the exact live blocker: the first two calls
        # reject, then the same bounded range succeeds. No page drift is allowed.
        class RetryableCallRejected(Exception):
            def __init__(self):
                super().__init__(com.RPC_E_CALL_REJECTED, "Volany odmitl volani")
                self.hresult = com.RPC_E_CALL_REJECTED
        class TypeInfo:
            def GetTypeAttr(self): return SimpleNamespace(cFuncs=1)
            def GetFuncDesc(self, index): return SimpleNamespace(memid=19, invkind=1)
            def GetNames(self, memid): return ("SaveToArray", "FirstObject", "LastObject")
        class Ole:
            def __init__(self):
                self.calls = []; self.failures = 2
            def GetTypeInfo(self): return TypeInfo()
            def Invoke(self, memid, lcid, kind, as_method, first, last):
                self.calls.append((first, last))
                if self.failures:
                    self.failures -= 1
                    raise RetryableCallRejected()
                return [[1, 2, 1, 1, 101, 201, 301]][first - 1:last]
        class Obj:
            def __init__(self): self._oleobj_ = Ole()
        obj = Obj(); retry_events = []
        retry_policy = dict(cfg["com_resilience"], initial_delay_seconds=0.0,
                            max_delay_seconds=0.0, max_attempts=3)
        exported = list(rt.iter_prt_pathlink_bounded(
            obj, ["OrigZoneNo", "DestZoneNo", "PathIndex", "Index",
                  "LinkNo", "FromNodeNo", "ToNodeNo"],
            page_size=256, require_verified=True, retry_policy=retry_policy,
            retry_progress=retry_events.append))
        active_files = ["r1_15a2_two_mode_v238.py", "r1_15a2_runtime_v1.py",
                        "r1_15a2_live_api_audit.py"]
        raw_invoke_leaks = [name for name in active_files
                            if ".Invoke(" in (root / name).read_text(encoding="utf-8")]
        path_retry_result = {
            "calls": obj._oleobj_.calls,
            "retry_events": retry_events,
            "exported_rows": len(exported),
            "raw_invoke_leaks": raw_invoke_leaks,
            "transient_is_page_size_error": com.is_bounded_page_size_error(
                RetryableCallRejected()),
            "explicit_size_error_is_page_size_error": com.is_bounded_page_size_error(
                RuntimeError("SIMULATED_COM_PAGE_TOO_LARGE")),
        }
        if obj._oleobj_.calls[:3] != [(1, 256), (1, 256), (1, 256)]:
            errors.append("PATH_EXPORT_RETRY_RANGE_DRIFT")
        if raw_invoke_leaks:
            errors.append("RAW_OLE_INVOKE_LEAK:" + ",".join(raw_invoke_leaks))
        if path_retry_result["transient_is_page_size_error"] is not False:
            errors.append("TRANSIENT_PAGE_FALLBACK_REGRESSION")
        if path_retry_result["explicit_size_error_is_page_size_error"] is not True:
            errors.append("SIZE_FALLBACK_REGRESSION")

        # Raw bytes may differ across a manual Save; semantic hashes remain the gate.
        snap = _semantic_snapshot(restart)
        first = restart.build_authority(snap, version_path="A.ver", raw_ver_sha256="1" * 64)
        second = restart.build_authority(snap, version_path="B.ver", raw_ver_sha256="2" * 64)
        same = restart.require_authority_match(first, second)
        changed = dict(snap)
        changed["matrix_hash"] = hashlib.sha256(b"changed").hexdigest()
        mismatch_failed = False
        try:
            restart.require_authority_match(
                first, restart.build_authority(changed, raw_ver_sha256="1" * 64))
        except SupplyContractError:
            mismatch_failed = True
        restart_result = {
            "same_semantics_different_raw_sha_pass": same["passes"],
            "raw_ver_sha_compared": same["raw_ver_sha_compared"],
            "semantic_mismatch_failed_closed": mismatch_failed,
            "semantic_fields": list(restart.SEMANTIC_FIELDS),
            "raw_ver_sha_role": restart.RAW_VER_SHA_ROLE,
        }
        if not same["passes"] or same["raw_ver_sha_compared"] or not mismatch_failed:
            errors.append("SEMANTIC_RESTART_REGRESSION")

        # Checkpoint publication must include the adjacent semantic sidecar.
        class Adapter:
            cfg = {"restart_authority": {"checkpoint_semantic_sidecar": True}}
            def save(self, path):
                path = Path(path); path.write_bytes(b"checkpoint")
                return {"path": str(path), "sha256": sha256(path),
                        "size": path.stat().st_size}
            def snapshot(self): return dict(snap)
        cp = overnight._save_rotating_checkpoint(Adapter(), temp / "run", 0)
        latest = json.loads((temp / "run/LATEST_ACCEPTED_CHECKPOINT.json").read_text())
        sidecar = restart.sidecar_path(Path(cp["path"]))
        checkpoint_result = {
            "sidecar_exists": sidecar.is_file(),
            "latest_has_semantic_authority": "semantic_restart_authority" in latest,
            "raw_sha_restart_acceptance": latest["semantic_restart_authority"].get(
                "raw_ver_sha_used_for_restart_acceptance"),
        }
        if not sidecar.is_file() or "semantic_restart_authority" not in latest or \
                checkpoint_result["raw_sha_restart_acceptance"] is not False:
            errors.append("CHECKPOINT_SEMANTIC_SIDECAR")

        compat = cfg["performance"]["persistent_path_cache"][
            "explicit_predecessor_read_compatibility"]
        v2493 = [row for row in compat["predecessors"]
                 if row.get("source_release") == V2493]
        if len(v2493) != 1 or v2493[0].get("source_config_sha256s") != [V2493_CONFIG_SHA256] or \
                v2493[0].get("source_path_implementation_files") != V2493_PATH_IMPLEMENTATION_FILES:
            errors.append("V2493_PREDECESSOR_NOT_PINNED")

        project = temp / "PROJECT"
        nested = project / "R1_15A2_V2493_RUNS/RUN_A/CALIBRATION/CHECKPOINTS/ACCEPTED.ver"
        nested.parent.mkdir(parents=True); nested.write_bytes(b"probe")
        layout = module._stable_project_layout(nested)
        new_run = project / "R1_15A2_V2494_RUNS/RUN_TEST"
        module._assert_new_run_is_not_nested(
            new_run, layout["detected_run_roots_nearest_first"])
        root_result = {"project_base": str(layout["project_base"]),
                       "expected": str(project.resolve()),
                       "new_run_postcondition": True}
        if layout["project_base"] != project.resolve():
            errors.append("PROJECT_ROOT_NORMALIZATION")
    except Exception as exc:
        errors.append("CONFIG_OR_MECHANICAL_VERIFY:%s:%s" % (type(exc).__name__, exc))
    finally:
        if inserted:
            try: sys.path.remove(str(root))
            except ValueError: pass
        for name in list(sys.modules):
            if name.startswith("r1_15a2_"):
                del sys.modules[name]
        sys.modules.update(old_modules)
        shutil.rmtree(temp, ignore_errors=True)

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
        "schema": "R1_15A2_V2494_PACKAGE_VERIFICATION_V1",
        "release": RELEASE,
        "status": "PASS" if not errors else "FAILED",
        "errors": errors,
        "manifest_file_count": len(manifest.get("files", [])),
        "manifest_sha256": sha256(manifest_path),
        "compileall_pass": bool(compile_ok),
        "config_validation": cfg_result,
        "methodology_preservation": method_result,
        "path_export_retry_validation": path_retry_result,
        "semantic_restart_validation": restart_result,
        "checkpoint_sidecar_validation": checkpoint_result,
        "run_root_validation": root_result,
        "pytest": test_result,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "real_visum_tested": False,
        "production_ready": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = verify(args.root, args.run_tests)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
