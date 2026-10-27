# -*- coding: utf-8 -*-
"""V2.4.9.16 demand-evidence adapter rebased on the verified V2.4.9.15 branch.

Scientific authority boundaries are intentionally narrow:
* frozen path incidence remains the numerical count-response authority;
* FlowBundle + DIST_KM only target/narrow TG and FineCDF search;
* candidate acceptance remains fresh Visum assignment + live 12D/11D;
* supply design/write behaviour is inherited unchanged from V2.4.8.9.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Sequence
import copy
import hashlib
import json
import time

import r1_15a2_core as core
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError
from r1_15a2_trial_adapter_v243 import VisumAdapter as _V243
from r1_15a2_demand_evidence_v24916 import (
    DemandEvidenceManager, DemandEvidenceSnapshot, build_supported_od,
    build_generation_targets, build_td_targeting, build_shadow_block_classifier,
    evidence_id, path_parity,
)
from r1_15a2_flowbundle_v24916 import (
    FlowBundleAdapter, contract_hash, driver_profile_audit,
)
from r1_15a2_skim_v24916 import SkimAuthorityCache
from r1_15a2_demand_support_v24916 import audit_live_matrices, path_epoch_validity_report


class VisumAdapter(_V243):
    runtime_backend = "VISUM_COM_V24916_FLOWBUNDLE_SKIM_TARGETING_REBASE"

    def __init__(self, visum, cfg, control=None):
        super().__init__(visum, cfg, control=control)
        target_cfg = cfg.get("demand_evidence_targeting", {})
        self.demand_evidence = DemandEvidenceManager(target_cfg)
        self.flowbundle = FlowBundleAdapter(visum, cfg)
        self.skim_authority = SkimAuthorityCache(
            visum, retry_policy=getattr(self, "com_retry_policy", None))
        self._current_candidate_folder = None
        self._last_support_risk = None

    def _evidence_cfg(self) -> Dict[str, Any]:
        return self.demand_evidence.config

    def _profiles_for_demand_evidence(self):
        excluded = set((getattr(self.cache, "duplicate_scope_audit", {}) or {}).get(
            "excluded_conflicting_driver_indices", ()))
        rows = []
        for index, raw in enumerate(getattr(self.cache, "profiles", []) or []):
            row = dict(raw)
            row["v249_duplicate_conflicted_driver"] = index in excluded
            row["v249_profile_index"] = index
            rows.append(row)
        return rows

    def _implementation_hashes(self) -> Dict[str, str]:
        root = Path(__file__).resolve().parent
        names = [
            "r1_15a2_coefficient_ledger_v24916.py",
            "r1_15a2_demand_evidence_v24916.py",
            "r1_15a2_demand_support_v24916.py",
            "r1_15a2_finecdf_bridge_v24916.py",
            "r1_15a2_flowbundle_v24916.py",
            "r1_15a2_inplace_transaction_v24916.py",
            "r1_15a2_overnight_controller_v24916.py",
            "r1_15a2_skim_v24916.py",
            "r1_15a2_trial_adapter_v24916.py",
        ]
        return {name: rt.sha256_file(root / name) for name in names
                if (root / name).is_file()}

    def _path_profile_od_rows(self, collector, live_matrices: Mapping[str, Any]) -> Sequence[Dict[str, Any]]:
        """Recreate current profile×OD flows from the frozen path basis.

        This mirrors the exact live-OD scaling contract used by
        ``TwoModeRouteCollector.incidence``.  It is diagnostic/parity evidence
        only and never replaces the sparse incidence operator.
        """
        profiles = list(getattr(collector, "profiles", []) or [])
        profile_ids = []
        for index, row in enumerate(profiles):
            value = row.get("countlocation_no", row.get("profile_id", index))
            profile_ids.append(str(value))
        out = []
        zone_index = {int(z): i for i, z in enumerate(self.zones)}
        query = """SELECT g.orig,g.dest,h.profile_index,SUM(v.volume*h.multiplicity),
                          COUNT(DISTINCT g.gid)
                   FROM volumes v
                   JOIN geometry g ON g.gid=v.gid
                   JOIN profile_hits h ON h.gid=g.gid
                   WHERE v.dseg=?
                   GROUP BY g.orig,g.dest,h.profile_index
                   ORDER BY g.orig,g.dest,h.profile_index"""
        total_query = """SELECT g.orig,g.dest,SUM(v.volume)
                         FROM volumes v JOIN geometry g ON g.gid=v.gid
                         WHERE v.dseg=? GROUP BY g.orig,g.dest"""
        for raw_code, matrix in sorted((live_matrices or {}).items()):
            code = core.norm_code(raw_code)
            live = matrix
            stored_totals = {(int(o), int(d)): float(v or 0.0)
                             for o, d, v in collector.db.execute(total_query, (code,))}
            for origin, destination, profile_index, stored_through, npaths in collector.db.execute(query, (code,)):
                origin = int(origin); destination = int(destination)
                stored_total = float(stored_totals.get((origin, destination), 0.0))
                oi = zone_index.get(origin); di = zone_index.get(destination)
                if oi is None or di is None:
                    raise SupplyContractError(
                        "V24916_PATH_OD_ZONE_NOT_IN_LIVE_MATRIX_ORDER:%s:%s:%s" %
                        (code, origin, destination))
                live_total = float(live[oi, di])
                scale = live_total / stored_total if stored_total > core.EPS else 0.0
                through = float(stored_through or 0.0) * scale
                pi = int(profile_index)
                out.append({
                    "profile_id": profile_ids[pi] if 0 <= pi < len(profile_ids) else str(pi),
                    "profile_index": pi,
                    "dseg_code": code,
                    "origin": origin,
                    "destination": destination,
                    "path_profile_volume": through,
                    "path_count": int(npaths or 0),
                    "live_od_volume": live_total,
                    "stored_od_volume": stored_total,
                })
        return out

    @staticmethod
    def _component_rows(diag: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        return (((diag or {}).get("d11") or {}).get("summary") or {}).get(
            "component_dist_summary_rows", []) or []

    def _build_demand_evidence(self, diag, context, folder, snapshot):
        started = time.perf_counter()
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        state_hash = str(snapshot["state_hash"])
        reused = self.demand_evidence.snapshot_for(state_hash)
        if reused is not None:
            self.demand_evidence.write_outputs(folder)
            return reused

        cfg = self._evidence_cfg()
        if cfg.get("enabled") is not True:
            snap = DemandEvidenceSnapshot(
                state_hash=state_hash, status="PATH_ONLY_FALLBACK",
                evidence_id=evidence_id({"state_hash": state_hash, "disabled": True}),
                path_epoch=self.path_epoch_index,
                path_basis_hash=self._epoch_basis(),
                path_basis_comparison_hash=self._epoch_comparison_basis(),
                fallback_reason="FEATURE_DISABLED")
            self.demand_evidence.set_snapshot(snap)
            self.demand_evidence.write_outputs(folder)
            return snap

        incidence = context["incidence"]
        supported = build_supported_od(incidence.get("variables", []))
        live_matrices = self._live_generation_matrices()
        path_rows = self._path_profile_od_rows(self.cache, live_matrices)
        fallback_reason = None
        fb_rows = []
        fb_status = []
        skim_summary = {}
        parity = {"status": "PATH_ONLY_FALLBACK", "decision": "PATH_ONLY_FALLBACK",
                  "reason": "NOT_EVALUATED"}
        generation_targets = {"status": "PATH_ONLY_FALLBACK", "od_rows": [],
                              "zone_rows": [], "allowed_zone_keys": set()}
        td_targets = {"status": "GLOBAL_IDP_FALLBACK", "active_components": [],
                      "frozen_components": ["SCHOOL", "LONG_COMPOSITE"],
                      "global_11d_evaluation_required": True}
        contract_digest = ""
        profile_rows = self._profiles_for_demand_evidence()
        ecfg = cfg["flowbundle"]
        driver_audit = driver_profile_audit(
            profile_rows, int(ecfg.get("max_profiles", 30)),
            float(ecfg.get("min_profile_geh", 10.0)),
            float(ecfg.get("min_profile_abs_residual", 300.0)))
        public_driver_audit = [
            {k: v for k, v in row.items() if not str(k).startswith("_")}
            for row in driver_audit
        ]
        try:
            skim = self.skim_authority.required_distance(state_hash)
            skim_summary = skim.to_summary()
            optional_summary = self.skim_authority.load_optional(
                state_hash, cfg.get("flowbundle_target_dsegs", []),
                cfg.get("skim", {}).get("optional_codes",
                    ["TT0", "TTC", "IMP", "DIS", "DID", "AD1", "VP0", "VPC"]))
            skim_summary["optional_shadow"] = optional_summary
            rt.write_json(folder / "OPTIONAL_SKIM_SHADOW_AUTHORITY.json", optional_summary)
            rt.write_csv(folder / "OPTIONAL_SKIM_SELECTED.csv", optional_summary.get("selected", []))
            rt.write_csv(folder / "OPTIONAL_SKIM_MISSING.csv", optional_summary.get("missing", []))
            rt.write_csv(folder / "OPTIONAL_SKIM_ERRORS.csv", optional_summary.get("errors", []))
            edges = cfg.get("td", {}).get("distance_bin_edges_km", [])
            skim_summary.update({
                "matrix_no": 9697,
                "matrix_code": "R1_OSRM_DIST_KM",
                "rows": len(skim.zone_numbers),
                "cols": len(skim.zone_numbers),
                "nonfinite": len(skim.zone_numbers) ** 2 - skim.finite_count,
                "negative": skim.finite_count - skim.nonnegative_count,
                "bin_contract_sha256": hashlib.sha256(json.dumps(
                    list(edges), separators=(",", ":")).encode("utf-8")).hexdigest(),
                "source_role": "SAME_DISTANCE_AUTHORITY_AS_11D_FINECDF",
            })
            extraction = self.flowbundle.extract_snapshot(
                profile_rows, state_hash, skim.zone_numbers,
                distance_lookup=skim.value)
            fb_rows = list(extraction.rows)
            fb_status = list(extraction.profile_status)
            contract_digest = contract_hash(extraction.contract)
            if extraction.status != "ACTIVE":
                fallback_reason = extraction.fallback_reason or extraction.status
            else:
                parity = path_parity(
                    fb_rows, path_rows,
                    float(ecfg.get("path_parity_relative_tolerance", 0.02)),
                    float(ecfg.get("path_parity_absolute_tolerance", 2.0)),
                    float(ecfg.get("od_parity_relative_tolerance", 0.10)),
                    float(ecfg.get("od_parity_absolute_tolerance", 5.0)))
                passing_keys = set(parity.get("passing_profile_dseg_keys", []) or [])
                target_fb_rows = [r for r in fb_rows
                                  if int(r.get("targeting_eligible", 0) or 0) == 1
                                  and "%s|%s" % (
                                      str(r.get("profile_id", r.get("countlocation_no", ""))),
                                      core.norm_code(r.get("dseg_code"))) in passing_keys]
                if parity.get("status") == "PATH_ONLY_FALLBACK" or not target_fb_rows:
                    fallback_reason = "FLOWBUNDLE_PATH_PARITY_FAILED"
                else:
                    generation_targets = build_generation_targets(target_fb_rows, supported, cfg)
                    td_targets = build_td_targeting(target_fb_rows, self._component_rows(diag), cfg)
                    if generation_targets.get("status") != "ACTIVE":
                        fallback_reason = "NO_SAFE_GENERATION_TARGETS"
        except Exception as exc:
            # Demand evidence is an observability/targeting layer.  A failure must
            # never corrupt or replace the verified V24915 path-only design.
            fallback_reason = "DEMAND_EVIDENCE_BUILD_FAILED:%s" % repr(exc)[:1000]
            fb_status.append({"status": "PATH_ONLY_FALLBACK", "error": repr(exc)[:1200]})

        status = "ACTIVE" if fallback_reason is None else "PATH_ONLY_FALLBACK"
        if status != "ACTIVE":
            generation_targets = {"status": "PATH_ONLY_FALLBACK", "od_rows": [],
                                  "zone_rows": [], "allowed_zone_keys": set(),
                                  "reason": fallback_reason}
            td_targets = {"status": "GLOBAL_IDP_FALLBACK", "active_components": [],
                          "frozen_components": ["SCHOOL", "LONG_COMPOSITE"],
                          "global_11d_evaluation_required": True,
                          "reason": fallback_reason}
        optional_summary = (skim_summary.get("optional_shadow", {})
                            if isinstance(skim_summary, Mapping) else {})
        classifier = build_shadow_block_classifier(
            profile_rows, fb_rows, td_targets, parity, optional_summary)
        rt.write_json(folder / "SHADOW_BLOCK_CLASSIFIER.json",
                      {k: v for k, v in classifier.items() if k != "rows"})
        rt.write_csv(folder / "SHADOW_BLOCK_CLASSIFIER.csv", classifier.get("rows", []))
        path_validity = path_epoch_validity_report(
            path_rows, self.skim_authority, folder=folder)

        payload = {
            "state_hash": state_hash,
            "path_epoch": self.path_epoch_index,
            "path_basis_hash": self._epoch_basis(),
            "path_basis_comparison_hash": self._epoch_comparison_basis(),
            "driver_set": [r.get("profile_id") for r in fb_rows],
            "flowbundle_contract_hash": contract_digest,
            "distance_skim_hash": skim_summary.get("matrix_sha256"),
            "flowbundle_path_parity": parity,
            "generation_target_count": len(generation_targets.get("zone_rows", [])),
            "td_active_components": td_targets.get("active_components", []),
            "shadow_classifier_counts": classifier.get("class_counts", {}),
            "path_epoch_validity_status": path_validity.get("status"),
        }
        snap = DemandEvidenceSnapshot(
            state_hash=state_hash, status=status, evidence_id=evidence_id(payload),
            path_epoch=self.path_epoch_index,
            path_basis_hash=self._epoch_basis(),
            path_basis_comparison_hash=self._epoch_comparison_basis(),
            flowbundle_rows=fb_rows, flowbundle_status=fb_status,
            driver_profiles=public_driver_audit,
            path_profile_od_rows=list(path_rows),
            generation_targets=generation_targets, td_targets=td_targets,
            parity=parity, skim_summary=skim_summary,
            flowbundle_contract_hash=contract_digest,
            config_sha256=str(self.cfg.get("config_sha256", "")),
            implementation_hashes=self._implementation_hashes(),
            source_hashes={
                "path_basis_hash": str(self._epoch_basis() or ""),
                "path_basis_comparison_hash": str(self._epoch_comparison_basis() or ""),
                "distance_matrix_sha256": str(skim_summary.get("matrix_sha256", "")),
                "flowbundle_contract_hash": contract_digest,
            },
            timings_seconds={"build_total": time.perf_counter() - started},
            fallback_reason=fallback_reason)
        self.demand_evidence.set_snapshot(snap)
        self.demand_evidence.write_outputs(folder)
        rt.write_json(folder / "DEMAND_EVIDENCE_STATE_BINDING.json", payload)
        return snap

    def generation_design(self, diag, folder):
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        # Build the exact V24915 design first.  This preserves all path-cache,
        # incidence, solver, saturation and P/A feasibility authorities.
        context = super().generation_design(diag, folder)
        snapshot = self.snapshot()
        evidence_folder = folder / "DEMAND_EVIDENCE"
        snap = self._build_demand_evidence(diag, context, evidence_folder, snapshot)
        if snap.status == "ACTIVE":
            rows, audit = self.demand_evidence.generation_projection(
                context["projection"].rows)
            context["projection"] = core.ProjectionResult(
                rows=rows,
                family_summaries=copy.deepcopy(context["projection"].family_summaries),
                weighted_rmse=float(context["projection"].weighted_rmse))
        else:
            rows = [dict(r) for r in context["projection"].rows]
            audit = {"schema": "R1_15A2_GENERATION_TARGET_APPLY_AUDIT_V24916",
                     "status": "PATH_ONLY_FALLBACK", "reason": snap.fallback_reason,
                     "input_rows": len(rows), "output_rows": len(rows),
                     "path_incidence_values_modified": False}
        rt.write_json(evidence_folder / "GENERATION_TARGET_APPLY_AUDIT.json", audit)
        rt.write_csv(evidence_folder / "GENERATION_TARGETED_PROJECTION.csv", rows)
        context["demand_evidence"] = snap
        return context

    def td_target_plan(self, diag, folder):
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        snapshot = self.snapshot()
        snap = self.demand_evidence.snapshot_for(snapshot["state_hash"])
        if snap is None:
            # After accepted Generation the state changed.  Build a fresh exact-state
            # snapshot.  Reuse the already frozen path cache; no re-enumeration.
            if self.cache is None:
                plan = {"status": "GLOBAL_IDP_FALLBACK", "active_components": [],
                        "reason": "NO_PATH_EPOCH"}
                rt.write_json(folder / "TD_ACTIVE_COMPONENT_MASK.json", plan)
                return plan
            profile_audit = self._sync_live_profiles(
                diag, snapshot, refresh_drivers=False)
            rt.write_json(folder / "PATH_EPOCH_PROFILE_REBIND.json", profile_audit)
            incidence, _export = self.cache.incidence(
                self.cfg, self.actuatable_zones,
                live_od_matrices=self._live_generation_matrices())
            fake_context = {"incidence": incidence}
            snap = self._build_demand_evidence(diag, fake_context, folder, snapshot)
        else:
            self.demand_evidence.write_outputs(folder)
        plan = self.demand_evidence.td_mask()
        rt.write_json(folder / "TD_ACTIVE_COMPONENT_MASK_APPLIED.json", plan)
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
        result = audit_live_matrices(
            self.cache, self._live_generation_matrices(), self.cfg,
            folder=folder, block=block, zone_numbers=self.zones)
        self._last_support_risk = result
        return result

    def apply_generation(self, context, scale, folder):
        self._current_candidate_folder = Path(folder)
        try:
            return super().apply_generation(context, scale, folder)
        finally:
            # Kept until block_gate consumes it; the controller is synchronous.
            pass

    def block_gate(self, block, before, after, rows):
        decision = super().block_gate(block, before, after, rows)
        if str(block).upper() != "GENERATION":
            return decision
        folder = self._current_candidate_folder
        self._current_candidate_folder = None
        if folder is None:
            raise SupplyContractError("V24916_GENERATION_GATE_WITHOUT_TRIAL_FOLDER")
        risk = self.candidate_support_risk(Path(folder) / "DEMAND_SUPPORT", block=block)
        if risk.get("eligible") is not True:
            out = copy.deepcopy(decision)
            out["accepted"] = False
            reasons = list(out.get("reasons", []))
            reasons.append("CANDIDATE_INDUCED_PATH_SUPPORT_RISK")
            out["reasons"] = reasons
            out["candidate_support_risk"] = risk
            return out
        decision["candidate_support_risk"] = risk
        return decision


__all__ = ["VisumAdapter"]
