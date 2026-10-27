# -*- coding: utf-8 -*-
"""Bridge a hash-locked R1 BC FineCDF authority into the 15A2 controller.

Important differences from the standalone runtime:
* the configured embedded source/targets/numerics are the scientific authority;
* no direct OD/result-matrix SetValues writes are used for rollback or clearing;
* rejected b/c states are restored by parameter restoration + a fresh native TD run;
* the caller owns the global 10 h budget and later full downstream recomputation.

The TD inner solver freezes trip-generation attributes and ADDVAL1.  It temporarily
executes only the native TD leaf (operation type 46), with FOREIGN excluded exactly
as in v1.7, then restores the original Procedure Sequence controls.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import hashlib
import importlib.util
import inspect
import json
import math
import time

import r1_15a2_runtime_v1 as rt
import r1_15a2_visum_parameters as vp
from r1_15a2_supply import SupplyContractError, canonical_hash, number
from r1_15a2_perf_v246 import optional_span

REF_REL = Path("reference_v17") / "R1_BC_AUTO_DIST_ONLY_FINECDF_PATCHED_v1_7.py"
REF_SHA256 = "2160f79fbd5de1645635327cb46e4a7daf6a14304af3e683d4f5dce98ebccf82"


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_reference(package_root, fine_cfg=None):
    fine_cfg = dict(fine_cfg or {})
    rel = Path(fine_cfg.get("reference_script", str(REF_REL)))
    expected_sha = str(fine_cfg.get("reference_sha256", REF_SHA256))
    expected_id = str(fine_cfg.get(
        "reference_script_id",
        "R1_BC_AUTO_DIST_ONLY_FINECDF_PATCHED_V1_7_20261016"))
    if rel.is_absolute() or ".." in rel.parts:
        raise SupplyContractError("V246_FINECDF_REFERENCE_PATH_NOT_PACKAGE_RELATIVE")
    root = Path(package_root).resolve()
    path = (root / rel).resolve()
    if root != path and root not in path.parents:
        raise SupplyContractError("V246_FINECDF_REFERENCE_ESCAPES_PACKAGE")
    if not path.is_file():
        raise SupplyContractError("V242_FINECDF_REFERENCE_MISSING")
    got = _sha(path)
    if got != expected_sha:
        raise SupplyContractError("V242_FINECDF_REFERENCE_HASH_MISMATCH:%s" % got)
    module_name = "r1_bc_finecdf_authority_" + got[:16]
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise SupplyContractError("V242_FINECDF_REFERENCE_IMPORT_SPEC_FAILED")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if getattr(mod, "SCRIPT_ID", "") != expected_id:
        raise SupplyContractError("V242_FINECDF_REFERENCE_SCRIPT_ID_MISMATCH")
    return mod, path, got


class NoDirectMatrixWriteTDAdapter:
    """Adapter required by v1.7 Runner, but rollback is recomputation-only."""

    A_ATTRS = ("PARA_A", "Para_A", "ParaA", "PARAM_A", "ParamA", "ParameterA", "A")

    def __init__(self, visum, ref, root, control=None, telemetry=None):
        self.v = visum
        self.telemetry = telemetry
        self.ref = ref
        self.root = Path(root)
        self.control = control
        self.n = int(ref.CONFIG["expected_zone_count"])
        self.ops = rt.get_all(self.v.Procedures.Operations)
        self.inventory = []
        self.controls_changed = False
        self.td_index = None
        self.td = None
        self.original_dset = None
        expected = {r["dstrat_code"] for r in ref.COMPONENTS}
        candidates = []
        for i, op in enumerate(self.ops, 1):
            typ = int(number(rt.att(op, "OPERATIONTYPE", -1)))
            active = bool(number(rt.att(op, "ACTIVE", 0)))
            row = {"index": i, "type": typ, "active": int(active),
                   "comment": str(rt.att(op, "COMMENT", "")),
                   "is_group": typ == int(ref.CONFIG["td_group_type"])}
            self.inventory.append(row)
            if typ == 46:
                try:
                    td = op.TripDistributionParameters
                    raw = str(td.AttValue("DSTRATSET"))
                    codes = {s.strip() for s in raw.split(",") if s.strip()}
                except Exception:
                    continue
                if codes == expected:
                    candidates.append((i, td, raw))
        ref.write_csv(self.root / "TD_PROCEDURE_INVENTORY.csv", self.inventory)
        if len(candidates) != 1:
            raise SupplyContractError("V242_EXPECTED_ONE_FULL_R1_TD_OPERATION_FOUND_%d" % len(candidates))
        self.td_index, self.td, self.original_dset = candidates[0]
        if not self.inventory[self.td_index - 1]["active"]:
            raise SupplyContractError("V242_R1_TD_OPERATION_INACTIVE")
        self.active_dset = ",".join(r["dstrat_code"] for r in ref.COMPONENTS if int(r["matrix_no"]) != 9116)

        pairs = list(self.v.Net.Zones.GetMultiAttValues("NO"))
        self.zone_order = [int(number(v)) for _k, v in pairs]
        if len(self.zone_order) != self.n or len(set(self.zone_order)) != self.n:
            raise SupplyContractError("V242_INVALID_ZONE_ORDER")
        if set(self.zone_order) != set(range(1, self.n + 1)):
            raise SupplyContractError("V242_EXPECTED_ZONE_NO_1_681")

        self.generation_guard = self._capture_generation_guard()
        self.addval_guard = self._capture_addval_guard()
        self.protected = {no: self.read_matrix(no) for no in (9001, 9697, 9116)}
        self.protected_hashes = {n: ref.sha_array(a) for n, a in self.protected.items()}
        if float(self.protected[9697].min()) < 0:
            raise SupplyContractError("V242_NEGATIVE_DISTANCE_MATRIX")
        if ref.CONFIG.get("require_2022_patch_preflight", True):
            ref.verify_2022_osrm_amdy_patched_inputs(
                self.protected, self.zone_order, self.root / "PATCHED_INPUT_PREFLIGHT.json")
        self.entry_abc = self.read_abc()
        self.initial_matrices = self.read_outputs()

    def _capture_generation_guard(self):
        attrs = ["ADD_PROD_W", "ADD_ATT_W", "ADD_PROD_S", "ADD_ATT_S", "ADD_SALARY",
                 "ZAHR_PROD_WORK", "ZAHR_PROD_SERV", "ZAHR_ATR_WORK", "ZAHR_ATR_SERV"]
        out = {}
        for a in attrs:
            try:
                out[a] = [[str(k), str(v)] for k, v in self.v.Net.Zones.GetMultiAttValues(a)]
            except Exception as exc:
                raise SupplyContractError("V245_TD_GENERATION_FREEZE_UNREADABLE:" + a) from exc
            if len(out[a]) != self.n or len({row[0] for row in out[a]}) != self.n:
                raise SupplyContractError("V245_TD_GENERATION_FREEZE_INCOMPLETE:" + a)
        return out

    def _capture_addval_guard(self):
        rows = []
        try:
            for key, value in self.v.Net.Links.GetMultiAttValues("ADDVAL1"):
                rows.append((str(key), str(value)))
        except Exception as exc:
            raise SupplyContractError("V245_TD_ADDVAL_FREEZE_UNREADABLE") from exc
        if not rows:
            raise SupplyContractError("V245_TD_ADDVAL_FREEZE_EMPTY")
        return canonical_hash(rows)

    def _guard_generation_addval(self):
        for a, expected in self.generation_guard.items():
            got = [[str(k), str(v)] for k, v in self.v.Net.Zones.GetMultiAttValues(a)]
            if got != expected:
                raise SupplyContractError("V242_TD_INNER_MUTATED_GENERATION:" + a)
        if self.addval_guard is not None:
            rows = [(str(k), str(v)) for k, v in self.v.Net.Links.GetMultiAttValues("ADDVAL1")]
            if canonical_hash(rows) != self.addval_guard:
                raise SupplyContractError("V242_TD_INNER_MUTATED_ADDVAL1")

    def gravity(self, matrix_no):
        code = self.ref.BY_NO[int(matrix_no)]["dstrat_code"]
        obj = self.td.TripDistributionDStratParameters(code)
        return obj.GravitationParameters

    @staticmethod
    def _read_attr(obj, names):
        for name in names:
            try:
                value = obj.AttValue(name)
                if value not in (None, ""):
                    parsed = float(value)
                    if not math.isfinite(parsed):
                        raise SupplyContractError("V245_TD_NONFINITE_PARAMETER:" + name)
                    return parsed
            except SupplyContractError:
                raise
            except Exception:
                pass
        raise SupplyContractError("V242_TD_PARAMETER_ATTR_UNREADABLE:" + "/".join(names))

    def read_abc(self):
        out = {}
        for no in self.ref.BY_NO:
            g = self.gravity(no)
            out[int(no)] = {
                "a": self._read_attr(g, self.A_ATTRS),
                "b": self._read_attr(g, vp.TD_B_ATTRS),
                "c": self._read_attr(g, vp.TD_C_ATTRS),
            }
        return out

    def set_abc(self, abc):
        candidates = []
        # v1.7 authority: a and FOREIGN are frozen; only b/c of 16 components move.
        for no in self.ref.MUTABLE_NOS:
            comp = self.ref.BY_NO[int(no)]["component"]
            candidates.append({"component": comp,
                               "candidate_b": float(abc[int(no)]["b"]),
                               "candidate_c": float(abc[int(no)]["c"])})
        audit = vp.apply_td_candidates(self.v, candidates)
        if not audit or any(r.get("status") != "OK" for r in audit):
            raise SupplyContractError("V242_TD_PARAMETER_READBACK_FAILED")
        actual = self.read_abc()
        tol = float(self.ref.CONFIG["parameter_readback_atol"])
        for no in self.ref.BY_NO:
            for p in ("a", "b", "c"):
                if abs(float(actual[int(no)][p]) - float(abc[int(no)][p])) > tol:
                    raise SupplyContractError("V242_TD_ABC_READBACK_MISMATCH_M%d_%s" % (no, p))
        return actual

    def read_matrix(self, no):
        np = self.ref.np
        if np is None:
            raise SupplyContractError("V242_NUMPY_UNAVAILABLE")
        a = np.array(self.v.Net.Matrices.ItemByKey(int(no)).GetValues(), dtype=np.float64, copy=True)
        if a.shape != (self.n, self.n) or not np.isfinite(a).all():
            raise SupplyContractError("V242_MATRIX_INVALID_M%d" % int(no))
        return a

    def read_outputs(self):
        return {int(n): self.read_matrix(n) for n in self.ref.MUTABLE_NOS}

    def isolate_td(self):
        self.controls_changed = True
        self.td.SetAttValue("DSTRATSET", self.active_dset)
        for r, op in zip(self.inventory, self.ops):
            if r["is_group"]:
                continue
            want = int(r["index"] == self.td_index)
            actual = int(bool(number(rt.att(op, "ACTIVE", 0))))
            if actual != want:
                op.SetAttValue("ACTIVE", want)
        self.assert_isolated()

    def assert_isolated(self):
        actual = {x.strip() for x in str(self.td.AttValue("DSTRATSET")).split(",") if x.strip()}
        if actual != set(self.active_dset.split(",")):
            raise SupplyContractError("V242_TD_DSTRATSET_NOT_ISOLATED")
        if len(rt.get_all(self.v.Procedures.Operations)) != len(self.ops):
            raise SupplyContractError("V242_PROCEDURE_SEQUENCE_CHANGED")
        for r, op in zip(self.inventory, self.ops):
            if r["is_group"]:
                continue
            got = int(bool(number(rt.att(op, "ACTIVE", 0))))
            want = int(r["index"] == self.td_index)
            if got != want:
                raise SupplyContractError("V242_TD_ACTIVE_MASK_MISMATCH_%d" % r["index"])

    def restore_controls(self):
        if not self.controls_changed:
            return
        errors = []
        try:
            self.td.SetAttValue("DSTRATSET", self.original_dset)
        except Exception as exc:
            errors.append("DSTRATSET:%r" % (exc,))
        for r, op in zip(self.inventory, self.ops):
            if r["is_group"]:
                continue
            try:
                actual = int(bool(number(rt.att(op, "ACTIVE", 0))))
                if actual != int(r["active"]):
                    op.SetAttValue("ACTIVE", int(r["active"]))
            except Exception as exc:
                errors.append("ACTIVE_%d:%r" % (r["index"], exc))
        try:
            if str(self.td.AttValue("DSTRATSET")) != self.original_dset:
                errors.append("DSTRATSET_READBACK")
            for row, op in zip(self.inventory, self.ops):
                if int(bool(number(rt.att(op, "ACTIVE", 0)))) != int(row["active"]):
                    errors.append("ACTIVE_READBACK_%d" % row["index"])
            if len(rt.get_all(self.v.Procedures.Operations)) != len(self.ops):
                errors.append("PROCEDURE_COUNT_CHANGED")
        except Exception as exc:
            errors.append("DSTRATSET_READBACK:%r" % (exc,))
        if errors:
            raise SupplyContractError("V242_TD_CONTROL_RESTORE_FAILED:" + ";".join(errors))
        self.controls_changed = False

    def guard_protected(self, full=False):
        self._guard_generation_addval()
        for no in (9001, 9697, 9116):
            if self.ref.sha_array(self.read_matrix(no)) != self.protected_hashes[no]:
                raise SupplyContractError("V242_TD_PROTECTED_MATRIX_CHANGED_M%d" % no)

    def execute(self):
        self.assert_isolated()
        # Stop/time gates are checked before parameter writes by the integrated
        # v1.7 log hook.  Do not raise a stop here after b/c have been written.
        # No output matrix clearing and no direct OD writes.  A failed native call must
        # surface as COM/procedure failure; positive regenerated matrices are required.
        with optional_span(self, "VISUM_NATIVE_TD_EXECUTE", purpose="FINECDF_INNER"):
            self.v.Procedures.Execute()
        arrays = self.read_outputs()
        for no, a in arrays.items():
            if float(a.sum()) <= 0 or float(a.min()) < -1e-10:
                raise SupplyContractError("V242_NATIVE_TD_INVALID_OUTPUT_M%d" % no)
        self.guard_protected(full=True)
        return arrays

    def restore_state(self, abc, matrices):
        self.set_abc(abc)
        regenerated = self.execute()
        np = self.ref.np
        for no, expected in matrices.items():
            actual = regenerated[int(no)]
            # Native rerun is the rollback authority.  It must reproduce the accepted
            # matrix numerically; we deliberately do not SetValues(expected).
            if not np.allclose(actual, expected, rtol=1e-10, atol=1e-8, equal_nan=False):
                diff = float(np.max(np.abs(actual - expected)))
                raise SupplyContractError("V242_TD_RECOMPUTE_ROLLBACK_MATRIX_DIFFER_M%d_MAX_%g" % (no, diff))
        self.guard_protected(full=True)
        return regenerated


def _abc_delta_rows(ref, before, after):
    rows = []
    for no in ref.MUTABLE_NOS:
        b0, c0 = float(before[no]["b"]), float(before[no]["c"])
        b1, c1 = float(after[no]["b"]), float(after[no]["c"])
        if abs(b1-b0) > 1e-12 or abs(c1-c0) > 1e-12:
            rows.append({"matrix_no": int(no), "component": ref.BY_NO[no]["component"],
                         "before_b": b0, "after_b": b1, "delta_b": b1-b0,
                         "before_c": c0, "after_c": c1, "delta_c": c1-c0})
    return rows



def _install_native_multi_diagnostic_guard(ref, policy):
    """Use native Visum Multi output as the TD authority in integrated overnight mode.

    The standalone v1.7 audit remains scientifically valuable and is left bit-identical
    in reference_v17.  Its fixed marginal tolerances, however, must not act as an
    external strict-IPF convergence requirement on Visum's iterative Multi procedure.
    We therefore keep the complete audit rows/worst-zone evidence but suppress the
    hard reject list and do not persist an inferred constrained axis.  P/A attributes,
    protected matrices, b/c readback, finite matrices and the downstream live objective
    remain guarded elsewhere.
    """
    if policy != "DIAGNOSTIC_ONLY_NATIVE_OUTPUT_AUTHORITY":
        return None
    original = ref.audit_native_marginals

    def diagnostic_only(reference, trial_matrices, prior_modes, zone_order):
        rows, worst, failures, candidate_modes, mode_rows = original(
            reference, trial_matrices, {}, zone_order)
        suppressed = len(failures)
        for row in rows:
            row["native_multi_guard_policy"] = policy
            row["original_hard_guard_failure"] = int(row.get("hard_guard_failure", 0))
            row["hard_guard_failure"] = 0
            if row.get("constraint_status") == "REJECT_CONSTRAINED_SIDE":
                row["constraint_status"] = "NATIVE_MULTI_DIAGNOSTIC_ONLY"
        for row in worst:
            row["native_multi_guard_policy"] = policy
            row["original_hard_guard_failure"] = int(row.get("hard_guard_failure", 0))
            row["hard_guard_failure"] = 0
            if row.get("interpretation") == "CHECK_FAILED":
                row["interpretation"] = "NATIVE_MULTI_RESIDUAL_DIAGNOSTIC"
        for row in mode_rows:
            row["native_multi_guard_policy"] = policy
            row["hard_reject_suppressed"] = suppressed
            row["evidence"] = (str(row.get("evidence", "")) +
                "; integrated V2.4.4: native Visum Multi output is authoritative, fixed external marginal tolerance is diagnostic only")
        # No persisted inferred mode: each native result is measured independently.
        return rows, worst, [], {}, mode_rows

    ref.audit_native_marginals = diagnostic_only
    return original

def run_finecdf_inner(adapter, cfg, folder, control, package_root, phase_budget=None):
    """Calibrate b/c against the exact 512-point IDP authority.

    Leaves Visum at the best accepted b/c + corresponding native TD output, with
    the original Procedure Sequence ACTIVE flags/DSTRATSET restored.  The caller
    must then run the full downstream Procedure Sequence before network scoring.
    """
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    fine_cfg = cfg.get("coupled_demand", {}).get("finecdf_td", {})
    if len(inspect.signature(load_reference).parameters) >= 2:
        ref, ref_path, ref_sha = load_reference(package_root, fine_cfg)
    else:
        # Compatibility with frozen test/user adapters that monkeypatch the
        # one-argument V2.4.5 loader.
        ref, ref_path, ref_sha = load_reference(package_root)
    phase_budget = dict(phase_budget or {})
    native_multi_policy = str(fine_cfg.get("native_multi_guard_policy", "STRICT_V17"))
    _install_native_multi_diagnostic_guard(ref, native_multi_policy)
    # Preserve v1.7 defaults unless the integration config explicitly lowers a budget.
    ref.CONFIG["max_iterations"] = int(phase_budget.get(
        "max_iterations", fine_cfg.get("max_iterations", ref.CONFIG["max_iterations"])))
    ref.CONFIG["max_td_evaluations"] = int(phase_budget.get(
        "max_td_evaluations", fine_cfg.get("max_td_evaluations", ref.CONFIG["max_td_evaluations"])))
    ref.CONFIG["max_stagnant_iterations"] = int(fine_cfg.get("max_stagnant_iterations", ref.CONFIG["max_stagnant_iterations"]))
    per_inner = float(fine_cfg.get("max_runtime_seconds", ref.CONFIG["max_runtime_seconds"]))
    ref.CONFIG["max_runtime_seconds"] = min(per_inner, max(1.0, float(control.remaining())))
    ref.CONFIG["save_versions"] = False

    log = ref.Log(folder)
    log.summary["integration"] = str(fine_cfg.get(
        "integration_id", "15A2_V2_4_5_COUPLED_DEMAND_INNER_TD"))
    log.summary["reference_source"] = str(ref_path)
    log.summary["reference_sha256"] = ref_sha
    log.summary["rollback_policy"] = "RESTORE_BC_AND_RERUN_NATIVE_TD_NO_MATRIX_SETVALUES"
    log.summary["direct_od_matrix_writes"] = False
    log.summary["native_multi_guard_policy"] = native_multi_policy
    log.summary["progressive_budget"] = phase_budget
    log.summary["native_multi_guard_method"] = "KEEP_FULL_MARGINAL_DIAGNOSTICS_BUT_DO_NOT_IMPOSE_EXTERNAL_STRICT_IPF_REJECT_ON_NATIVE_VISUM_MULTI"
    bridge = NoDirectMatrixWriteTDAdapter(
        adapter.visum, ref, folder, control=control,
        telemetry=getattr(adapter, "telemetry", None))
    start_abc = {n: dict(v) for n, v in bridge.entry_abc.items()}
    runner = None
    stop_reason = None
    try:
        bridge.isolate_td()
        runner = ref.Runner(bridge, log)
        original_check = log.check_stop
        inner_started = time.monotonic()
        max_eval = int(ref.CONFIG["max_td_evaluations"])
        max_secs = float(ref.CONFIG["max_runtime_seconds"])

        def integrated_check(evaluations):
            # Convert global cooperative stop/time into an inner safe-stop request.
            # Runner checks this only between native TD evaluations, before the next
            # b/c write, so the current best state remains coherent.
            try:
                control.checkpoint("TD_FINECDF_INNER", td_evaluations=int(evaluations),
                                   td_inner_elapsed=round(time.monotonic()-inner_started, 3))
            except Exception as exc:
                if exc.__class__.__name__ in ("UserStopRequested", "TimeBudgetReached"):
                    raise ref.StopRequested("GLOBAL_" + exc.__class__.__name__.upper())
                raise
            if evaluations >= max_eval:
                raise ref.StopRequested("TD_EVALUATION_BUDGET")
            if time.monotonic() - inner_started >= max_secs:
                raise ref.StopRequested("TD_INNER_TIME_BUDGET")
            # Retain v1.7 STOP.txt compatibility too.
            if (log.root / "STOP.txt").exists():
                raise ref.StopRequested("TD_USER_STOP_FILE")

        log.check_stop = integrated_check
        try:
            stop_reason = runner.optimize()
        except ref.StopRequested as exc:
            stop_reason = str(exc)
            if runner.best is None:
                raise
        finally:
            log.check_stop = original_check
        # Make best accepted inner state explicit before restoring controls.
        if runner.best is not None:
            bridge.restore_state(runner.best["abc"], runner.best["matrices"])
    finally:
        try:
            bridge.restore_controls()
        except Exception:
            # Control restoration is a hard failure; the outer runner must stop.
            raise

    if runner is None or runner.best is None:
        raise SupplyContractError("V242_FINECDF_NO_BEST_STATE")
    end_abc = bridge.read_abc()
    changed_rows = _abc_delta_rows(ref, start_abc, end_abc)
    objective_start = float(sum(m["objective"] for m in runner.baseline["metrics"].values()))
    objective_final = float(sum(m["objective"] for m in runner.best["metrics"].values()))
    full_complete = stop_reason == "LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM"
    budget_progress = bool(phase_budget.get("allow_progress_continue")) and not full_complete and str(stop_reason) in (
        "MAX_ITERATIONS", "TD_EVALUATION_BUDGET")
    summary = {
        "schema": "R1_15A2_V242_FINECDF_INNER_RESULT_V1",
        "repair_release": str(cfg.get("release", "V2.4.5")),
        "status": "COMPLETED_BEST_STATE_RETAINED",
        "stop_reason": stop_reason,
        "search_complete": full_complete,
        "stationarity_confirmed": full_complete,
        "progress_continue": budget_progress,
        "progressive_budget": phase_budget,
        "iterations_completed": int(log.summary.get("iterations_completed", 0)),
        "reference_sha256": ref_sha,
        "objective_start": objective_start,
        "objective_final": objective_final,
        "objective_improvement": objective_start - objective_final,
        "changed": bool(changed_rows),
        "changed_components": [r["component"] for r in changed_rows],
        "changed_rows": changed_rows,
        "td_evaluations": int(runner.evaluations),
        "direct_od_matrix_writes": False,
        "generation_frozen": True,
        "addval1_frozen": True,
        "foreign_frozen": True,
        "primary_objective": str(fine_cfg.get(
            "primary_objective", "512_POINT_IDP_CDF_PLUS_MEAN_DISTANCE")),
        "survey_reference_role": str(fine_cfg.get(
            "survey_reference_role", "HARD_REFERENCE_LEGACY")),
        "exact_curve_match_required": bool(fine_cfg.get(
            "exact_curve_match_required", True)),
        "native_multi_guard_policy": native_multi_policy,
    }
    log.summary.update(status="COMPLETED_BEST_STATE_RETAINED", stop_reason=stop_reason,
                       search_complete=summary["search_complete"])
    log.event("INNER_FINISHED", str(stop_reason))
    ref.write_json(folder / "V242_FINECDF_INNER_RESULT.json", summary)
    ref.write_diagnostics(folder / "FINAL_FINECDF", runner.best["metrics"], runner.best["abc"], full_fine=True)
    return summary


__all__ = ["load_reference", "NoDirectMatrixWriteTDAdapter", "run_finecdf_inner", "REF_SHA256"]
