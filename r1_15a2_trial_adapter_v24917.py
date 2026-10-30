# -*- coding: utf-8 -*-
"""V24917 adapter: targeted, coarse catch-up Generation on top of V24916 ACTIVE.

Inherited unchanged: assignment, dynamic DIS skims, 12D/11D (+dynamic 11D
overlay), TD targeting, support-risk gate and acceptance logic.  GENFIX1
hardens full snapshot reads and uncached Generation parent checks while
preserving the exact semantic schema.  Generation design changes:

1. FlowBundle evidence builder replaced by the fixed V24917 subclass, so
   Generation/TD targeting evidence is actually published (V24916 NameError).
2. generation_design: after the certified parent design (path incidence,
   guidance solve, evidence) the Generation proposal is replaced by the
   V24917 zonal count fit (r1_15a2_zonal_count_fit_v24917): per-zone P/A log
   steps fitted to all CAL count residuals.  Any fit error falls back to the
   unchanged parent proposal and is written to V24917_FIT_FALLBACK.json.
3. generation_preview / apply_generation run under a phase overlay
   (CATCH_UP: +50 % / -20 % per zone and cycle, no soft damping; REFINE: stage
   caps) and the TARGETED_ZONE_DIRECT design mode (no uniform family term).
"""
from __future__ import annotations

import contextlib
import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping

import r1_15a2_core as core
import r1_15a2_runtime_v1 as rt
import r1_15a2_multiblock as mb
import r1_15a2_supply_visum as supply_visum
from r1_15a2_trial_adapter_v24916p2c_active import VisumAdapter as _V24916ActiveAdapter
from r1_15a2_active_demand_evidence_v24917 import ActiveDemandEvidenceBuilder as _FixedEvidenceBuilder
from r1_15a2_demand_evidence_v24916 import target_projection_rows
import r1_15a2_targeted_generation_v24917 as tg
import r1_15a2_zonal_count_fit_v24917 as zf
import r1_15a2_dynamic_11d_files_v24917 as d11fix
import r1_15a2_long_school_generation_v24917 as lsgen
import r1_15a2_long_distance_guard_v24917 as longguard
import r1_15a2_long_od_mask_v24917 as longmask
import r1_15a2_long_post_td_mask_v24917 as post_td_mask
import r1_15a2_long_incidence_read_v24917 as long_incidence_read
import r1_15a2_long_cache_generation_v24917 as long_cache
import r1_15a2_demand_policy_v1 as long_opts
import r1_15a2_boundary_generation_v24917 as bdgen
import r1_15a2_boundary_pa_v24917 as bdpa
import r1_15a2_mobility_guard_v24917 as mguard
import r1_15a2_mobility_zone_v24917 as zguard
import r1_15a2_intrazonal_penalty_v24917 as izpen
import r1_15a2_snapshot_reads_v24917 as snapshot_reads
import r1_15a2_com_busy_snapshot_hotfix_v24916 as snapshot_retry

RELEASE = "R1_15A2_V24917_MOBILITYALLOC1_TDLONG1_ADAPTER_20261027"


class VisumAdapter(_V24916ActiveAdapter):
    runtime_backend = "VISUM_COM_V24917_TARGETED_CATCHUP_ZONAL_COUNT_FIT"

    def __init__(self, visum: Any, cfg: Mapping[str, Any], control: Any = None):
        self._long_post_td_mask_enabled = True
        self.v24917_ls = lsgen.activate(visum)        # idempotent; launcher activates first
        super().__init__(visum, cfg, control)
        if self.v24916_active_evidence is not None:
            self.v24916_active_evidence = _FixedEvidenceBuilder.from_parent(self.v24916_active_evidence)
        self.v24917_status = {"release": RELEASE, "designs": 0, "fit_fallbacks": 0,
                              "last_phase": None, "last_ratio": None,
                              "long_school_activation": dict(self.v24917_ls),
                              "ls_incomplete_current_cycle": False,
                              "longguard1": longguard.RELEASE,
                              "long_generation_requested": bool(
                                  long_opts.load_options()["long_generation_enabled"]),
                              "long_composite_td_requested": bool(
                                  long_opts.load_options()["long_composite_td_enabled"]),
                              "school_td_requested": bool(
                                  long_opts.load_options()["school_td_enabled"])}

    def assign(self, folder, *, supply_only):
        with post_td_mask.execution_scope(self):
            return super().assign(folder, supply_only=supply_only)

    def assign_for_block(self, folder, block):
        with post_td_mask.execution_scope(self):
            return super().assign_for_block(folder, block)

    def _refresh_dynamic_skims_after_assignment(self, *args, **kwargs):
        self._long_incidence_assignment_binding = None
        epoch = super()._refresh_dynamic_skims_after_assignment(*args, **kwargs)
        if epoch is not None:
            long_incidence_read.bind_after_assignment(self)
        return epoch

    def diagnostics(self, folder, label="CURRENT"):
        """Rebind LONG only after a semantically unchanged diagnostic read.

        The PERF2 diagnostic reader invalidates the candidate readback mutation
        epoch because CountLocation UDAs may be written.  This alone does not
        change a completed assignment, but no stale binding is ever accepted.
        """
        bound = getattr(self, "_long_incidence_assignment_binding", None)
        current = None
        if bound is not None:
            current = long_incidence_read._epoch(self, require_completed=True)
            if current != bound:
                current = None
        if current is None:
            return super().diagnostics(folder, label=label)

        before = self.generation_guard_snapshot()
        result = super().diagnostics(folder, label=label)
        after = long_incidence_read._epoch(self, require_completed=True)
        if any(after[key] != current[key] for key in (
                "assignment_epoch", "skim_epoch_hash", "assignment_token",
                "zone_order_sha256")):
            raise RuntimeError("LONG_INCIDENCE_DIAGNOSTICS_ASSIGNMENT_CHANGED")
        if after["mutation_epoch"] != current["mutation_epoch"] + 1:
            raise RuntimeError("LONG_INCIDENCE_DIAGNOSTICS_MUTATION_EPOCH_UNEXPECTED")
        if self.generation_guard_snapshot() != before:
            raise RuntimeError("LONG_INCIDENCE_DIAGNOSTICS_MODEL_CHANGED")
        long_incidence_read.bind_after_assignment(self)
        return result

    def td_target_plan(self, diag, folder):
        """Add SCHOOL and LONG to the native TDJOINT1 active pool independently.

        SCHOOL is one atomic M9117 IDP target and changes native gravity b/c,
        never the AMDY school TG formulas. LONG is one aggregate 5-layer
        composite; its existing dynamic count and support proof is unchanged.
        In GLOBAL_IDP_FALLBACK the reference loader owns the entire pool and
        opt-in filtering is applied there, not by inventing a target mask.
        """
        plan = super().td_target_plan(diag, folder)
        opts = long_opts.load_options()
        school = bool(opts["school_td_enabled"])
        long = bool(opts["long_composite_td_enabled"])
        if not (school or long):
            return plan
        plan = dict(plan)
        plan["school_td_requested"] = school
        plan["long_composite_td_requested"] = long
        if plan.get("status") == "ACTIVE":
            selected = list(plan.get("active_components") or ())
            if not selected:
                raise supply_visum.SupplyContractError("TDSCHOOL_LONG_ACTIVE_POOL_EMPTY")
            if len(selected) != len(set(selected)):
                raise supply_visum.SupplyContractError("TD_COMPONENT_POOL_DUPLICATE")
            if school:
                if "SCHOOL" in selected:
                    raise supply_visum.SupplyContractError("TDSCHOOL_TARGET_MASK_COLLISION")
                selected.append("SCHOOL")
                plan["school_td_policy"] = "SCHOOL_9117_NATIVE_B_C_IDP_512"
                plan["school_td_target_count"] = 1
            if long:
                if "LONG_COMPOSITE" in selected:
                    raise supply_visum.SupplyContractError("TDLONG_COMPOSITE_TARGET_MASK_COLLISION")
                selected.append("LONG_COMPOSITE")
                plan["long_composite_policy"] = "SHARED_B_OFFSET_LOG_NEG_C_5_COMPONENTS"
                plan["long_count_response"] = "LIVE_NATIVE_DYNAMIC_ASSIGNMENT_REQUIRED"
                plan["targeted_long_component_count"] = 1
            plan["active_components"] = selected
            rt.write_json(Path(folder) / "TD_ACTIVE_COMPONENT_MASK.json", plan)
        else:
            if plan.get("status") != "GLOBAL_IDP_FALLBACK":
                raise supply_visum.SupplyContractError("TDSCHOOL_LONG_TARGET_PLAN_UNKNOWN_STATUS")
            if school:
                plan["school_td_policy"] = "GLOBAL_IDP_FALLBACK_INCLUDES_SCHOOL_9117"
            if long:
                plan["long_composite_policy"] = "GLOBAL_IDP_FALLBACK_INCLUDES_ONE_LONG_COMPOSITE"
                plan["long_count_response"] = "LIVE_NATIVE_DYNAMIC_ASSIGNMENT_REQUIRED"
        return plan

    def long_profile_incidence(self, diag, folder):
        """Explicit read-only LONG audit using the same ordered 12D profile rows.

        Does not alter the W/S path cache or enable LONG Generation/TD fitting.
        The expensive NATIVE_CL export is requested only by this diagnostic API.
        """
        return long_incidence_read.read_current(self, diag["d12"]["rows"], folder)

    @staticmethod
    def _without_unverified_long_rows(rows, context=None):
        """Only this adapter's validated cache-backed proposal may change LONG."""
        if ((context or {}).get("_long_cache_receipt")
                and ((context or {}).get("v24917_ls") or {}).get("summary", {}).get("long_generation_permitted") is True):
            return list(rows)
        return [row for row in rows if str(row.get("family", "")).upper() != "LONG"]

    # ------------------------------------------------------- GENFIX1 snapshot
    def legacy_snapshot_from_live_visum(self):
        """Read the unchanged semantic schema without masking transient COM errors.

        PERF2's candidate bundle still reuses successful snapshots within its
        established mutation/assignment epoch.  Every full read now goes through
        the strict V24917 reader, including the read used to build that bundle.
        A rejected optional COM read must never become an empty input in a hash.
        """
        self._sync_readback_telemetry()
        self._record_snapshot_event("LEGACY_SNAPSHOT_TOTAL")
        result = snapshot_reads.strict_snapshot(self)
        self.last_perf2c_snapshot_parity = {
            "status": "V24917_STRICT_FULL_SNAPSHOT",
            "state_hash": result.get("state_hash"),
            "public_snapshot_schema_changed": False,
            "cross_call_cache": False,
            "transient_read_errors_use_defaults": False,
            "unsafe_legacy_fallback": False,
        }
        self._record_snapshot_event(
            "V24917_STRICT_FULL_SNAPSHOT", state_hash=result.get("state_hash"))
        return result

    def generation_guard_snapshot(self):
        """Force a live parent check, including uncached M9002 penalties.

        Generation design is not a candidate-readback epoch.  Its integrity
        boundary must read Visum even when the preceding accepted candidate has
        left a reusable PERF2 bundle or PERF3 penalty entry in memory.
        """
        def read_live():
            result = self.legacy_snapshot_from_live_visum()
            if izpen.active():
                result = dict(result)
                result[izpen.SNAPSHOT_KEY] = izpen.penalty_dict(izpen.read_penalty(self.visum))
                result[izpen.BASE_KEY] = izpen.base_sha(izpen.STATE["base"])
            return result
        return snapshot_retry._read_retry(self, "V24917_GENERATION_PARENT_SNAPSHOT", read_live)

    # ------------------------------------------------------- IZPEN1 snapshot
    def snapshot(self):
        """Parent snapshot + the intrazonal penalties of M9002 (key v24917_iz_penalty).

        state_hash is NOT changed; every snapshot comparison (rollback equality, stale parent,
        diagnostics-did-not-change-model) now also covers the penalties.
        """
        return izpen.extend_snapshot(super().snapshot(), self.visum)

    # ------------------------------------------------------- dynamic 11D fix
    def _dynamic_11d_overlay(self, diag, folder, label):
        if self.v24916_dynamic_skims is None:
            return super()._dynamic_11d_overlay(diag, folder, label)
        # Work in a short folder (Windows MAX_PATH), mirror evidence into the run tree.
        short = d11fix.new_short_folder()
        out = d11fix.dynamic_folder(short, label)
        d11fix.stage_static_files(diag["d11"]["summary_path"], out)
        with d11fix.capture_metrics() as captured:
            diag = super()._dynamic_11d_overlay(diag, short, label)
        diag = dict(diag)
        report = d11fix.publish_dynamic_files(self, diag, out, self.cfg, captured=captured)
        report["evidence_mirror"] = d11fix.mirror(out, d11fix.dynamic_folder(folder, label))
        diag["v24917_dynamic_11d_files"] = report
        return diag

    # ---------------------------------------------------------------- overlay
    @contextlib.contextmanager
    def _v24917_overlay(self, phase):
        old = self.cfg
        self.cfg = tg.overlay_cfg(old, phase) if phase else old
        try:
            yield self.cfg
        finally:
            self.cfg = old

    @staticmethod
    def _phase_of(context) -> Any:
        return ((context or {}).get("v24917") or {}).get("overlay_phase")

    # ---------------------------------------------------------------- design
    def _blocked_generation(self, context, folder, exc, stage="UNSPECIFIED"):
        # This error is raised *after* expensive path enumeration. Keep its
        # actual cause in the ordinary block result, not only in a deep file.
        # Distinguish a FlowBundle mask exception from missing mobility data.
        detail = Path(folder) / "V24917_MOBILITY_BLOCKED.json"
        context["projection"] = core.ProjectionResult(rows=[], weighted_rmse=0.0,
            family_summaries=[{"family": f, "converged": False, "proposal_usable": False} for f in zf.FAMILIES])
        context["v24917"] = {"release": RELEASE, "status": "BLOCKED_MOBILITY_DATA",
                             "failure_stage": str(stage), "exception_type": type(exc).__name__,
                             "error": type(exc).__name__ + ":" + str(exc),
                             "detail_path": str(detail), "proposal_usable": False}
        context["v24917_step_model"] = {"keys": [], "delta_full": [], "available": False,
                                       "reason": "BLOCKED_MOBILITY_DATA"}
        context.pop("v24917_ls", None); context.pop("v24917_bd", None)
        rt.write_json(detail, context["v24917"])
        return context

    def generation_design(self, diag, folder):
        previous = getattr(self, "_v24917_generation_reads", None)
        self._v24917_generation_reads = {}
        try:
            return self._generation_design_live(diag, folder)
        finally:
            if previous is None:
                del self._v24917_generation_reads
            else:
                self._v24917_generation_reads = previous

    def _generation_read_key(self):
        manager = getattr(self, "readback_manager", None)
        skims = getattr(self, "v24916_dynamic_skims", None)
        epoch = d11fix.epoch_key(skims.require_current()) if skims is not None else None
        return (id(manager), getattr(manager, "mutation_epoch", None),
                getattr(manager, "assignment_epoch", None),
                getattr(self, "path_epoch_index", None), epoch,
                tuple(self.zones), tuple(self.cfg.get("path_export_dsegs", ())),
                self.cfg.get("expected_zones"))

    def _live_generation_matrices(self):
        scope = getattr(self, "_v24917_generation_reads", None)
        if scope is None:
            return super()._live_generation_matrices()
        key = self._generation_read_key()
        if scope.get("key") != key:
            scope.clear()
            import numpy as np
            matrices = {code: np.array(matrix, dtype=np.float64, copy=True, order="C")
                        for code, matrix in super()._live_generation_matrices().items()}
            if key != self._generation_read_key():
                raise supply_visum.SupplyContractError("V24917_GENERATION_READ_EPOCH_CHANGED")
            for matrix in matrices.values():
                matrix.flags.writeable = False
            scope.update(key=key, matrices=matrices)
        return dict(scope["matrices"])

    def _generation_design_live(self, diag, folder):
        context = super().generation_design(diag, folder)
        if isinstance(context, Mapping) and context.get("incidence") is not None:
            self.v24917_last_incidence = context["incidence"]
        policy = tg.policy_of(self.cfg)
        folder = Path(folder) / "V24917_TARGETED_GENERATION"
        folder.mkdir(parents=True, exist_ok=True)
        # LONGGUARD1: capture the parent before *any* candidate write. A
        # conditional 100..200 FineCDF cannot certify that LONG trips are >=100.
        self._longguard1_parent = longguard.capture(self, diag)
        # TDLONG1: bind a diagnostic >=100 km mask to this live assignment/skims
        # epoch. This is not native support evidence and cannot enable LONG.
        self._tdlong1_native_filter_verified = False
        self._tdlong1_mask = longmask.capture_current(self, diag)
        rt.write_json(folder / "TDLONG1_SOURCE_AUTHORITY.json", self._tdlong1_mask)
        if not hasattr(self, "_longguard1_fine_anchor") and self._longguard1_parent.get("fine_cdf_verified"):
            self._longguard1_fine_anchor = self._longguard1_parent["fine_100_200_rmse"]
        if hasattr(self, "_longguard1_fine_anchor"):
            self._longguard1_parent["fine_cdf_anchor_rmse"] = self._longguard1_fine_anchor
        rt.write_json(folder / "LONGGUARD1_PARENT.json", self._longguard1_parent)
        self.v24917_status["longguard1_parent_status"] = self._longguard1_parent.get("status")
        self.v24917_status["longguard1_parent_short"] = self._longguard1_parent.get("below_min_km")
        long_observed = None
        self._long_generation_parent_vehicle_sha = None
        long_requested = bool(long_opts.load_options()["long_generation_enabled"])
        long_cache_error = ("PARENT_SUPPORT_OR_FINECDF_UNVERIFIED" if long_requested
                            else "LONG_ZONAL_GENERATION_EXPLICITLY_DISABLED")
        if (long_requested
                and (getattr(self, "v24917_ls", None) or {}).get("active")
                and self._longguard1_parent.get("long_generation_permitted")):
            try:
                try:
                    long_observed = long_cache.capture(self)
                except ValueError as exc:
                    if not str(exc).startswith("LONG_CACHE_REFRESH_REQUIRED:"):
                        raise
                    # Same shared-store refresh used by W/S when OD support grows.
                    # Rebuild W/S context too, so both use the same new path basis.
                    self._build_cache(diag, folder / "LONG_SHARED_CACHE_REFRESH", self.snapshot(),
                                      build_sequence_evidence=False, allow_persistent_restore=False)
                    context = super().generation_design(diag, folder / "AFTER_LONG_CACHE_REFRESH")
                    self.v24917_last_incidence = context["incidence"]
                    long_observed = long_cache.capture(self)
                context["_long_cache_receipt"] = {k: long_observed[k] for k in (
                    "status", "binding", "cache_parent_hash", "path_epoch", "parameter_parent_sha256",
                    "cache_revision", "profile_order_sha256")}
                long_cache_error = None
                self._long_generation_parent_vehicle_sha = (
                    long_observed["matrix_values_sha256"]["9305"])
                rt.write_json(folder / "LONG_SHARED_CACHE_INCIDENCE.json", {
                    k: long_observed[k] for k in ("status", "source_status", "binding", "cache_parent_hash",
                        "path_epoch", "profile_parity_max_abs", "matrix_values_sha256", "geometry_identity")})
            except Exception as exc:
                long_cache_error = str(exc)
                context.pop("_long_cache_receipt", None)
                rt.write_json(folder / "LONG_SHARED_CACHE_DEFERRED.json", {"error": long_cache_error})
        phase, ratio = tg.phase_for(diag["d12"]["rows"], policy) if policy else (None, None)
        self.v24917_status.update(last_phase=phase, last_ratio=ratio)
        # Acquire the guard authority independently of the numerical fit. Any
        # fallback below still has to satisfy exactly the same enabled guard.
        stage = "ZONE_AUTHORITY_READ"
        try:
            with self._v24917_overlay(phase) as cfg:
                zone_rows, attrs = supply_visum.base.zone_state_rows(
                    self.visum, self.zones, cfg, zone_indices=self.zone_write_index_by_no,
                    retry_policy=self.com_retry_policy)
            stage = "MOBILITY_OPTIONS"
            mg_opts = mguard.options()
        except Exception as exc:
            return self._blocked_generation(context, folder, exc, stage=stage)
        context["_genfix2_mobility"] = {"zone_rows": copy.deepcopy(zone_rows), "options": mg_opts,
                                        "zone_attributes": attrs}
        self._genfix2_mobility_parent = context["_genfix2_mobility"]
        # MOBILITYZONE1: raw resident FP, not post-sym vehicle trips or counts.
        try:
            mz_rows, mz_families, mz_errors = zguard.enrich(self, zone_rows)
            mz = zguard.capture(mz_rows, mg_opts, mz_families, mz_errors,
                                anchor=getattr(self, "_mobilityzone1_anchor", None))
            if not hasattr(self, "_mobilityzone1_anchor"):
                self._mobilityzone1_anchor = copy.deepcopy(mz)
            else:
                # Newly available optional families may be bound once; existing
                # references are never re-centred on calibrated current values.
                for key, entry in mz["entries"].items():
                    self._mobilityzone1_anchor["entries"].setdefault(key, copy.deepcopy(entry))
            context["_mobilityzone1"] = mz
            self._mobilityzone1_parent = mz
            rt.write_json(folder / "MOBILITYZONE1_PARENT.json", mz)
        except Exception as exc:
            return self._blocked_generation(context, folder, exc, stage="MOBILITYZONE1_PARENT")
        original_projection = context["projection"]
        problem = solution = bd = ls = summary = None
        bounds = {}
        mobility_fit_bounds = None
        fallback = None
        if policy is not None:
            try:
                with self._v24917_overlay(phase) as cfg:
                    bounds = tg.zone_bounds(mb, zone_rows, cfg, self.generation_reference_values)
                    bounds, mobility_fit_bounds = zguard.constrain_fit_bounds(bounds, mz)
                    rows, summary, problem, solution, bd = self._fit_with_boundary(context["incidence"], bounds, cfg, policy)
                    if not rows and long_observed is None:
                        raise RuntimeError("V24917_FIT_PRODUCED_NO_ROWS")
                    if (getattr(self, "v24917_ls", None) or {}).get("active"):
                        try:
                            ls_fit = dict(policy.get("fit", {}))
                            # If baseline already has short LONG trips or the
                            # current NATIVE_CL skim is unverified, defer only
                            # LONG production. SCHOOL and W/S can still run.
                            ls_fit["longguard1_allow_long"] = bool(
                                long_requested and
                                self._longguard1_parent.get("long_generation_permitted"))
                            ls_fit["tdlong1_source_status"] = self._tdlong1_mask.get("status")
                            ls_fit["tdlong1_native_filter_verified"] = False
                            ls_fit["long_cache_incidence"] = long_observed
                            ls_fit["long_mobility_authority"] = mz
                            ls = lsgen.design(self.visum, cfg, self.zones, context["incidence"], problem,
                                              solution, self.generation_reference_values, ls_fit)
                        except Exception as ls_exc:
                            # W/S may continue, but the incomplete LONG/SCHOOL
                            # search cannot certify demand stationarity.
                            ls = {"steps": {}, "summary": {"status": "LS_DESIGN_ERROR", "error": repr(ls_exc),
                                                           "search_complete": False,
                                                           "recovery": "SKIP_LS_THIS_CYCLE_CONTINUE_WS"}}
            except Exception as exc:
                fallback = type(exc).__name__ + ":" + str(exc)
                self.v24917_status["fit_fallbacks"] += 1
                rows = [dict(r) for r in original_projection.rows]
                problem = solution = bd = ls = None
        else:
            rows = [dict(r) for r in original_projection.rows]
        try:
            mask = self._apply_flowbundle_mask(rows, context, policy, phase) if policy else {"rows": rows, "audit": {"status": "PARENT"}}
        except Exception as exc:
            return self._blocked_generation(context, folder, exc, stage="FLOWBUNDLE_MASK")
        try:
            zonal_rows, zonal_projection = zguard.guard_projection(mask["rows"], mz)
            ls = zguard.guard_ls(ls, mz)
            if ls and not (ls.get("summary") or {}).get("long_generation_permitted"):
                ls = lsgen.defer_long(ls, long_cache_error or
                                      ls.get("summary", {}).get("long_deferred_reason", "LONG_FIT_UNAVAILABLE"))
                ls["summary"]["tdlong1_source_status"] = self._tdlong1_mask.get("status")
                ls["summary"]["tdlong1_native_filter_status"] = "NOT_REQUIRED_POST_TD_MASK"
            rows, mobility = mguard.guard(zonal_rows, zone_rows, mg_opts)
            if not mobility.get("passes", mobility.get("status") == "DISABLED"):
                raise ValueError(mobility["status"])
        except Exception as exc:
            return self._blocked_generation(context, folder, exc, stage="MOBILITY_GUARD")
        self.v24917_status["last_mobility_guard"] = mobility
        if solution is not None:
            converged = bool(solution["converged"])
            usable = bool(converged or solution["objective_final"] < solution["objective_initial"])
            summaries = [{"family": f, "method": zf.METHOD, "converged": converged,
                          "solver_converged": converged, "proposal_usable": usable,
                          "fit_solver_converged": converged, "iterations": int(solution["iterations"])} for f in zf.FAMILIES]
        else:
            summaries = copy.deepcopy(original_projection.family_summaries)
            converged = bool(summaries) and all(r.get("converged") for r in summaries)
            usable = converged
        context["v24917_parent_projection_summary"] = {"rows": len(original_projection.rows),
                                                        "family_summaries": copy.deepcopy(original_projection.family_summaries)}
        context["projection"] = core.ProjectionResult(rows=rows, family_summaries=summaries,
                                                      weighted_rmse=0.0 if solution else original_projection.weighted_rmse)
        ls_activation = getattr(self, "v24917_ls", {}) or {}
        ls_deferred = (not ls_activation.get("active", False) and
                       ls_activation.get("reason") not in ("ATTRIBUTES_MISSING", None))
        ls_design_error = (ls or {}).get("summary", {}).get("status") == "LS_DESIGN_ERROR"
        longguard_deferred = bool((getattr(self, "v24917_ls", None) or {}).get("active") and
                                  not self._longguard1_parent.get("long_generation_permitted"))
        tdlong1_deferred = bool((getattr(self, "v24917_ls", None) or {}).get("active") and
                                (not (ls or {}).get("summary", {}).get("long_generation_permitted")
                                 or (ls or {}).get("summary", {}).get("long_solver_converged") is False))
        school_fp_deferred = bool(ls and
            (ls.get("summary") or {}).get("school_generation_search_complete") is False)
        self.v24917_status["school_fp_link_deferred"] = school_fp_deferred
        self.v24917_status["ls_incomplete_current_cycle"] = bool(
            ls_deferred or ls_design_error or longguard_deferred or tdlong1_deferred
            or school_fp_deferred or fallback or not mz["target_satisfied"])
        context["v24917"] = {"release": RELEASE, "phase": phase, "overlay_phase": phase if not fallback else None,
                             "model_obs_ratio": ratio, "raw_fit_summary": summary, "fit_summary": summary,
                             "flowbundle_mask": mask["audit"], "bounds_count": len(bounds),
                             "mobility_fit_bounds": mobility_fit_bounds,
                             "long_school": ((ls or {}).get("summary") or
                                             ({"status": "DEFERRED_READ_UNAVAILABLE",
                                               "activation": dict(ls_activation), "search_complete": False}
                                              if ls_deferred else {"status": "INACTIVE", "activation": dict(ls_activation)})),
                             "long_school_search_incomplete": bool(ls_deferred or ls_design_error or longguard_deferred or tdlong1_deferred or school_fp_deferred or fallback or not mz["target_satisfied"]),
                             "school_fp_link_deferred": school_fp_deferred,
                             "long_generation_requested": long_requested,
                             "long_generation_candidate_eligible": bool(
                                 (ls or {}).get("summary", {}).get("long_generation_permitted")
                                 and context.get("_long_cache_receipt")),
                             "long_composite_td_requested": bool(
                                 long_opts.load_options()["long_composite_td_enabled"]),
                             "longguard1_parent": self._longguard1_parent,
                             "longguard1_long_step_deferred": longguard_deferred,
                             "tdlong1": {"source_status": self._tdlong1_mask.get("status"),
                                         "native_filter_status": "NOT_REQUIRED_POST_TD_MASK",
                                         "long_generation_permitted": not tdlong1_deferred and bool(long_observed),
                                         "search_incomplete": tdlong1_deferred},
                             "boundary": (bd or {}).get("summary"),
                             "mobilityzone1": zonal_projection, "mobility_guard": mobility, "solver_converged": converged, "proposal_usable": usable,
                             "status": "FIT_FALLBACK_PARENT_PROPOSAL" if fallback else "GUARDED_PROPOSAL"}
        context["v24917_ls"], context["v24917_bd"] = ls, bd
        context["_genfix2_effect_model"] = {"problem": problem, "ls": ls, "bd": bd}
        context["v24917_step_model"] = self._step_model(problem, solution, ls, rows=rows, bd=bd)
        if fallback:
            context["v24917"]["error"] = fallback
            rt.write_json(folder / "V24917_FIT_FALLBACK.json", context["v24917"])
        if bd:
            rt.write_json(folder / "V24917_BOUNDARY_STEPS.json", bd)
        rt.write_json(folder / "V24917_FIT_SUMMARY.json", context["v24917"])
        rt.write_csv(folder / "V24917_FIT_PROJECTION_ROWS.csv", rows)
        self.v24917_status["designs"] += 1
        return context

    def _fit_with_boundary(self, incidence, bounds, cfg, policy):
        """W/S zonal fit, jointly with the border-crossing P/A lever when BNDGEN1 is active."""
        fit_cfg = dict(policy.get("fit", {}), nonlinear_pa_repair=True)
        if not bdgen.active():
            rows, summary, problem, solution = zf.fit(incidence, self.zones, bounds, cfg, fit_cfg)
            return rows, summary, problem, solution, None
        current = bdgen.current_values(self.visum, bdgen.STATE["zones"])
        # Boundary P/A volumes retain their own band when ZAHR coefficients expand.
        env = (policy.get("envelope") or {}).get("boundary_reference_multiplier", [0.5, 2.0])
        bd_bounds = bdgen.bounds(current, self.generation_reference_values, cfg, env)
        all_bounds = dict(bounds)
        all_bounds.update(bd_bounds)
        problem = zf.build_problem(incidence, self.zones, all_bounds, cfg)
        bd_margins = bdpa.margins_from_problem(problem, bdgen.STATE["zones"])   # BDPA1
        problem = bdgen.merge_pa(problem, bdgen.STATE["zones"])
        solution = zf.solve(problem, fit_cfg)
        all_rows = zf.projection_rows(problem, solution, float(cfg.get("min_add_log_step", 1.0e-5)))
        rows, steps = bdgen.split_rows(all_rows)
        summary = zf.summary(problem, solution, rows)
        bd = bdgen.design_payload(steps, current)
        bd["margins"] = {k: v for k, v in bd_margins.items() if k in bd["steps"]}
        bd["summary"]["boundary_variables_in_fit"] = int(getattr(problem, "boundary_variables", 0))
        summary["boundary"] = bd["summary"]
        return rows, summary, problem, solution, bd

    @staticmethod
    def _step_model(problem, solution, ls, rows=None, bd=None):
        """First-order response of the requested IMPLEMENTABLE proposal, not stale solver x."""
        try:
            import numpy as np
            from r1_15a2_td_count_blend_v24917 import cl_key
            if rows is None:  # API for explicitly untransformed fit diagnostics
                delta = np.asarray(solution["predicted_change"], dtype=float).copy()
            else:
                if problem is None or not hasattr(problem, "G") or not hasattr(problem, "var_keys"):
                    raise ValueError("FINAL_CANDIDATE_EFFECT_OPERATOR_UNAVAILABLE")
                by = {(r["family"], r["role"], int(r["zone_no"])): float(r.get("log_step", 0)) for r in rows}
                for key, step in ((bd or {}).get("steps") or {}).items():
                    fam, z = key.split("|")
                    by[(fam, "PA", int(z))] = float(step)
                x = np.array([by.get(tuple(k), 0.0) for k in problem.var_keys])
                delta = np.asarray(problem.G @ x, dtype=float)
            if (ls or {}).get("prediction_unavailable_after_guard"):
                raise ValueError("MOBILITYZONE1_LS_EFFECT_OPERATOR_UNAVAILABLE")
            lsp = (ls or {}).get("predicted_change")
            if lsp is not None:
                if len(lsp) != len(delta):
                    raise ValueError("LS_PREDICTION_AXIS_MISMATCH")
                delta += np.asarray(lsp, dtype=float)
            if not np.isfinite(delta).all():
                raise ValueError("NONFINITE_FINAL_PREDICTION")
            keys = [cl_key(r.get("countlocation_no")) for r in problem.profile_rows]
            if len(keys) != len(delta) or len(set(keys)) != len(keys):
                raise ValueError("DUPLICATE_OR_MISMATCHED_PREDICTION_PROFILES")
            return {"keys": keys, "delta_full": delta.tolist(), "available": True,
                    "source": "GENFIX2_GUARDED_PROPOSAL_LINEAR" if rows is not None else "RAW_FIT_DIAGNOSTIC"}
        except Exception as exc:
            return {"keys": [], "delta_full": [], "available": False, "error": repr(exc)}

    def _final_step_prediction(self, context, design, scale):
        import numpy as np
        model = context.get("_genfix2_effect_model") or {}
        problem = model.get("problem")
        if problem is None or not hasattr(problem, "G"):
            return {"keys": [], "delta": [], "available": False, "reason": "NO_FINAL_EFFECT_OPERATOR"}
        effects = {(r["family"], r["role"], int(r["zone_no"])): float(r["implemented_total_log_effect"])
                   for r in design.get("effect_rows", [])}
        for key, value in ((model.get("bd") or {}).get("steps") or {}).items():
            fam, z = key.split("|")
            effects[(fam, "PA", int(z))] = float(scale)*float(value)
        x = np.array([effects.get(tuple(k), 0.0) for k in problem.var_keys])
        delta = np.asarray(problem.G @ x, dtype=float)
        if (model.get("ls") or {}).get("prediction_unavailable_after_guard"):
            return {"keys": [], "delta": [], "available": False,
                    "reason": "MOBILITYZONE1_LS_EFFECT_OPERATOR_UNAVAILABLE"}
        ls_delta = (model.get("ls") or {}).get("predicted_change")
        if ls_delta is not None:
            if len(ls_delta) != len(delta):
                raise supply_visum.SupplyContractError("GENFIX2_LS_PREDICTION_AXIS_MISMATCH")
            delta += float(scale)*np.asarray(ls_delta, dtype=float)
        if not np.isfinite(delta).all():
            raise supply_visum.SupplyContractError("GENFIX2_NONFINITE_FINAL_PREDICTION")
        from r1_15a2_td_count_blend_v24917 import cl_key
        return {"keys": [cl_key(r.get("countlocation_no")) for r in problem.profile_rows],
                "delta": delta.tolist(), "available": True, "scale": float(scale),
                "source": "GENFIX2_FINAL_EFFECT_ROWS_INCLUDING_SALARY_BOUNDARY_LS"}

    # ---------------------------------------------------------- TD acceptance
    def block_gate(self, block, before, after, rows):
        decision = super().block_gate(block, before, after, rows)
        if str(block).upper() == "GENERATION":
            parent = getattr(self, "_longguard1_parent", {"status": "UNVERIFIED"})
            post = longguard.capture(self, after)
            proof = longguard.decide(parent, post, changed_long=longguard.changed_long(rows))
            decision = dict(decision, longguard1=proof,
                            longguard1_parent=parent, longguard1_after=post)
            if longguard.changed_long(rows):
                # A frozen-path incidence model is only a proposal; after the
                # real TG->TD->20A/20B->assignment, require evidence that
                # realized LONG vehicle OD actually responded to the zonal
                # coefficients. The independent FP formula and live 12D/11D
                # acceptance guards remain mandatory.
                try:
                    base_sha = getattr(self, "_long_generation_parent_vehicle_sha", None)
                    if not base_sha:
                        raise RuntimeError("LONG_TG_PARENT_9305_AUTHORITY_MISSING")
                    actual = post_td_mask._read(self, 9305)[1]
                    after_sha = long_cache.matrix_values_hash(actual)
                    if after_sha == base_sha:
                        raise RuntimeError("LONG_TG_NO_NATIVE_VEHICLE_OD_RESPONSE")
                    decision["long_generation_native_response"] = {
                        "status": "CHANGED_FINAL_VEHICLE_OD_MEASURED",
                        "matrix_no": 9305, "parent_sha256": base_sha,
                        "candidate_sha256": after_sha,
                        "vehicle_total_after": float(actual.sum()),
                        "method": "REALIZED_NATIVE_TG_TD_20A_20B_AFTER_80KM_MASK"}
                except Exception as exc:
                    decision["accepted"] = False
                    decision["reasons"] = list(decision.get("reasons") or []) + [
                        "LONG_TG_NATIVE_RESPONSE_UNVERIFIED:" + str(exc)]
                    self.v24917_status["ls_incomplete_current_cycle"] = True
            self.v24917_status["longguard1_last_proof"] = proof
            if not proof["passes"]:
                decision["accepted"] = False
                decision["reasons"] = list(decision.get("reasons") or []) + list(proof["reasons"])
                self.v24917_status["ls_incomplete_current_cycle"] = True
            authority = getattr(self, "_genfix2_mobility_parent", None)
            opts = authority["options"] if authority else mguard.options()
            if opts.get("enabled", True):
                if authority is None:
                    raise supply_visum.SupplyContractError("MOBILITY2_PARENT_AUTHORITY_MISSING")
                live_rows, _ = supply_visum.base.zone_state_rows(
                    self.visum, self.zones, self.cfg, zone_indices=self.zone_write_index_by_no,
                    retry_policy=self.com_retry_policy)
                proof = mguard.check_live(authority["zone_rows"], live_rows, opts)
                mz = getattr(self, "_mobilityzone1_parent", None)
                if mz is not None:
                    try:
                        mz_live, _, read_errors = zguard.enrich(self, live_rows)
                        if any(f not in mz["unavailable"] for f in read_errors):
                            raise ValueError("MOBILITYZONE1_LIVE_READ_UNAVAILABLE:" + repr(read_errors))
                        zonal = zguard.check_live(mz, mz_live)
                    except Exception as exc:
                        zonal = {"release": zguard.RELEASE, "passes": False,
                                 "status": "LIVE_READ_UNVERIFIED", "error": repr(exc)}
                    proof["mobilityzone1"] = zonal
                    proof["passes"] = bool(proof["passes"] and zonal["passes"])
                    if zonal.get("deferred_families") or not zonal["passes"]:
                        self.v24917_status["ls_incomplete_current_cycle"] = True
                decision = dict(decision, mobility_guard_live=proof)
                if not proof["passes"]:
                    decision["accepted"] = False
                    decision["reasons"] = list(decision.get("reasons", [])) + ["MOBILITY2_LIVE_ENVELOPE_REJECTED"]
        if str(block).upper() != "TD_FINECDF_SOFT_REFERENCE":
            return decision
        import r1_15a2_td_count_blend_v24917 as blend
        try:
            out = blend.outer_decision(decision, before, after, self.cfg)
        except Exception as exc:
            # SAFETYFIX1: reject THIS TD trial, never inherit a positive parent
            # verdict without the mandatory shared GEH/11D acceptance.  The
            # existing realization controller treats gate rejection as retryable
            # backtracking, then restores and verifies the accepted parent.
            # No exception escapes here: a recoverable scoring outage must not
            # kill the entire coupled Generation/TD run.
            self.v24917_status["td_blend_outer_failures"] = \
                self.v24917_status.get("td_blend_outer_failures", 0) + 1
            self.v24917_status["td_outer_incomplete_cycle"] = True
            print("R1 V24917 TD BLEND: shared score unavailable; REJECT current trial, continue backtracking: %r" % (exc,))
            out = dict(decision)
            out["accepted"] = False
            out["reasons"] = list(decision.get("reasons") or []) + ["V24917_TD_SHARED_OBJECTIVE_UNAVAILABLE"]
            out["v24917_td_blend_error"] = repr(exc)[:2000]
            out["v24917_td_blend_recovery"] = "REJECT_CURRENT_TRIAL_RETRY_OR_VERIFIED_PARENT_ROLLBACK"
        self.v24917_status["td_blend_decisions"] = self.v24917_status.get("td_blend_decisions", 0) + 1
        return out

    def _apply_flowbundle_mask(self, rows, context, policy, phase):
        factor = float((policy.get("flowbundle_mask_non_target_factor") or {}).get(phase, 1.0))
        snap = context.get("v24916_demand_evidence")
        if factor >= 1.0 or snap is None:
            return {"rows": rows, "audit": {"status": "OFF" if factor >= 1.0 else "NO_EVIDENCE",
                                            "non_target_factor": factor}}
        targets = self._targets_from_snapshot(snap)
        mask_cfg = copy.deepcopy(self.cfg.get("demand_evidence_targeting", {}) or {})
        mask_cfg.setdefault("generation", {})
        mask_cfg["generation"].update(enabled=True, target_step_multiplier=1.0,
                                      non_target_step_multiplier=factor)
        out, audit = target_projection_rows(rows, targets, mask_cfg)
        return {"rows": out, "audit": audit}

    # ------------------------------------------------------- preview / apply
    def _validate_mobility_plan(self, context, design):
        authority = context.get("_genfix2_mobility")
        if authority is None:
            if mguard.options().get("enabled", True):
                raise supply_visum.SupplyContractError("MOBILITY2_PARENT_AUTHORITY_MISSING")
            return {"passes": True, "status": "DISABLED"}
        proof = mguard.check_candidate(design.get("candidate_rows") or [], authority["zone_rows"], authority["options"])
        mz = context.get("_mobilityzone1")
        if mz is not None:
            zonal = zguard.check_candidate(design.get("candidate_rows") or [], mz)
            proof["mobilityzone1"] = zonal
            proof["passes"] = bool(proof["passes"] and zonal["passes"])
            if not proof["passes"]:
                proof["status"] = "REJECTED_FINAL_CANDIDATE_OUTSIDE_ENVELOPE"
        design["genfix2_mobility"] = proof
        return proof

    def generation_preview(self, context, scale):
        if (context.get("v24917") or {}).get("status") == "BLOCKED_MOBILITY_DATA":
            blocked = context["v24917"]
            raise supply_visum.SupplyContractError("MOBILITY2_BLOCKED_DATA_NOT_A_PLATEAU:"
                + str(blocked.get("failure_stage", "UNKNOWN")) + ":"
                + str(blocked.get("error", "NO_DETAIL"))[:1000])
        if not math.isfinite(float(scale)) or not 0 <= float(scale) <= 1:
            raise supply_visum.SupplyContractError("GENFIX2_INVALID_GENERATION_SCALE")
        authority = context.get("_genfix2_mobility")
        with self._v24917_overlay(self._phase_of(context)), bdpa.scope(context.get("v24917_bd")):
            if authority is None:
                design = super().generation_preview(context, scale)
            else:
                # Pure preview from the verified parent. Actual apply re-reads COM
                # and checks byte-identical planned rows BEFORE its first write.
                design = mb.design_generation_candidates(context["projection"].rows, authority["zone_rows"],
                    self.cfg, scale=scale, reference_values=self.generation_reference_values)
                design["zone_attributes_read"] = authority["zone_attributes"]
        extra_all = lsgen.rows_at_scale(context.get("v24917_ls"), scale) + bdgen.rows_at_scale(context.get("v24917_bd"), scale)
        extra = self._without_unverified_long_rows(extra_all, context)
        if longguard.changed_long(extra):
            long_cache.require_current(self, context.get("_long_cache_receipt"))
        if isinstance(design, dict):
            design = dict(design)
            design["candidate_rows"] = list(design.get("candidate_rows") or []) + extra
            long_cache.add_gate_summary(design, context.get("v24917_ls"))
            design["v24917_long_school_rows"] = len(extra)
            self._validate_mobility_plan(context, design)
            design["genfix2_prediction"] = self._final_step_prediction(context, design, scale)
        return design

    def apply_generation(self, context, scale, folder):
        from r1_15a2_supply import canonical_hash
        # Validate the complete final plan before calling inherited mutators.
        preview = self.generation_preview(context, scale)
        proof = preview.get("genfix2_mobility") or {}
        if proof.get("passes") is not True:
            raise supply_visum.SupplyContractError("GENERATION_GATE:MOBILITY2_FINAL_ENVELOPE")
        extra_all = lsgen.rows_at_scale(context.get("v24917_ls"), scale) + bdgen.rows_at_scale(context.get("v24917_bd"), scale)
        extra = self._without_unverified_long_rows(extra_all, context)
        native_long_rows = longguard.changed_long(extra)
        if native_long_rows:
            long_cache.require_current(self, context.get("_long_cache_receipt"))
        mz = context.get("_mobilityzone1")
        if mz is not None and mz["enabled"]:
            # Includes LS values immediately before the first inherited COM write.
            fresh, _ = supply_visum.base.zone_state_rows(
                self.visum, self.zones, self.cfg, zone_indices=self.zone_write_index_by_no,
                retry_policy=self.com_retry_policy)
            fresh, _, read_errors = zguard.enrich(self, fresh)
            if any(f not in mz["unavailable"] for f in read_errors):
                raise supply_visum.SupplyContractError("GENERATION_GATE:MOBILITYZONE1_LIVE_READ_UNAVAILABLE")
            check = zguard.parent_unchanged(mz, fresh)
            if not check["passes"]:
                raise supply_visum.SupplyContractError("GENERATION_GATE:MOBILITYZONE1_STALE_PARENT")
        original = supply_visum.base.generation_candidate
        def checked_design(*args, **kwargs):
            design = original(*args, **kwargs)
            complete = dict(design, candidate_rows=list(design.get("candidate_rows") or []) + extra)
            # Do not mutate the inherited summary shared with the preview builder.
            complete["summary"] = copy.deepcopy(design.get("summary", {}))
            long_cache.add_gate_summary(complete, context.get("v24917_ls"))
            checked = self._validate_mobility_plan(context, complete)
            if not checked["passes"]:
                raise supply_visum.SupplyContractError("GENERATION_GATE:MOBILITY2_FINAL_ENVELOPE")
            if canonical_hash(complete["candidate_rows"]) != canonical_hash(preview["candidate_rows"]):
                raise supply_visum.SupplyContractError("GENFIX2_GENERATION_PLAN_CHANGED_BEFORE_WRITE")
            design["genfix2_mobility"] = checked
            return complete if native_long_rows else design
        # The COM orchestrator is synchronous. Restore the scoped hook even on
        # KeyboardInterrupt; inherited cache invalidation and support-risk hooks remain intact.
        supply_visum.base.generation_candidate = checked_design
        try:
            if native_long_rows:
                long_cache.begin_apply(self, context.get("_long_cache_receipt"))
            with self._v24917_overlay(self._phase_of(context)), bdpa.scope(context.get("v24917_bd")):
                rows = super().apply_generation(context, scale, folder)
        finally:
            supply_visum.base.generation_candidate = original
        if extra and not native_long_rows:
            audit = rt.apply_add_candidate(self.visum, extra, self.zones, zone_indices=self.zone_write_index_by_no,
                retry_policy=self.com_retry_policy, readback_tolerance=self.zone_readback_tolerance)
            if not audit or any(x.get("status") != "OK" for x in audit):
                raise supply_visum.SupplyContractError("V24917_LONG_SCHOOL_READBACK_FAILED")
            rt.write_json(Path(folder) / "V24917_LONG_SCHOOL_ROWS.json", {"scale": scale, "rows": extra})
            rows = list(rows) + extra
        elif extra:
            rt.write_json(Path(folder) / "V24917_LONG_SCHOOL_ROWS.json", {
                "scale": scale, "rows": extra, "writer": "INHERITED_GENERATION_TRANSACTION"})
        rt.write_json(Path(folder) / "GENFIX2_FINAL_MOBILITY_AND_PREDICTION.json",
                      {"mobility": proof, "prediction": preview.get("genfix2_prediction")})
        return rows

    def rollback_diagnostic_equivalence(self, baseline_diag, before_snapshot, folder):
        # A profile-only proof cannot establish that dynamic 11D/skims are equal.
        # Recompute the full diagnostic authority, then use the shared verifier.
        return {"passes": False, "reason": "GENFIX2_REQUIRES_LIVE_12D_11D_COMPONENT_PROOF"}


__all__ = ["VisumAdapter", "RELEASE"]
