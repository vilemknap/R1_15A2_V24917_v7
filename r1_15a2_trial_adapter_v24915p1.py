# -*- coding: utf-8 -*-
"""V24915 PERF1 adapter: exact-safe procedure slicing and rollback proof.

The parent V24915 adapter remains byte-identical.  This child adapter changes
only execution orchestration and always retains the legacy full paths as
fallbacks.
"""
from __future__ import annotations

from pathlib import Path

import r1_15a2_runtime_v1 as rt
import r1_15a2_acceleration_v24915p1 as perf1
from r1_15a2_trial_adapter_v243 import VisumAdapter as _V24915
from r1_15a2_perf_v246 import optional_span


class VisumAdapter(_V24915):
    runtime_backend = "VISUM_COM_V24915_PERF1_EXACT_SAFE"

    def _execute_perf1_plan(self, folder, block, plan):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.last_gap_evidence = None
        rt.write_json(folder / "PROCEDURE_EXECUTION_PLAN.json", plan)
        try:
            with optional_span(
                    self, "VISUM_PROCEDURES_EXECUTE",
                    purpose="V24915_PERF1_PHASE_SPECIFIC_RECOMPUTE",
                    block=str(block), plan_mode=plan.get("mode"),
                    optimized=bool(plan.get("optimized"))):
                with perf1.activate_operation_plan(self.visum, plan) as active_plan:
                    rt.write_json(
                        folder / "PROCEDURE_EXECUTION_PLAN_ACTIVE.json", active_plan)
                    rt.execute_procseq(self.visum, folder)
                    gap = self.gap()
        finally:
            if self.last_gap_evidence is not None:
                rt.write_json(
                    folder / "ASSIGNMENT_QUALITY_SCOPE_EVIDENCE.json",
                    self.last_gap_evidence)
        rt.write_json(folder / "ASSIGNMENT_QUALITY.json", {
            "gap": gap, "block": str(block),
            "plan_mode": plan.get("mode"),
            "optimized": bool(plan.get("optimized")), "passes": True,
        })
        return gap

    def assign_for_block(self, folder, block):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        if not perf1.enabled(self.cfg, "phase_specific_procseq"):
            return super().assign(
                folder, supply_only=(str(block).upper() == "SUPPLY_ADDVAL1"))
        plan = perf1.phase_recompute_plan(self.visum, self.cfg, block)
        return self._execute_perf1_plan(folder, block, plan)

    def rollback_diagnostic_equivalence(self, baseline_diag, before_snapshot, folder):
        return perf1.rollback_diagnostic_equivalence(
            self, baseline_diag, before_snapshot, Path(folder))
