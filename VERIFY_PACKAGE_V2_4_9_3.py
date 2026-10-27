# -*- coding: utf-8 -*-
"""Independent offline verifier for R1 15A2 V2.4.9.3."""
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

RELEASE = "R1_15A2_V2_4_9_3_METHOD_AND_COM_CORRECTIONS_20261018"
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_3.py"
MANIFEST = "MANIFEST_V2493.json"
V2492 = "R1_15A2_V2_4_9_2_SIGNED_GENERATION_REFINEMENT_20261018"
V2492_CONFIG_SHA256 = "356cde547e168d277763cf52a3fb82cc4f766863fd0340a695ab87785960ed22"


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


def _cal_row(code, observed, model, weight=1.0):
    return {"role": "CALIBRATION", "countlocation_no": code,
            "observed": observed, "model": model, "profile_weight": weight}


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
    geh_result = long_result = com_result = None
    probe_root = Path(tempfile.mkdtemp(prefix="v2493_verify_"))
    old_modules = {name: module for name, module in sys.modules.items()
                   if name.startswith("r1_15a2_")}
    try:
        for name in list(sys.modules):
            if name.startswith("r1_15a2_"):
                del sys.modules[name]
        sys.path.insert(0, str(root)); inserted = True
        from r1_15a2_safety_v2493 import (
            V2492_PATH_IMPLEMENTATION_FILES, validate_v2493_config)
        import r1_15a2_core as core
        import r1_15a2_multiblock as mb
        import r1_15a2_com_compat as com
        import r1_15a2_runtime_v1 as rt
        from r1_15a2_overnight_controller_v242 import _generation_counts_cfg

        spec = importlib.util.spec_from_file_location("verify_v2493_launcher", root / LAUNCHER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cfg = module.load_config()
        cfg_result = validate_v2493_config(cfg, root)
        if module.RELEASE != RELEASE or cfg.get("release") != RELEASE:
            errors.append("LAUNCHER_RELEASE_MISMATCH")

        # Preserve the V2.4.9.2 signed Generation proof.
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
        early = _generation_counts_cfg(cfg, 1); late = _generation_counts_cfg(cfg, 5)
        if early["max_add_log_up"] != 0.06 or early["max_add_log_down"] != 0.06:
            errors.append("SIGNED_EARLY_STAGE")
        if late["max_add_log_up"] != 0.02 or late["max_add_log_down"] != 0.02 or \
           late["generation_signed_refinement"]["max_family_global_log_up"] != 0.005:
            errors.append("DISTRIBUTION_FOCUS_STAGE")

        # Mechanical weighted-GEH proof and diagnostic-only passage sums.
        rows = [_cal_row("A", 100.0, 121.0, 1.0),
                _cal_row("B", 400.0, 361.0, 3.0)]
        metrics = core.csd_metrics(rows)
        gehs = [core.geh(121.0, 100.0), core.geh(361.0, 400.0)]
        expected = (gehs[0] + 3.0 * gehs[1]) / 4.0
        selected = core.csd_objective_value(metrics, cfg)
        geh_result = {
            "metric": core.csd_objective_metric(cfg),
            "key": core.csd_objective_key(cfg),
            "expected_weighted_mean_geh": expected,
            "selected_value": selected,
            "legacy_geh2_value": metrics["objective_geh2_mean"],
            "profile_sum_role": metrics["profile_sum_role"],
            "unique_trip_interpretation_allowed":
                metrics["profile_sum_unique_trip_interpretation_allowed"],
        }
        if abs(selected - expected) > 1e-12:
            errors.append("WEIGHTED_MEAN_GEH_MECHANICAL_PROOF")
        if geh_result["profile_sum_role"] != "DIAGNOSTIC_ONLY_PROFILE_PASSAGE_CHECKSUM" or \
           geh_result["unique_trip_interpretation_allowed"] is not False:
            errors.append("PROFILE_SUM_SEMANTICS")

        # Synthetic global LONG mix proof: five native curves, one authority.
        long_components = [name for name, reg in mb.COMPONENT_REGISTRY.items()
                           if reg.get("family") == "LONG"]
        summaries = []; baselines = []; total = first_num = 0.0
        for i, comp in enumerate(long_components, 1):
            volume = float(100 * i); share = 0.1 * i
            summaries.append({"component": comp, "conditioned_volume": volume,
                              "total_volume": volume, "target_status": "NO_COMPONENT_TARGET"})
            baselines.extend([
                {"component": comp, "bin_low": 100.0, "bin_high": 110.0,
                 "share_conditioned": share},
                {"component": comp, "bin_low": 110.0, "bin_high": 120.0,
                 "share_conditioned": 1.0 - share},
            ])
            total += volume; first_num += volume * share
        authority = {"authority_id": "GLOBAL_LONG_VERIFY", "component_targets": {},
                     "aggregate_cl_guard": {"bins": [
                         {"bin_low": 100.0, "bin_high": 110.0, "target_share": 0.4},
                         {"bin_low": 110.0, "bin_high": 120.0, "target_share": 0.6},
                     ]}}
        signals = mb.build_td_signals(summaries, [], baselines, authority, cfg)
        composite = signals.get("LONG_COMPOSITE", {})
        collapsed = mb.collapse_td_acceptance_components(long_components, cfg)
        first = next((r for r in composite.get("model_bins", [])
                      if r.get("bin_low") == 100.0), {})
        long_result = {
            "native_components": long_components,
            "collapsed_components": collapsed,
            "composite_calibratable": composite.get("calibratable"),
            "conditioned_volume": composite.get("conditioned_volume"),
            "expected_first_share": first_num / total,
            "actual_first_share": first.get("model_share"),
            "individual_components_calibratable":
                {c: signals[c].get("calibratable") for c in long_components},
        }
        if collapsed != ["LONG_COMPOSITE"] or composite.get("calibratable") is not True:
            errors.append("GLOBAL_LONG_COMPOSITE_PROOF")
        if abs(float(first.get("model_share", -1.0)) - first_num / total) > 1e-12:
            errors.append("GLOBAL_LONG_MIX_AGGREGATION")
        if any(signals[c].get("calibratable") for c in long_components):
            errors.append("INDIVIDUAL_LONG_AUTHORITY_LEAK")

        # Transient-only COM retry and cached zone-key write proof.
        class RetryableCallRejected(Exception):
            def __init__(self):
                super().__init__(com.RPC_E_CALL_REJECTED, "Volany odmitl volani")
                self.hresult = com.RPC_E_CALL_REJECTED
        calls = {"n": 0}; sleeps = []
        def transient():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RetryableCallRejected()
            return "OK"
        retry_value = com.com_call_with_retry(
            transient, retry_policy=cfg["com_resilience"], sleep_fn=sleeps.append)
        class Zones:
            def __init__(self):
                self.values = {101: 1.0, 102: 2.0}; self.no_reads = 0
            def GetMultiAttValues(self, attr, active_only=False):
                if attr == "NO":
                    self.no_reads += 1
                    raise AssertionError("Zone.NO re-read")
                return sorted(self.values.items())
            def SetMultiAttValues(self, attr, rows, active_only=False):
                self.values.update({int(k): float(v) for k, v in rows})
        zones_obj = Zones()
        visum = type("V", (), {"Net": type("N", (), {"Zones": zones_obj})()})()
        readback = rt.write_zone_attr(
            visum, "ADD", [1, 2], [3.0, 4.0], zone_indices={1: 101, 2: 102},
            retry_policy=cfg["com_resilience"], readback_tolerance=1e-7)
        com_result = {"retry_value": retry_value, "attempts": calls["n"],
                      "sleep_schedule": sleeps, "zone_no_reads": zones_obj.no_reads,
                      "zone_readback": readback}
        if retry_value != "OK" or calls["n"] != 3 or zones_obj.no_reads != 0 or \
           readback != [3.0, 4.0]:
            errors.append("COM_RESILIENCE_MECHANICAL_PROOF")

        compat = cfg["performance"]["persistent_path_cache"][
            "explicit_predecessor_read_compatibility"]
        v2492 = [r for r in compat["predecessors"] if r["source_release"] == V2492]
        if len(v2492) != 1 or v2492[0].get("source_config_sha256s") != [V2492_CONFIG_SHA256] or \
           v2492[0].get("source_path_implementation_files") != V2492_PATH_IMPLEMENTATION_FILES:
            errors.append("V2492_PREDECESSOR_NOT_PINNED")

        project = probe_root / "PROJECT"
        nested = _probe(project / "R1_15A2_V2492_RUNS" / "RUN_A" / "CALIBRATION" /
                        "CHECKPOINTS" / "ACCEPTED.ver")
        layout = module._stable_project_layout(nested)
        new_run = project / "R1_15A2_V2493_RUNS" / "RUN_TEST"
        module._assert_new_run_is_not_nested(
            new_run, layout["detected_run_roots_nearest_first"])
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
        for name in list(sys.modules):
            if name.startswith("r1_15a2_"):
                del sys.modules[name]
        sys.modules.update(old_modules)
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
        "schema": "R1_15A2_V2493_PACKAGE_VERIFICATION_V1",
        "release": RELEASE,
        "status": "PASS" if not errors else "FAILED",
        "errors": errors,
        "manifest_file_count": len(manifest.get("files", [])),
        "manifest_sha256": sha256(manifest_path),
        "compileall_pass": bool(compile_ok),
        "config_validation": cfg_result,
        "signed_generation_validation": signed_result,
        "weighted_geh_validation": geh_result,
        "long_composite_validation": long_result,
        "com_resilience_validation": com_result,
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
