# -*- coding: utf-8 -*-
"""Active V24916 adapter over the current PERF2C adapter.

Only additive V24916 behaviors are introduced:
1) accepted-state FlowBundle evidence plus assignment-coupled native DIS skims;
2) signed-safe Generation projection damping;
3) TD active-component planning + candidate support-risk gate;
4) dynamic 11D/FineCDF distance authority bound to the fresh assignment epoch.
Everything else, including assignment/readback/snapshot/acceptance, is inherited.
Static R1_OSRM_DIST_KM is retained only as reference provenance.
"""
from __future__ import annotations

import copy
import json
import numpy as np
from pathlib import Path
from typing import Any, Mapping
from types import SimpleNamespace

import r1_15a2_core as core
import r1_15a2_com_compat as com
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError
from r1_15a2_trial_adapter_v24916p2c import VisumAdapter as _V24916P2CBase
from r1_15a2_active_demand_evidence_v24916p2c import ActiveDemandEvidenceBuilder
from r1_15a2_demand_evidence_v24916 import target_projection_rows
from r1_15a2_demand_support_v24916 import audit_live_matrices
from r1_15a2_demand_targeting_hooks_v24916p2c import recompute_generation_post_target_summary
import r1_15a2_runtime_io_hotfix_profile488 as runtime_io_hotfix
import r1_15a2_supply_visum as supply_visum
import r1_15a2_acceleration_v24915p1 as perf1
from r1_15a2_candidate_readback_bundle_v24915p2 import diagnostic_reference_hash
from r1_15a2_dynamic_skim_v24916p2c import DynamicSkimManager, active_native_skim_positions


class VisumAdapter(_V24916P2CBase):
    runtime_backend = "VISUM_COM_V24916_PERF2C_ACTIVE_FLOWBUNDLE_TD_TARGETING"

    def __init__(self, visum: Any, cfg: Mapping[str, Any], control: Any = None):
        super().__init__(visum, cfg, control)
        self._v24916_package_root = Path(__file__).resolve().parent
        configured_authority = str(cfg.get("runtime_v24916_live_authority_path", "") or "").strip()
        if configured_authority:
            authority_path = Path(configured_authority)
        else:
            authority_name = str(
                (cfg.get("v24916_fresh_baseline", {}) or {}).get(
                    "authority_file", "V24916_FRESH0_ISOLATED_LIVE_AUTHORITY.json")
            )
            authority_path = self._v24916_package_root / authority_name
        if self.v24916_enabled and (
            self.v24916_generation_targeting_enabled or self.v24916_td_mask_enabled
        ):
            if not runtime_io_hotfix._is_file(authority_path):
                raise RuntimeError(
                    "V24916_ACTIVE_TARGETING_LIVE_AUTHORITY_MISSING:" + str(authority_path))
            authority = runtime_io_hotfix.critical_runtime_read_json(authority_path)
            if authority.get("passes") is not True:
                raise RuntimeError("V24916_ACTIVE_TARGETING_LIVE_AUTHORITY_NOT_PASSED")
            self.v24916_active_evidence = ActiveDemandEvidenceBuilder(
                self, self._v24916_package_root, authority)
        else:
            self.v24916_active_evidence = None
        self._v24916_last_evidence = None
        self._v24916_current_candidate_folder = None
        self.v24916_dynamic_skims = DynamicSkimManager(self) if (
            self.v24916_enabled and bool((self.cfg.get("v24916_flowbundle_skim_runtime", {}) or {}).get(
                "dynamic_assignment_skim_enabled", False))) else None


    def _refresh_dynamic_skims_after_assignment(self, folder, label, *, skims_already_executed=False):
        """Execute only configured active PrT skim operations after a fresh assignment."""
        if self.v24916_dynamic_skims is None:
            return None
        folder = Path(folder) / "DYNAMIC_ASSIGNMENT_SKIMS"
        folder.mkdir(parents=True, exist_ok=True)
        skim_positions, groups = active_native_skim_positions(self.visum)
        selected = sorted(set(skim_positions) | set(groups))
        inventory = com.operation_rows(self.visum)
        plan = {
            "schema": "R1_15A2_V24916_DYNAMIC_SKIM_PROCSEQ_PLAN_V1",
            "block": str(label),
            "mode": "SKIM_ONLY_AFTER_FRESH_ASSIGNMENT",
            "optimized": True,
            "selected_operation_positions": selected,
            "original_active_operation_positions": sorted(int(r["no"]) for r in inventory if int(r["active"])),
            "dynamic_skim_operation_positions": skim_positions,
            "preserved_group_positions": groups,
            "inventory": [{k:v for k,v in r.items() if k != "object"} for r in inventory],
        }
        rt.write_json(folder / "DYNAMIC_SKIM_PROCEDURE_PLAN.json", plan)
        if not skims_already_executed:
            with perf1.activate_operation_plan(self.visum, plan) as active_plan:
                rt.write_json(folder / "DYNAMIC_SKIM_PROCEDURE_PLAN_ACTIVE.json", active_plan)
                rt.execute_procseq(self.visum, folder)
        else:
            rt.write_json(folder / "DYNAMIC_SKIM_PROCEDURE_PLAN_ACTIVE.json", {
                **plan,
                "mode": "CAPTURE_EXISTING_SKIMS_FROM_JUST_COMPLETED_FULL_SEQUENCE",
                "procedure_execute_repeated": False,
            })
        rm = getattr(self, "readback_manager", None)
        assignment_epoch = int(getattr(rm, "assignment_epoch", 0) or 0)
        token = diagnostic_reference_hash({
            "assignment_epoch": assignment_epoch,
            "gap_evidence": getattr(self, "last_gap_evidence", None),
            "label": str(label),
            "skim_positions": skim_positions,
        })
        epoch = self.v24916_dynamic_skims.capture_after_execution(
            folder, token, skim_positions, self._live_generation_matrices())
        rt.write_json(folder / "DYNAMIC_SKIM_BINDING.json", {
            "assignment_epoch": assignment_epoch,
            "skim_epoch": epoch.epoch,
            "skim_epoch_hash": epoch.epoch_hash,
            "passes": True,
        })
        return epoch

    def assign_for_block(self, folder, block):
        gap = super().assign_for_block(folder, block)
        self._refresh_dynamic_skims_after_assignment(folder, block)
        return gap

    def assign(self, folder, *, supply_only):
        gap = super().assign(folder, supply_only=supply_only)
        self._refresh_dynamic_skims_after_assignment(
            folder, "SUPPLY_ADDVAL1" if supply_only else "FULL_DOWNSTREAM_RECOMPUTE",
            skims_already_executed=not bool(supply_only))
        return gap

    def _dynamic_11d_overlay(self, diag, folder, label):
        if self.v24916_dynamic_skims is None:
            return diag
        epoch = self.v24916_dynamic_skims.require_current()
        from r1_15a2_finecdf_bridge_v24916 import load_reference, DynamicFamilyMetrics
        fine_cfg = (self.cfg.get("coupled_demand", {}) or {}).get("finecdf_td", {}) or {}
        ref, _path, ref_sha = load_reference(self._v24916_package_root, fine_cfg)
        needed = sorted({int(no) for target in ref.TARGETS.values() for no in target["matrix_nos"]})
        matrices = {}
        for no in needed:
            a = np.asarray(self.visum.Net.Matrices.ItemByKey(int(no)).GetValues(), dtype=np.float64)
            if a.shape != (len(self.zones), len(self.zones)) or not np.isfinite(a).all():
                raise SupplyContractError("V24916_DYNAMIC_11D_COMPONENT_MATRIX_INVALID:%s" % no)
            matrices[no] = a
        combined = DynamicFamilyMetrics(
            SimpleNamespace(dynamic_skim_epoch=epoch), ref).evaluate(matrices)

        d11 = copy.deepcopy(diag["d11"])
        meta = copy.deepcopy(d11["summary"])
        rows = [dict(r) for r in (meta.get("component_dist_summary_rows") or [])]
        by_component = {str(r.get("component", "")): r for r in rows}
        for key, metric in combined.items():
            row = by_component.get(key)
            if row is None:
                continue
            row.update({
                "conditioned_volume": float(metric["conditioned_volume_diagnostic"]),
                "total_volume": float(metric["total_volume_diagnostic"]),
                "mean_model_conditioned": float(metric["mean_model_km"]),
                "mean_target": float(metric["mean_target_km"]),
                "l1_distance_half": float(metric["l1_half"]),
                "rmse_share": float(metric["rmse_share"]),
                "dynamic_fine_cdf_rmse": float(metric["fine_cdf_rmse"]),
                "distance_authority": "DYNAMIC_ASSIGNMENT_DIS_KM",
                "dynamic_distance_family": metric["dynamic_distance_family"],
                "dynamic_skim_epoch": int(epoch.epoch),
                "dynamic_skim_epoch_hash": epoch.epoch_hash,
            })
        meta["component_dist_summary_rows"] = rows
        meta["dist_classification_matrix"] = {
            "code": "VISUM_DYNAMIC_ASSIGNMENT_DIS_KM",
            "classification": "DYNAMIC_ASSIGNMENT_PATH_VOLUME_WEIGHTED_DIS",
            "assignment_epoch": int(epoch.assignment_epoch),
            "skim_epoch": int(epoch.epoch),
            "skim_epoch_hash": epoch.epoch_hash,
            "zone_order_sha256": epoch.zone_order_sha256,
            "family_hashes": dict(epoch.family_hashes),
            "readback": {"nonfinite_cells": 0, "negative_cells": 0},
        }
        idp_contract = dict(meta.get("idp_contract") or {})
        idp_contract["backend_metric"] = "DYNAMIC_ASSIGNMENT_DIS_KM"
        idp_contract["static_r1_osrm_dist_km_role"] = "REFERENCE_ONLY_NOT_ACTIVE_CALIBRATION"
        idp_contract["fresh_assignment_required"] = True
        meta["idp_contract"] = idp_contract
        meta["dynamic_distance_authority"] = epoch.summary()

        # Reuse every existing 11D structural/read-only check by presenting the
        # dynamic numbers through the legacy schema, then add an explicit
        # assignment-epoch authority check.  No threshold is relaxed.
        gate_meta = copy.deepcopy(meta)
        gate_meta["dist_classification_matrix"] = {
            "code": "R1_OSRM_DIST_KM",
            "readback": {"nonfinite_cells": 0, "negative_cells": 0},
        }
        gate_contract = dict(gate_meta.get("idp_contract") or {})
        gate_contract["backend_metric"] = "DIST_KM"
        gate_meta["idp_contract"] = gate_contract
        decision = rt.assess_11d_idp_gate(gate_meta, diag["d12"], self.cfg)
        if not decision.get("passes"):
            raise SupplyContractError("V24916_DYNAMIC_11D_STRUCTURAL_GATE_FAIL:" + ",".join(decision.get("failures", [])[:8]))
        decision = dict(decision)
        decision.update({
            "status": "PASS_ATOMIC_IDP_DYNAMIC_ASSIGNMENT_SKIM",
            "distance_authority": "DYNAMIC_ASSIGNMENT_DIS_KM",
            "dynamic_assignment_epoch": int(epoch.assignment_epoch),
            "dynamic_skim_epoch": int(epoch.epoch),
            "dynamic_skim_epoch_hash": epoch.epoch_hash,
            "static_r1_osrm_dist_km_used_for_active_idp": False,
            "static_r1_osrm_dist_km_role": "REFERENCE_ONLY_NOT_ACTIVE_CALIBRATION",
        })
        d11["summary"] = meta
        d11["idp_gate"] = decision
        out = Path(folder) / ("11D_DYNAMIC_ASSIGNMENT_SKIM_" + str(label))
        out.mkdir(parents=True, exist_ok=True)
        rt.write_json(out / "DYNAMIC_11D_SUMMARY.json", meta)
        rt.write_json(out / "DYNAMIC_11D_GATE.json", decision)
        rt.write_json(out / "DYNAMIC_SKIM_EPOCH.json", epoch.summary())
        rt.write_csv(out / "DYNAMIC_COMPONENT_DIST_SUMMARY.csv", rows)
        d11["summary_path"] = str(out / "DYNAMIC_11D_SUMMARY.json")
        diag = dict(diag)
        diag["d11"] = d11
        signals, _ = supply_visum.base.build_td_signals_from_11d(d11, self.cfg)
        diag["signals"] = signals
        diag["dynamic_skim_epoch"] = epoch.summary()
        diag["dynamic_11d_reference_sha256"] = ref_sha
        return diag

    def diagnostics(self, folder, label="CURRENT"):
        diag = super().diagnostics(folder, label=label)
        if self.v24916_dynamic_skims is not None:
            diag = self._dynamic_11d_overlay(diag, folder, label)
        return diag

    @staticmethod
    def _targets_from_snapshot(snap) -> dict[str, Any]:
        payload = dict(snap.target_payload or {})
        row = dict(payload.get("generation_targets") or {})
        allowed = set()
        for item in row.get("allowed_zone_keys", []) or []:
            try:
                fam, role, zone = item
                allowed.add((str(fam), str(role), int(zone)))
            except Exception:
                continue
        row["allowed_zone_keys"] = allowed
        return row

    def generation_design(self, diag, folder):
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        # Exact certified parent design first.  This owns path incidence, solver,
        # saturation, P/A projection, and all scientific design authorities.
        context = super().generation_design(diag, folder)
        if not (self.v24916_enabled and self.v24916_generation_targeting_enabled):
            return context
        snapshot = self.snapshot()
        evidence_folder = folder / "V24916_ACTIVE_TARGETING"
        try:
            snap = self.v24916_active_evidence.build(
                diag, context, evidence_folder / "EVIDENCE", snapshot)
            targets = self._targets_from_snapshot(snap)
            rows, audit = target_projection_rows(
                context["projection"].rows, targets,
                self.cfg.get("demand_evidence_targeting", {}))
            # Preserve solver convergence summaries as solver summaries; compute
            # a separate post-target summary from the actual transformed rows.
            parent_projection = context["projection"]
            context["projection"] = core.ProjectionResult(
                rows=rows,
                family_summaries=copy.deepcopy(parent_projection.family_summaries),
                weighted_rmse=float(parent_projection.weighted_rmse),
            )
            post = recompute_generation_post_target_summary(
                rows, zone_field="zone_no", delta_field="log_step", family_field="family")
            context["v24916_demand_evidence"] = snap
            context["v24916_generation_targeting_audit"] = audit
            context["v24916_generation_post_target_summary"] = post
            self._v24916_last_evidence = snap
            rt.write_json(evidence_folder / "GENERATION_TARGET_APPLY_AUDIT.json", audit)
            rt.write_json(evidence_folder / "GENERATION_POST_TARGET_SUMMARY.json", post)
            rt.write_csv(evidence_folder / "GENERATION_TARGETED_PROJECTION.csv", rows)
        except Exception as exc:
            # Evidence/targeting cannot replace or weaken the certified path-only
            # parent design.  Fail safely to the unchanged parent proposal.
            fallback = {
                "schema": "R1_15A2_V24916_ACTIVE_GENERATION_FALLBACK_V1",
                "status": "GLOBAL_PATH_ONLY_FALLBACK",
                "reason": type(exc).__name__ + ":" + str(exc),
                "parent_projection_unchanged": True,
                "acceptance_authority_changed": False,
            }
            rt.write_json(evidence_folder / "GENERATION_TARGETING_FALLBACK.json", fallback)
            context["v24916_generation_targeting_fallback"] = fallback
        return context

    def td_target_plan(self, diag, folder):
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        if not (self.v24916_enabled and self.v24916_td_mask_enabled):
            plan = {"status": "FEATURE_OFF", "active_components": [],
                    "global_11d_evaluation_required": True}
            rt.write_json(folder / "TD_ACTIVE_COMPONENT_MASK.json", plan)
            return plan
        snapshot = self.snapshot()
        try:
            # A0004 recovery resumes directly at cycle-3 TD.  The parent recovery
            # deliberately forbids cross-run cache restore, while active TD
            # targeting needs path incidence as its numerical parity authority.
            # Build one fresh accepted-state epoch read-only before resumed TD.
            if self.cache is None:
                lineage = dict(getattr(self, "v24916_lineage_context", {}) or {})
                if (lineage.get("resume_substep") == "TD_FINECDF_V17" and
                        lineage.get("fresh_recovery_path_epoch_required") is True):
                    self._build_cache(
                        diag, folder / "RECOVERY_TD_FRESH_PATH_EPOCH", snapshot,
                        build_sequence_evidence=False, allow_persistent_restore=False)
                else:
                    raise RuntimeError("NO_PATH_EPOCH")
            profile_audit = self._sync_live_profiles(
                diag, snapshot, refresh_drivers=False)
            rt.write_json(folder / "PATH_EPOCH_PROFILE_REBIND.json", profile_audit)
            incidence, _export = self.cache.incidence(
                self.cfg, self.actuatable_zones,
                live_od_matrices=self._live_generation_matrices())
            context = {"incidence": incidence}
            snap = self.v24916_active_evidence.build(
                diag, context, folder / "EVIDENCE", snapshot)
            plan = copy.deepcopy(dict((snap.target_payload or {}).get("td_targets") or {}))
            if plan.get("status") != "ACTIVE" or not plan.get("active_components"):
                plan = {"status": "GLOBAL_IDP_FALLBACK", "active_components": [],
                        "global_11d_evaluation_required": True,
                        "reason": "NO_SAFE_ACTIVE_COMPONENT_MASK"}
            else:
                # Hard safety: active targeting may only narrow WORK/SERVICE.
                bad = [str(c) for c in plan.get("active_components", [])
                       if str(c).upper().startswith("LONG") or str(c).upper() == "SCHOOL"]
                if bad:
                    raise RuntimeError("V24916_TD_MASK_FORBIDDEN_COMPONENT:" + ",".join(bad))
                plan["global_11d_evaluation_required"] = True
                plan["finecdf_direction_and_magnitude_authority_preserved"] = True
                plan["acceptance_authority_changed"] = False
            self._v24916_last_evidence = snap
        except Exception as exc:
            plan = {"status": "GLOBAL_IDP_FALLBACK", "active_components": [],
                    "global_11d_evaluation_required": True,
                    "reason": type(exc).__name__ + ":" + str(exc),
                    "acceptance_authority_changed": False}
        rt.write_json(folder / "TD_ACTIVE_COMPONENT_MASK.json", plan)
        return plan

    def candidate_support_risk(self, folder, block="DEMAND"):
        if self.cache is None:
            result = {"schema": "R1_15A2_CANDIDATE_SUPPORT_RISK_V24916",
                      "block": str(block), "status": "NO_PATH_EPOCH",
                      "eligible": False,
                      "decision": "INELIGIBLE_NO_PATH_EPOCH_NO_IMMEDIATE_REENUMERATION",
                      "candidate_induced_reenumeration": False}
            rt.write_json(Path(folder) / "CANDIDATE_SUPPORT_RISK.json", result)
            return result
        return audit_live_matrices(
            self.cache, self._live_generation_matrices(), self.cfg,
            folder=folder, block=block, zone_numbers=self.zones)

    def apply_generation(self, context, scale, folder):
        self._v24916_current_candidate_folder = Path(folder)
        return super().apply_generation(context, scale, folder)

    def block_gate(self, block, before, after, rows):
        decision = super().block_gate(block, before, after, rows)
        if str(block).upper() != "GENERATION":
            return decision
        if not bool(self.v24916_config.get("support_risk_gate_enabled", True)):
            return decision
        folder = self._v24916_current_candidate_folder
        self._v24916_current_candidate_folder = None
        if folder is None:
            raise SupplyContractError("V24916_GENERATION_GATE_WITHOUT_TRIAL_FOLDER")
        risk = self.candidate_support_risk(Path(folder) / "DEMAND_SUPPORT", block=block)
        out = copy.deepcopy(decision)
        out["candidate_support_risk"] = risk
        if risk.get("eligible") is not True:
            out["accepted"] = False
            reasons = list(out.get("reasons", []))
            reasons.append("CANDIDATE_INDUCED_PATH_SUPPORT_RISK")
            out["reasons"] = reasons
        return out

    def v24916_active_telemetry(self) -> dict[str, Any]:
        if self.v24916_active_evidence is None:
            return {"status": "FEATURE_OFF"}
        return {
            "status": "ACTIVE",
            **dict(self.v24916_active_evidence.telemetry),
            **self.v24916_active_evidence.manager.telemetry(),
        }


__all__ = ["VisumAdapter"]
