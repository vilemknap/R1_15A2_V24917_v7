# -*- coding: utf-8 -*-
"""V2.4.9.16 trial evaluator using full TG+TD coefficient-ledger rollback.

The evaluation/adoption semantics are copied from the current V24915/V240
controller.  The only intentional change is the demand rollback authority:
all accepted-parent Generation coefficients and all TD b/c parameters are
restored through the retry-safe V24916 transaction. Supply rollback remains
owned by the unchanged V239 transaction delegated by that module.
"""
from __future__ import annotations

from pathlib import Path
import traceback

from r1_15a2_controller_v22 import atomic_json, ledger, diagnostic_hash, assert_freeze
from r1_15a2_inplace_transaction_v24916 import rollback_and_verify
from r1_15a2_overnight_controller_v240 import UserStopRequested, TimeBudgetReached
from r1_15a2_safety_v245 import recovery_scope
from r1_15a2_supply import SupplyContractError, canonical_hash, number


def candidate_signature(block, candidate, rows):
    if block == "SUPPLY_ADDVAL1":
        return canonical_hash([(r.get("key"), r.get("expected_old"), r.get("new"))
                               for r in candidate.get("changes", [])])
    if block == "GENERATION":
        return canonical_hash([(r.get("zone_no"), r.get("attr"), r.get("current"), r.get("proposed"))
                               for r in rows])
    return canonical_hash([(r.get("component"), r.get("candidate_b"), r.get("candidate_c"))
                           for r in rows])


def apply_candidate(adapter, block, candidate, rows, context, before, folder):
    if block == "SUPPLY_ADDVAL1":
        adapter.apply_supply(candidate, before, folder)
        return rows
    if block == "GENERATION":
        got = adapter.apply_generation(context, float(candidate["scale"]), folder)
        if candidate_signature(block, candidate, got) != candidate_signature(block, candidate, rows):
            raise SupplyContractError("GENERATION_PREVIEW_APPLY_MISMATCH")
        return got
    adapter.apply_td(rows)
    return rows


def evaluate_candidate(adapter, cfg, policy, block, candidate, rows, context,
                       before, baseline_diag, baseline_value, anchors, reference,
                       folder, control):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    baseline_diag_hash = diagnostic_hash(baseline_diag)
    mutated = False
    primary_exc = None
    primary_tb = None
    evaluation = None
    rolled_diag = baseline_diag
    # Needed only when read-only diagnostic publication fails after a verified
    # model restore.  The V24916 rollback transaction validates its hash before
    # reusing this object.
    adapter._v249_baseline_diag_for_rollback = baseline_diag
    try:
        control.checkpoint("TRIAL_APPLY", block=block,
                           candidate=candidate_signature(block, candidate, rows))
        mutated = True
        actual_rows = apply_candidate(adapter, block, candidate, rows, context, before, folder)
        control.checkpoint("TRIAL_ASSIGNMENT", block=block)
        gap = adapter.assign(folder / "ASSIGNMENT", supply_only=(block == "SUPPLY_ADDVAL1"))
        if block != "SUPPLY_ADDVAL1":
            adapter.parameter_persistence(block, actual_rows)
        after = adapter.snapshot()
        assert_freeze(before, after, block, rows=actual_rows, candidate=candidate, cfg=cfg)
        control.checkpoint("TRIAL_DIAGNOSTICS", block=block)
        after_diag = adapter.diagnostics(folder / "DIAGNOSTICS", "AFTER")
        if adapter.snapshot() != after:
            raise SupplyContractError("TRIAL_DIAGNOSTICS_CHANGED_MODEL")
        after_value = ledger(after_diag, after, anchors, policy, reference, cfg)
        decision = adapter.block_gate(block, baseline_diag, after_diag, actual_rows)
        improvement = baseline_value["total"] - after_value["total"]
        decision["shared_ledger_before"] = baseline_value
        decision["shared_ledger_after"] = after_value
        decision["shared_objective_improvement"] = improvement
        minimum = number(cfg.get("shared_objective", {}).get("minimum_improvement", 1e-8))
        exploratory_nonmonotonic = (
            block == "GENERATION" and
            decision.get("exploration_nonmonotonic_accepted") is True)
        decision["shared_objective_monotonicity_bypassed"] = exploratory_nonmonotonic
        if improvement <= minimum and not exploratory_nonmonotonic:
            decision["accepted"] = False
            decision.setdefault("reasons", []).append("SHARED_OBJECTIVE_NOT_IMPROVED")
        atomic_json(folder / "ACCEPTANCE.json", decision)
        evaluation = {
            "eligible": bool(decision.get("accepted")),
            "gap": gap,
            "after_snapshot": after,
            "after_diag_hash": diagnostic_hash(after_diag),
            "after_value": after_value,
            "decision": decision,
            "candidate": candidate,
            "rows": actual_rows,
            "signature": candidate_signature(block, candidate, actual_rows),
        }
    except BaseException as exc:
        primary_exc = exc
        primary_tb = traceback.format_exc()
    finally:
        if mutated:
            try:
                with recovery_scope(control, "TRIAL_ROLLBACK"):
                    rb, rolled_diag = rollback_and_verify(
                        adapter, block, before, baseline_diag_hash, diagnostic_hash,
                        folder / "ROLLBACK", candidate_rows=rows, candidate=candidate,
                    )
                atomic_json(folder / "ROLLBACK_SUMMARY.json", rb)
            except Exception as rollback_exc:
                rollback_tb = traceback.format_exc()
                live_state = None
                state_restored = False
                snapshot_error = None
                try:
                    live_state = adapter.snapshot()
                    state_restored = (live_state == before)
                except Exception as snap_exc:
                    snapshot_error = str(snap_exc)
                status = ("ROLLBACK_DIAGNOSTIC_VERIFICATION_FAILED_STATE_RESTORED"
                          if state_restored else "ROLLBACK_FAILED_MANUAL_REOPEN_LATEST_ACCEPTED")
                atomic_json(folder / "TRIAL_RESULT.json", {
                    "status": status,
                    "block": block,
                    "primary_error": None if primary_exc is None else str(primary_exc),
                    "primary_traceback": primary_tb,
                    "rollback_error": str(rollback_exc),
                    "rollback_traceback": rollback_tb,
                    "live_snapshot_matches_before_after_rollback_error": state_restored,
                    "live_snapshot_error": snapshot_error,
                })
                if state_restored:
                    raise SupplyContractError(
                        "V24916_ROLLBACK_DIAGNOSTIC_VERIFICATION_FAILED_STATE_RESTORED:" + block
                    ) from rollback_exc
                raise SupplyContractError(
                    "V24916_ROLLBACK_FAILED_MANUAL_REOPEN_LATEST_ACCEPTED:" + block
                ) from rollback_exc
    if primary_exc is not None:
        atomic_json(folder / "TRIAL_RESULT.json", {
            "status": "FAILED_BUT_ROLLBACK_VERIFIED",
            "block": block, "error": str(primary_exc), "traceback": primary_tb,
        })
        if isinstance(primary_exc, (UserStopRequested, TimeBudgetReached)) or not isinstance(primary_exc, Exception):
            raise primary_exc
        return None, rolled_diag, str(primary_exc)
    atomic_json(folder / "TRIAL_RESULT.json", {
        "status": "ELIGIBLE" if evaluation["eligible"] else "REJECTED",
        "block": block, "signature": evaluation["signature"],
        "decision": evaluation["decision"], "gap": evaluation["gap"],
        "rollback_verified": True,
        "rollback_authority": "ALL_ACCEPTED_PARENT_TG_AND_TD_COEFFICIENTS",
    })
    return evaluation, rolled_diag, None


def adopt_candidate(adapter, cfg, policy, block, best, context, before,
                    baseline_diag, baseline_value, anchors, reference, folder, control):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    candidate = best["candidate"]
    rows = best["rows"]
    baseline_diag_hash = diagnostic_hash(baseline_diag)
    mutated = False
    adapter._v249_baseline_diag_for_rollback = baseline_diag
    try:
        if adapter.snapshot() != before:
            raise SupplyContractError("ADOPTION_NOT_FROM_IDENTICAL_ACCEPTED_PARENT")
        control.checkpoint("ADOPT_REAPPLY", block=block)
        mutated = True
        actual_rows = apply_candidate(adapter, block, candidate, rows, context, before, folder)
        gap = adapter.assign(folder / "ASSIGNMENT", supply_only=(block == "SUPPLY_ADDVAL1"))
        if block != "SUPPLY_ADDVAL1":
            adapter.parameter_persistence(block, actual_rows)
        after = adapter.snapshot()
        assert_freeze(before, after, block, rows=actual_rows, candidate=candidate, cfg=cfg)
        after_diag = adapter.diagnostics(folder / "DIAGNOSTICS", "ADOPTED")
        if adapter.snapshot() != after:
            raise SupplyContractError("ADOPTION_DIAGNOSTICS_CHANGED_MODEL")
        after_value = ledger(after_diag, after, anchors, policy, reference, cfg)
        decision = adapter.block_gate(block, baseline_diag, after_diag, actual_rows)
        improvement = baseline_value["total"] - after_value["total"]
        exploratory_nonmonotonic = (
            block == "GENERATION" and
            decision.get("exploration_nonmonotonic_accepted") is True)
        decision["shared_objective_monotonicity_bypassed"] = exploratory_nonmonotonic
        if (improvement <= number(cfg.get("shared_objective", {}).get("minimum_improvement", 1e-8))
                and not exploratory_nonmonotonic):
            decision["accepted"] = False
            decision.setdefault("reasons", []).append("ADOPTION_SHARED_OBJECTIVE_NOT_IMPROVED")
        reproducible = diagnostic_hash(after_diag) == best["after_diag_hash"]
        if cfg.get("trial_calibration", {}).get("require_reproducible_reapply", True) and not reproducible:
            decision["accepted"] = False
            decision.setdefault("reasons", []).append("ADOPTION_NOT_REPRODUCIBLE")
        atomic_json(folder / "ADOPTION_ACCEPTANCE.json", {
            "decision": decision, "gap": gap, "reproducible_vs_evaluation": reproducible,
            "evaluation_diag_hash": best["after_diag_hash"],
            "adoption_diag_hash": diagnostic_hash(after_diag),
            "evaluation_ledger": best["after_value"], "adoption_ledger": after_value,
        })
        if not decision.get("accepted"):
            raise SupplyContractError("ADOPTION_REJECTED:" + ";".join(decision.get("reasons", [])))
        return after, after_diag, after_value, actual_rows, gap
    except BaseException:
        if mutated:
            with recovery_scope(control, "ADOPTION_ROLLBACK"):
                rollback_and_verify(
                    adapter, block, before, baseline_diag_hash, diagnostic_hash,
                    folder / "ROLLBACK_AFTER_FAILED_ADOPTION",
                    candidate_rows=rows, candidate=candidate,
                )
        raise


__all__ = ["candidate_signature", "apply_candidate", "evaluate_candidate", "adopt_candidate"]
