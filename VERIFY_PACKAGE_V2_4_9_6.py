# -*- coding: utf-8 -*-
"""Independent offline verifier for R1 15A2 V2.4.9.6."""
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

RELEASE = "R1_15A2_V2_4_9_6_EARLY_EXPLORATION_PARETO_ACCEPTANCE_20261018"
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_6.py"
MANIFEST = "MANIFEST_V2496.json"
V2495 = "R1_15A2_V2_4_9_5_GEH20_HYSTERESIS_SEVERITY_BUDGET_20261018"
V2495_CONFIG_SHA256 = "59bfa7013a8f141c559c4232031e1c0fb6979da4f54cec976bc05211be1d4e7c"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _cal_row(code, observed, model, weight=1.0):
    return {"role": "CALIBRATION", "countlocation_no": code,
            "observed": observed, "model": model, "profile_weight": weight}


def _model_for_geh(observed, target_geh):
    o = float(observed); g = float(target_geh)
    d = (g * g + math.sqrt(g ** 4 + 16.0 * g * g * o)) / 4.0
    return o + d


def _geh_row(code, target_geh, observed=1000.0, weight=1.0):
    return _cal_row(code, observed, _model_for_geh(observed, target_geh), weight)


def _semantic_snapshot(restart, seed="a"):
    result = {
        name: hashlib.sha256((seed + ":" + name).encode("ascii")).hexdigest()
        for name in restart.SEMANTIC_FIELDS
    }
    result["state_hash"] = hashlib.sha256((seed + ":state").encode("ascii")).hexdigest()
    return result


def _td_summary(obj):
    return {"component_dist_summary_rows": [{
        "component": "WORK_E_C", "family": "WORK",
        "target_status": "ACTIVE_COMPONENT_DIST_TARGET",
        "mean_model_conditioned": 10.0, "mean_target": 10.0,
        "l1_distance_half": float(obj), "rmse_share": 0.0,
    }]}


def _td_signal(obj):
    return {"WORK_E_C": {
        "component": "WORK_E_C", "family": "WORK", "calibratable": True,
        "l1_half": float(obj), "rmse_share": 0.0,
        "mean_target": 10.0, "mean_delta": 0.0, "conditioned_volume": 1000.0,
    }}


def _bulk_rows(before_geh, after_geh, n=100):
    return ([_geh_row("S%d" % i, before_geh) for i in range(n)],
            [_geh_row("S%d" % i, after_geh) for i in range(n)])


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
    cfg_result = methodology_result = early_result = None
    td_result = best_result = path_retry_result = restart_result = root_result = None
    temp = Path(tempfile.mkdtemp(prefix="v2496_verify_"))
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
        import r1_15a2_overnight_controller_v240 as ctl240
        import r1_15a2_overnight_controller_v242 as ctl242
        from r1_15a2_safety_v2496 import (
            V2495_PATH_IMPLEMENTATION_FILES, validate_v2496_config)
        from r1_15a2_supply import SupplyContractError

        spec = importlib.util.spec_from_file_location("verify_v2496_launcher", root / LAUNCHER)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        cfg = launcher.load_config()
        cfg_result = validate_v2496_config(cfg, root)
        if launcher.RELEASE != RELEASE or cfg.get("release") != RELEASE:
            errors.append("LAUNCHER_RELEASE_MISMATCH")

        master_spec = importlib.util.spec_from_file_location(
            "verify_v2496_master", root / "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py")
        master = importlib.util.module_from_spec(master_spec)
        master_spec.loader.exec_module(master)

        # Preserve weighted GEH, diagnostic profile sums, LONG_COMPOSITE and signed TG.
        rows = [_cal_row("A", 100.0, 121.0, 1.0),
                _cal_row("B", 400.0, 361.0, 3.0)]
        metrics = core.csd_metrics(rows)
        expected_geh = (core.geh(121.0, 100.0) +
                        3.0 * core.geh(361.0, 400.0)) / 4.0
        selected_geh = core.csd_objective_value(metrics, cfg)

        long_components = [name for name, reg in mb.COMPONENT_REGISTRY.items()
                           if reg.get("family") == "LONG"]
        summaries = []; baselines = []; total = first_num = 0.0
        for i, component in enumerate(long_components, 1):
            volume = float(100 * i); share = float(i) / 10.0
            summaries.append({"component": component, "conditioned_volume": volume,
                              "total_volume": volume, "target_status": "NO_COMPONENT_TARGET"})
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
        methodology_result = {
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
        }
        if abs(selected_geh - expected_geh) > 1e-12:
            errors.append("WEIGHTED_GEH_REGRESSION")
        if collapsed != ["LONG_COMPOSITE"] or composite.get("calibratable") is not True:
            errors.append("LONG_COMPOSITE_REGRESSION")
        if abs(actual_first - first_num / total) > 1e-12:
            errors.append("LONG_COMPOSITE_MIX")
        if not methodology_result["signed_positive"] or not methodology_result["signed_negative"]:
            errors.append("SIGNED_GENERATION_REGRESSION")
        if abs(work["estimated_prod_delta"]) > 1e-6 or abs(work["estimated_att_delta"]) > 1e-6:
            errors.append("SIGNED_CENTERING_REGRESSION")

        # Early Generation: any true improvement, nonmonotonic severity trade-off,
        # soft GEH20/30, warning GEH35 and hard GEH40.
        gen_cfg = json.loads(json.dumps(cfg)); gen_cfg["runtime_acceptance_outer_cycle"] = 3
        gen_cfg["runtime_acceptance_scope"] = "GENERATION"
        positive = core.acceptance_decision(
            [_geh_row("DRIVER", 50.0), _geh_row("EDGE", 19.91)],
            [_geh_row("DRIVER", 49.80), _geh_row("EDGE", 20.08)],
            {}, {}, gen_cfg, "GENERATION")
        nonmono_before = [_geh_row("HIGH", 50.0)] + [_geh_row("M%d" % i, 20.0) for i in range(10)]
        nonmono_after = [_geh_row("HIGH", 40.0)] + [_geh_row("M%d" % i, 21.1) for i in range(10)]
        nonmono = core.acceptance_decision(nonmono_before, nonmono_after, {}, {}, gen_cfg, "GENERATION")
        over = core.acceptance_decision(
            nonmono_before,
            [_geh_row("HIGH", 40.0)] + [_geh_row("M%d" % i, 22.0) for i in range(10)],
            {}, {}, gen_cfg, "GENERATION")
        soft = core.severity_transition_guard(
            [_geh_row("A", 19.0), _geh_row("B", 29.0), _geh_row("C", 34.0)],
            [_geh_row("A", 24.0), _geh_row("B", 32.0), _geh_row("C", 36.0)],
            gen_cfg, "GENERATION")
        hard40 = core.severity_transition_guard(
            [_geh_row("X", 39.0)], [_geh_row("X", 40.1)], gen_cfg, "GENERATION")
        protected = core.protected_profile_guard(
            [_geh_row("P", 4.0)], [_geh_row("P", 20.0)], gen_cfg, "GENERATION")
        cycle9_cfg = json.loads(json.dumps(cfg)); cycle9_cfg["runtime_acceptance_outer_cycle"] = 9
        cycle9_cfg["runtime_acceptance_scope"] = "GENERATION"
        cycle9 = core.acceptance_decision(
            [_geh_row("D", 50.0), _geh_row("E", 19.91)],
            [_geh_row("D", 49.99), _geh_row("E", 20.08)],
            {}, {}, cycle9_cfg, "GENERATION")
        early_result = {
            "positive_accepted": positive.get("accepted"),
            "positive_path": positive.get("acceptance_path"),
            "nonmonotonic_accepted": nonmono.get("accepted"),
            "nonmonotonic_flag": nonmono.get("exploration_nonmonotonic_accepted"),
            "over_two_percent_rejected": not over.get("accepted", True),
            "geh20_30_soft_pass": soft.get("passes"),
            "geh35_warning_count": len(soft.get("new_geh35_warning", [])),
            "geh40_rejected": not hard40.get("passes", True),
            "protected_catastrophic_rejected": not protected.get("passes", True),
            "cycle9_inherited": cycle9.get("active_acceptance_stage") == "INHERITED",
            "cycle9_tiny_move_rejected": not cycle9.get("accepted", True),
        }
        if not positive.get("accepted") or positive.get("acceptance_path") != "EARLY_EXPLORATION_ANY_POSITIVE_WEIGHTED_GEH":
            errors.append("EARLY_GENERATION_POSITIVE_PATH")
        if not nonmono.get("accepted") or nonmono.get("exploration_nonmonotonic_accepted") is not True:
            errors.append("EARLY_GENERATION_NONMONOTONIC_PATH")
        if over.get("accepted"):
            errors.append("EARLY_GENERATION_TWO_PERCENT_CAP")
        if not soft.get("passes") or len(soft.get("new_geh35_warning", [])) != 1:
            errors.append("EARLY_SEVERITY_SOFT_WARNING")
        if hard40.get("passes") or protected.get("passes"):
            errors.append("EARLY_CATASTROPHIC_GUARD")
        if cycle9.get("active_acceptance_stage") != "INHERITED" or cycle9.get("accepted"):
            errors.append("V2495_FALLBACK_AFTER_CYCLE8")

        # Early TD: reproduce the live-like 5.5% / <1% case and scale-0.25-like
        # large benefit, then prove benefit/cost and 5% CAL caps still reject.
        td_cfg = json.loads(json.dumps(cfg)); td_cfg["runtime_acceptance_outer_cycle"] = 3
        td_cfg["runtime_acceptance_scope"] = "TD"
        before, after = _bulk_rows(50.0, 50.30)
        before += [_geh_row("C20", 19.82), _geh_row("C30", 29.47)]
        after += [_geh_row("C20", 21.01), _geh_row("C30", 30.17)]
        live_like = master.td_acceptance_decision(
            before, after, _td_summary(0.20), _td_summary(0.189),
            _td_signal(0.20), _td_signal(0.189), ["WORK_E_C"], td_cfg)
        before2, after2 = _bulk_rows(50.0, 51.30)
        before2 += [_geh_row("N%d" % i, 28.0 + 0.1 * i) for i in range(7)]
        after2 += [_geh_row("N%d" % i, 30.2 + 0.1 * i) for i in range(7)]
        quarter = master.td_acceptance_decision(
            before2, after2, _td_summary(0.20), _td_summary(0.1568),
            _td_signal(0.20), _td_signal(0.1568), ["WORK_E_C"], td_cfg)
        low_b, low_a = _bulk_rows(50.0, 50.5)
        low_ratio = master.td_acceptance_decision(
            low_b, low_a, _td_summary(0.20), _td_summary(0.198),
            _td_signal(0.20), _td_signal(0.198), ["WORK_E_C"], td_cfg)
        cost_b, cost_a = _bulk_rows(50.0, 53.1)
        too_costly = master.td_acceptance_decision(
            cost_b, cost_a, _td_summary(0.20), _td_summary(0.15),
            _td_signal(0.20), _td_signal(0.15), ["WORK_E_C"], td_cfg)
        td_result = {
            "live_like_accepted": live_like.get("accepted"),
            "live_like_improvement": live_like.get("selected_relative_improvement"),
            "live_like_cal_degradation": live_like.get("cal_csd_relative_degradation"),
            "live_like_benefit_cost": live_like.get("benefit_cost_ratio"),
            "quarter_like_accepted": quarter.get("accepted"),
            "quarter_like_improvement": quarter.get("selected_relative_improvement"),
            "quarter_like_cal_degradation": quarter.get("cal_csd_relative_degradation"),
            "low_ratio_reasons": low_ratio.get("reasons"),
            "too_costly_reasons": too_costly.get("reasons"),
        }
        if not live_like.get("accepted") or not quarter.get("accepted"):
            errors.append("EARLY_TD_PARETO_ACCEPTANCE")
        if "TD_BENEFIT_COST_RATIO_TOO_LOW" not in low_ratio.get("reasons", []):
            errors.append("EARLY_TD_BENEFIT_COST_GUARD")
        if "CAL_CSD_DEGRADED_TOO_MUCH" not in too_costly.get("reasons", []):
            errors.append("EARLY_TD_FIVE_PERCENT_CAP")

        # Dedicated immutable best-so-far checkpoint.
        snap = _semantic_snapshot(restart)
        source = temp / "source.ver"; source.write_bytes(b"best checkpoint probe")
        source_cp = {"path": str(source), "sha256": sha256(source), "size": source.stat().st_size}
        class BestAdapter:
            cfg = {"restart_authority": {"checkpoint_semantic_sidecar": True}}
        best = ctl242._publish_best_so_far_checkpoint(
            BestAdapter(), temp / "run", source_cp, snap, {"total": 0.95}, 2)
        pointer = json.loads((temp / "run/BEST_SO_FAR_CHECKPOINT.json").read_text(encoding="utf-8"))
        best_path = Path(best["checkpoint"]["path"])
        sidecar_path = best_path.with_name(best_path.name + ".semantic.json")
        best_result = {
            "best_checkpoint_exists": best_path.is_file(),
            "best_pointer_readback": pointer == best,
            "semantic_sidecar_exists": sidecar_path.is_file(),
            "source_and_best_sha_match": sha256(best_path) == source_cp["sha256"],
        }
        if not all(best_result.values()):
            errors.append("BEST_SO_FAR_CHECKPOINT_REGRESSION")

        # Inherited same-range path export retry.
        class RetryableCallRejected(Exception):
            def __init__(self):
                super().__init__(com.RPC_E_CALL_REJECTED, "Volany odmitl volani")
                self.hresult = com.RPC_E_CALL_REJECTED
        class TypeInfo:
            def GetTypeAttr(self): return SimpleNamespace(cFuncs=1)
            def GetFuncDesc(self, index): return SimpleNamespace(memid=19, invkind=1)
            def GetNames(self, memid): return ("SaveToArray", "FirstObject", "LastObject")
        class Ole:
            def __init__(self): self.calls = []; self.failures = 2
            def GetTypeInfo(self): return TypeInfo()
            def Invoke(self, memid, lcid, kind, as_method, first, last):
                self.calls.append((first, last))
                if self.failures:
                    self.failures -= 1; raise RetryableCallRejected()
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
            "transient_is_page_size_error": com.is_bounded_page_size_error(RetryableCallRejected()),
            "explicit_size_error_is_page_size_error": com.is_bounded_page_size_error(
                RuntimeError("SIMULATED_COM_PAGE_TOO_LARGE")),
        }
        if obj._oleobj_.calls[:3] != [(1, 256), (1, 256), (1, 256)]:
            errors.append("PATH_EXPORT_RETRY_RANGE_DRIFT")
        if raw_invoke_leaks:
            errors.append("RAW_OLE_INVOKE_LEAK:" + ",".join(raw_invoke_leaks))
        if path_retry_result["transient_is_page_size_error"] is not False or \
                path_retry_result["explicit_size_error_is_page_size_error"] is not True:
            errors.append("PATH_EXPORT_FALLBACK_CLASSIFICATION")

        # Inherited semantic restart ignores cross-run raw .ver bytes.
        snap2 = _semantic_snapshot(restart, "restart")
        first = restart.build_authority(snap2, version_path="A.ver", raw_ver_sha256="1" * 64)
        second = restart.build_authority(snap2, version_path="B.ver", raw_ver_sha256="2" * 64)
        same = restart.require_authority_match(first, second)
        changed = dict(snap2); changed["matrix_hash"] = hashlib.sha256(b"changed").hexdigest()
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
        }
        if not same["passes"] or same["raw_ver_sha_compared"] or not mismatch_failed:
            errors.append("SEMANTIC_RESTART_REGRESSION")

        compat = cfg["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
        parent_rows = [row for row in compat["predecessors"]
                       if row.get("source_release") == V2495]
        if len(parent_rows) != 1 or parent_rows[0].get("source_config_sha256s") != [V2495_CONFIG_SHA256] or \
                parent_rows[0].get("source_path_implementation_files") != V2495_PATH_IMPLEMENTATION_FILES:
            errors.append("V2495_PREDECESSOR_NOT_PINNED")

        project = temp / "PROJECT"
        nested = project / "R1_15A2_V2495_RUNS/RUN_A/CALIBRATION/CHECKPOINTS/ACCEPTED.ver"
        nested.parent.mkdir(parents=True); nested.write_bytes(b"probe")
        layout = launcher._stable_project_layout(nested)
        new_run = project / "R1_15A2_V2496_RUNS/RUN_TEST"
        launcher._assert_new_run_is_not_nested(new_run, layout["detected_run_roots_nearest_first"])
        root_result = {"project_base": str(layout["project_base"]),
                       "expected": str(project.resolve()), "new_run_postcondition": True}
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
        "schema": "R1_15A2_V2496_PACKAGE_VERIFICATION_V1",
        "release": RELEASE,
        "status": "PASS" if not errors else "FAILED",
        "errors": errors,
        "manifest_file_count": len(manifest.get("files", [])),
        "manifest_sha256": sha256(manifest_path),
        "compileall_pass": bool(compile_ok),
        "config_validation": cfg_result,
        "methodology_preservation": methodology_result,
        "early_generation_and_severity_validation": early_result,
        "early_td_pareto_validation": td_result,
        "best_so_far_checkpoint_validation": best_result,
        "path_export_retry_validation": path_retry_result,
        "semantic_restart_validation": restart_result,
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
