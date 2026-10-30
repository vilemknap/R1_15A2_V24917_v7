# -*- coding: utf-8 -*-
"""Small runtime wiring for TDJOINT1; sealed parent files remain unchanged."""
from __future__ import annotations
import copy
import functools
from pathlib import Path

import r1_15a2_td_joint_v24917 as joint
import r1_15a2_long_composite_td_v24917 as long_td


def wrap_inner(original):
    @functools.wraps(original)
    def inner(adapter, cfg, folder, control, package_root, *args, **kwargs):
        enabled = joint.options()["enabled"]
        adapter._tdjoint_stage = None
        result = original(adapter, cfg, folder, control, package_root, *args, **kwargs)
        if not enabled:
            return result
        stage = getattr(adapter, "_tdjoint_stage", None)
        if stage is None or Path(stage["inner_root"]) != Path(folder).resolve():
            raise RuntimeError("TDJOINT1_STAGE_RESULT_MISSING_OR_STALE")
        result = dict(result)
        result["long_composite_td"] = dict(
            long_td.activation_plan(),
            requested=bool(joint.options().get("long_enabled")),
            live_enabled=stage.get("long_composite_live_readiness") is not None,
            live_readiness=stage.get("long_composite_live_readiness"))
        result.update({k: stage[k] for k in (
            "objective_start", "objective_final", "objective_improvement",
            "search_complete", "stationarity_confirmed",
            "fresh_assignment_and_skims_per_finecdf_evaluation")})
        result["primary_objective"] = stage["metric"]
        result["tdjoint"] = stage
        result["progress_continue"] = str(result.get("stop_reason", "")) in (
            "MAX_ITERATIONS", "TD_EVALUATION_BUDGET", "TD_INNER_TIME_BUDGET")
        # Keep the original key and publish corrected semantics, not a second
        # conflicting result file.  The separate summary is the search audit.
        from r1_15a2_controller_v22 import atomic_json
        atomic_json(Path(folder) / "V24916_FINECDF_INNER_RESULT.json", result)
        return result
    inner._tdjoint1 = True
    return inner


def wrap_realization(original, ctrl):
    """Retain the existing combined/backtracking path, then bounded ablations.

    Each ablation starts only after the parent rollback was VERIFIED by the
    original path.  One additional full realization per component, <=2.  No
    new retry or acceptance exception is swallowed.  Pending IZ changes use
    the existing combined IZ realization unchanged in this first increment.
    """
    @functools.wraps(original)
    def realize(adapter, cfg, folder, control, before, baseline_diag, target_rows):
        opts = joint.options()
        stage = getattr(adapter, "_tdjoint_stage", None)
        if not opts["enabled"]:
            return original(adapter, cfg, folder, control, before, baseline_diag, target_rows)
        import r1_15a2_td_count_blend_v24917 as blend
        now = blend.options()
        if stage is None:
            raise RuntimeError("TDJOINT1_REALIZATION_STAGE_MISSING")
        if any(abs(float(stage[k]) - float(now[k])) > 1e-12 for k in ("w_cnt", "w_idp")):
            raise RuntimeError("TDJOINT1_WEIGHT_CHANGED_DURING_STAGE")
        # Never silently associate an old component plan with a new inner run.
        import r1_15a2_multiblock as mb
        component_no = {str(k): int(r["matrix_no"]) for k, r in mb.COMPONENT_REGISTRY.items()}
        groups = long_td.realization_groups(target_rows, before.get("td_values", []), component_no)
        # Accept only the real measured native dynamic result from this stage.
        if any(group == long_td.GROUP for group, _ in groups):
            proof = stage.get("long_composite_live_readiness")
            if not isinstance(proof, dict) or proof.get("status") != (
                    "READY_CURRENT_NATIVE_DYNAMIC_COUNT_RESPONSE"):
                raise RuntimeError("TDLONG_COMPOSITE_MEASURED_NATIVE_STAGE_PROOF_MISSING")
            from types import SimpleNamespace
            bridge_view = SimpleNamespace(
                outer_adapter=adapter, dynamic_skim_enabled=True,
                _v24917_frozen=False)
            fresh = long_td.require_live_ready(groups, bridge=bridge_view)
            if not fresh or fresh.get("status") != proof["status"]:
                raise RuntimeError("TDLONG_COMPOSITE_REALIZATION_AUTHORITY_STALE")
        else:
            long_td.require_live_ready(groups)
        for row in target_rows:
            final = stage["final_abc"].get(str(component_no.get(row["component"])))
            if final is None or any(abs(float(final[p]) - float(row["candidate_" + p])) > 1e-8
                                    for p in ("b", "c")):
                raise RuntimeError("TDJOINT1_TARGET_PLAN_MISMATCH:" + row["component"])
        import r1_15a2_intrazonal_penalty_v24917 as iz
        pending_iz = bool(getattr(iz, "_STAGE", {}))
        result = original(adapter, cfg, folder, control, before, baseline_diag, target_rows)
        if (result[0] or len(groups) < 2 or not opts["outer_isolates"] or pending_iz):
            return result
        if result[4].get("status") != "SOFT_REFERENCE_PLATEAU":
            return result
        # Existing target order is deterministic.  In this first version, no
        # claim is made that an inner contribution predicts live ablation rank.
        rows_order = groups[:opts["max_isolates"]]
        records = [{"kind": "COMBINED_WITH_BACKTRACK", "evidence": result[4]}]
        cfg_one = copy.deepcopy(cfg)
        fine = cfg_one.setdefault("coupled_demand", {}).setdefault("finecdf_td", {})
        fine["realization_backtracking_scales"] = [1.0]
        for ordinal, (group, rows) in enumerate(rows_order, 1):
            control.checkpoint("TDJOINT_ISOLATED_REALIZATION", component=group, force=True)
            isolated_folder = Path(folder) / ("ISOLATED_%02d_%s" % (ordinal, group))
            one = original(adapter, cfg_one, isolated_folder, control, before, baseline_diag, rows)
            records.append({"kind": "ISOLATED", "component": group, "evidence": one[4]})
            ctrl.atomic_json(Path(folder) / "TDJOINT_REALIZATION.json", {
                "release": joint.RELEASE, "attempt_groups": records,
                "max_extra_realization_trials": opts["max_isolates"],
                "accepted": bool(one[0]), "fresh_assignment_required": True,
                "parent_hash": before["state_hash"], "outer_acceptance_changed": False})
            result = one
            if one[0]:
                break
        evidence = dict(result[4])
        evidence["tdjoint_attempt_groups"] = records
        evidence["tdjoint_component_isolation"] = True
        ctrl.atomic_json(Path(folder) / "TD_REALIZATION_ATTEMPTS.json", evidence)
        return result[:4] + (evidence,)
    realize._tdjoint1 = True
    return realize


def install(controller, print_fn=print):
    import r1_15a2_finecdf_bridge_v24916 as bridge
    import r1_15a2_active_controller_patch_v24916p2c as active
    if not getattr(bridge.load_reference, "_tdjoint1", False):
        original_loader = bridge.load_reference
        @functools.wraps(original_loader)
        def loader(package_root, fine_cfg=None):
            ref, path, sha = original_loader(package_root, fine_cfg)
            if joint.options()["enabled"]:
                ref.long_composite_td_contract = long_td.reference_contract(ref)
                # A single shared b / log(-c) group for all five LONG layers.
                # Disabled mode retains historical frozen behaviour; enabled
                # mode can run ONLY via measured native DYNAMIC TD evaluations.
                if not joint.options().get("long_enabled", False):
                    ref.GROUPS = [key for key in ref.GROUPS if key != long_td.GROUP]
                ref.Runner = joint.make_runner(ref.Runner, ref)
            return ref, path, sha
        loader._tdjoint1 = True
        bridge.load_reference = loader
    # For measured LONG count response, the FineCDF inner bridge executes the
    # complete downstream procedure. Its old direct call to rt.execute_procseq
    # did NOT set the LONG post-TD mask context. Scope that actual invocation
    # so each b/c probe includes clipped 911x/929x, formula 9305, all OP17-20
    # and fresh native skims. Never mask in FROZEN_PATHS mode.
    old_dynamic = bridge.NoDirectMatrixWriteTDAdapter._execute_dynamic_realization
    if not getattr(old_dynamic, "_tdlong_dynamic_scope", False):
        @functools.wraps(old_dynamic)
        def dynamic_with_long_mask(self):
            if not joint.options().get("long_enabled", False):
                return old_dynamic(self)
            from r1_15a2_long_post_td_mask_v24917 import execution_scope
            if getattr(self, "outer_adapter", None) is None:
                raise RuntimeError("TDLONG_COMPOSITE_DYNAMIC_OUTER_ADAPTER_MISSING")
            with execution_scope(self.outer_adapter):
                return old_dynamic(self)
        dynamic_with_long_mask._tdlong_dynamic_scope = True
        bridge.NoDirectMatrixWriteTDAdapter._execute_dynamic_realization = dynamic_with_long_mask
    # The active controller owns its own imported function; patch that actual
    # dispatch too.  All wrappers are installed after GENFIX2 / IZ wrappers.
    for module, name in ((bridge, "run_finecdf_inner"),
                         (controller, "run_finecdf_inner"),
                         (active, "targeted_run_finecdf_inner")):
        old = getattr(module, name, None)
        if old is not None and not getattr(old, "_tdjoint1", False):
            setattr(module, name, wrap_inner(old))
    old = controller._realize_finecdf_td
    if not getattr(old, "_tdjoint1", False):
        controller._realize_finecdf_td = wrap_realization(old, controller)
    status = {"release": joint.RELEASE, "installed": True, "options": joint.options(),
              "sealed_reference_modified": False, "outer_acceptance_modified": False,
              "long_composite_td": dict(long_td.activation_plan(),
                                        requested=bool(joint.options().get("long_enabled")))}
    print_fn("R1 TDJOINT1: %s; shared score once; native isolated +/- probes; outer isolates=%s" %
             ("ENABLED" if status["options"]["enabled"] else "DISABLED", status["options"]["outer_isolates"]))
    return status
