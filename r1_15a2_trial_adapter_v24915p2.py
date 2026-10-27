# -*- coding: utf-8 -*-
"""V24915 PERF2 adapter: exact-state CandidateReadbackBundle integration."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import r1_15a2_runtime_v1 as rt
import r1_15a2_acceleration_v24915p1 as perf1
from r1_15a2_candidate_readback_bundle_v24915p2 import CandidateReadbackManager
from r1_15a2_trial_adapter_v24915p1 import VisumAdapter as _PERF1
from r1_15a2_perf_v246 import optional_span
from r1_15a2_supply import SupplyContractError, canonical_hash


class VisumAdapter(_PERF1):
    runtime_backend = "VISUM_COM_V24915_PERF2_CANDIDATE_READBACK_BUNDLE"

    def __init__(self, visum, cfg, control=None):
        # Preserve the exact constructor contract of the V24915/PERF1 parent.
        # The production launcher passes OvernightControl as the third
        # positional argument so that telemetry/checkpoints remain attached to
        # the adapter.  PERF2 is an orchestration-only child and must not narrow
        # this public runtime API.
        super().__init__(visum, cfg, control)
        self.readback_manager = CandidateReadbackManager(
            cfg, telemetry=getattr(self, "telemetry", None))

    def _sync_readback_telemetry(self):
        self.readback_manager.telemetry = getattr(self, "telemetry", None)

    def begin_candidate_readback_context(
            self, accepted_parent_state_hash: str, block: str,
            candidate_write_signature: str, *, parameter_evidence: Any = None,
            baseline_profile_rows: Optional[Sequence[Mapping[str, Any]]] = None):
        self._sync_readback_telemetry()
        self.readback_manager.begin_candidate(
            accepted_parent_state_hash=accepted_parent_state_hash,
            block=block,
            candidate_write_signature=candidate_write_signature,
            parameter_evidence=parameter_evidence,
            baseline_profile_rows=baseline_profile_rows)

    def end_candidate_readback_context(self, reason="CANDIDATE_CONTEXT_END"):
        self.readback_manager.end_candidate(reason)

    def invalidate_candidate_readback(self, reason: str, *, mutation: bool = True):
        self._sync_readback_telemetry()
        self.readback_manager.invalidate(reason, mutation=mutation)

    def legacy_snapshot_from_live_visum(self):
        self._sync_readback_telemetry()
        self.readback_manager._event("LEGACY_SNAPSHOT_TOTAL")
        return super().snapshot()

    def _profile_payload_factory(self, rows):
        return perf1.count_profile_signature(self.visum, self.cfg, rows)

    def capture_candidate_readback(self):
        self._sync_readback_telemetry()
        return self.readback_manager.capture(
            snapshot_factory=self.legacy_snapshot_from_live_visum,
            profile_factory=self._profile_payload_factory)

    def current_candidate_readback(self):
        return self.readback_manager.require_current()

    def snapshot_from_bundle(self, bundle=None):
        if bundle is not None:
            current = self.readback_manager.require_current()
            if current.payload_hash != bundle.payload_hash:
                raise SupplyContractError("V24915P2_REQUESTED_BUNDLE_NOT_CURRENT")
        return self.readback_manager.snapshot_from_current()

    def snapshot(self):
        self._sync_readback_telemetry()
        if not self.readback_manager.enabled:
            return self.legacy_snapshot_from_live_visum()
        bundle = self.readback_manager.try_current()
        if bundle is not None:
            return self.readback_manager.snapshot_from_current()
        if self.readback_manager.can_capture():
            try:
                bundle = self.capture_candidate_readback()
                optimized = bundle.snapshot()
                if self.readback_manager.feature_cfg.get(
                        "require_exact_snapshot_parity", True) is True:
                    # Capture was built from the legacy payload.  Reconstructing it
                    # must therefore be bit-for-bit/canonical-object identical.
                    if optimized != dict(bundle.semantic_snapshot_payload):
                        raise SupplyContractError("V24915P2_BUNDLE_PARITY_FAIL")
                return self.readback_manager.snapshot_from_current()
            except Exception:
                self.readback_manager._event(
                    "BUNDLE_FALLBACK", reason="CAPTURE_OR_PARITY_FAILURE")
                if self.readback_manager.feature_cfg.get(
                        "fallback_to_legacy", True) is not True:
                    raise
        return self.legacy_snapshot_from_live_visum()

    def _execute_perf1_plan(self, folder, block, plan):
        self._sync_readback_telemetry()
        self.readback_manager.mark_assignment_started(
            reason="PROCEDURES_EXECUTE:" + str(block), procedure_plan=plan)
        try:
            gap = super()._execute_perf1_plan(folder, block, plan)
        except BaseException as exc:
            self.readback_manager.mark_assignment_failed(str(exc))
            raise
        self.readback_manager.mark_assignment_completed({
            "gap": gap,
            "gap_evidence": getattr(self, "last_gap_evidence", None),
            "block": str(block),
            "supply_only": str(block).upper() == "SUPPLY_ADDVAL1",
            "procedure_plan": plan,
        })
        return gap

    def assign_for_block(self, folder, block):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        if perf1.enabled(self.cfg, "phase_specific_procseq"):
            plan = perf1.phase_recompute_plan(self.visum, self.cfg, block)
            return self._execute_perf1_plan(folder, block, plan)
        # Fail-safe legacy path is still epoch-bound.
        self.readback_manager.mark_assignment_started(
            reason="PROCEDURES_EXECUTE_LEGACY:" + str(block),
            procedure_plan={"mode": "FULL_SEQUENCE_FALLBACK", "block": str(block)})
        try:
            gap = super(_PERF1, self).assign(
                folder, supply_only=(str(block).upper() == "SUPPLY_ADDVAL1"))
        except BaseException as exc:
            self.readback_manager.mark_assignment_failed(str(exc))
            raise
        self.readback_manager.mark_assignment_completed({
            "gap": gap,
            "gap_evidence": getattr(self, "last_gap_evidence", None),
            "block": str(block),
            "supply_only": str(block).upper() == "SUPPLY_ADDVAL1",
            "procedure_plan": {"mode": "FULL_SEQUENCE_FALLBACK"},
        })
        return gap

    def assign(self, folder, *, supply_only):
        block = "SUPPLY_ADDVAL1" if supply_only else "FULL_DOWNSTREAM_RECOMPUTE"
        self.readback_manager.mark_assignment_started(
            reason="PROCEDURES_EXECUTE_LEGACY:" + block,
            procedure_plan={"mode": "FULL_SEQUENCE_FALLBACK", "block": block})
        try:
            gap = super().assign(folder, supply_only=supply_only)
        except BaseException as exc:
            self.readback_manager.mark_assignment_failed(str(exc))
            raise
        self.readback_manager.mark_assignment_completed({
            "gap": gap,
            "gap_evidence": getattr(self, "last_gap_evidence", None),
            "block": block,
            "supply_only": bool(supply_only),
            "procedure_plan": {"mode": "FULL_SEQUENCE_FALLBACK"},
        })
        return gap

    def apply_supply(self, candidate, snapshot, folder):
        self.invalidate_candidate_readback("SUPPLY_CANDIDATE_WRITE", mutation=True)
        return super().apply_supply(candidate, snapshot, folder)

    def apply_generation(self, context, scale, folder):
        self.invalidate_candidate_readback("GENERATION_CANDIDATE_WRITE", mutation=True)
        return super().apply_generation(context, scale, folder)

    def apply_td(self, rows):
        self.invalidate_candidate_readback("TD_CANDIDATE_WRITE", mutation=True)
        return super().apply_td(rows)

    def restore(self, checkpoint, snapshot):
        self.invalidate_candidate_readback("LOADVERSION", mutation=True)
        return super().restore(checkpoint, snapshot)

    def diagnostics(self, folder, label="CURRENT"):
        # The 12D helper may create/update CountLocation UDAs.  The semantic
        # snapshot excludes them, but PERF2 deliberately treats any COM write as
        # a mutation and rebuilds the bundle afterwards.
        self.invalidate_candidate_readback(
            "LIVE_12D_11D_DIAGNOSTICS_POTENTIAL_COM_WRITE", mutation=True)
        result = super().diagnostics(folder, label)
        self.readback_manager.attach_diagnostics(result)
        return result

    def parameter_persistence(self, block, rows):
        result = super().parameter_persistence(block, rows)
        self.readback_manager.update_parameter_evidence({
            "block": str(block),
            "rows": rows,
            "status": "LIVE_READBACK_OK",
        })
        return result

    def rollback_diagnostic_equivalence(self, baseline_diag, before_snapshot, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            pre = self.snapshot()
            bundle = self.readback_manager.require_current()
            signature = bundle.profile_volume_payload
            post = self.snapshot()
            passes = bool(
                pre == before_snapshot and post == before_snapshot and
                isinstance(signature, Mapping) and signature.get("passes") is True)
            result = {
                "schema": "R1_15A2_V24915_PERF2_ROLLBACK_DIAGNOSTIC_REUSE_PROOF_V1",
                "passes": passes,
                "reason": None if passes else "BUNDLE_PROFILE_OR_SNAPSHOT_PROOF_MISSING",
                "snapshot_equal_before_signature": pre == before_snapshot,
                "snapshot_equal_after_signature": post == before_snapshot,
                "matrix_hash_equal_authority": pre.get("matrix_hash") == before_snapshot.get("matrix_hash"),
                "generation_hash_equal_authority": pre.get("generation_hash") == before_snapshot.get("generation_hash"),
                "td_hash_equal_authority": pre.get("td_hash") == before_snapshot.get("td_hash"),
                "d11_reuse_basis": "CURRENT_CANDIDATE_BUNDLE_EXACT_SEMANTIC_SNAPSHOT",
                "d12_reuse_basis": "BUNDLE_CAPTURED_498_PROFILE_12_DSEG_BULK_SIGNATURE",
                "full_diagnostics_fallback_required": not passes,
                "bundle_payload_hash": bundle.payload_hash,
                "signature": signature,
            }
            rt.write_json(folder / "ROLLBACK_DIAGNOSTIC_REUSE_PROOF.json", result)
            if passes:
                return result
        except Exception as exc:
            rt.write_json(folder / "ROLLBACK_DIAGNOSTIC_REUSE_BUNDLE_FALLBACK.json", {
                "passes": False,
                "reason": "BUNDLE_REUSE_PROOF_EXCEPTION",
                "error": str(exc),
            })
        return super().rollback_diagnostic_equivalence(
            baseline_diag, before_snapshot, folder)

    def readback_telemetry(self):
        return self.readback_manager.telemetry_snapshot()


__all__ = ["VisumAdapter"]
