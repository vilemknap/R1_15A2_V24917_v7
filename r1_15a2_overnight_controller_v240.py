"""Full overnight trial-assignment calibration controller for R1 15A2 V2.4.0.

Scientific rule: saved-path geometry proposes candidates only. Acceptance always
uses a fresh real Visum recomputation and live diagnostics. Rejected trials are
rolled back in place by restoring only calibrated parameters and recomputing;
LoadVersion is never used.
"""
from __future__ import annotations

from datetime import datetime
from contextlib import contextmanager
from r1_15a2_safety_v245 import recovery_scope
from pathlib import Path
import json
import math
import os
import time
import traceback

from r1_15a2_controller_v22 import (
    atomic_json, build_reference, ledger, diagnostic_hash, assert_freeze,
)
from r1_15a2_inplace_transaction_v239 import rollback_and_verify
from r1_15a2_supply import SupplyContractError, SupplyPolicy, canonical_hash, number
from r1_15a2_perf_v246 import PerformanceTelemetry
import r1_15a2_com_compat as com


class UserStopRequested(RuntimeError):
    pass


class TimeBudgetReached(RuntimeError):
    pass


def _final_snapshot_with_retry(adapter, cfg, label, audit):
    """Read a final semantic snapshot with the explicit final-verification lease.

    This wraps the whole snapshot because a transient COM rejection can occur in
    any one of its read-only subreads.  Retrying restarts the snapshot from the
    beginning and never performs a model write.  ``audit`` is append-only and is
    safe to serialize even when the final attempt is exhausted.
    """
    policy = com.scoped_retry_policy(cfg.get("com_resilience"), "final_verification")
    def on_retry(event):
        audit.append(dict(event, phase="FINAL_STATE_SNAPSHOT_RETRY"))
    def on_exhausted(event):
        audit.append(dict(event, phase="FINAL_STATE_SNAPSHOT_RETRY_EXHAUSTED"))
    return com.com_call_with_retry(
        adapter.snapshot, label=label, retry_policy=policy,
        on_retry=on_retry, on_exhausted=on_exhausted)


def _mark_transient_final_verification_failure(result, exc, active_parent, prior_status):
    checkpoint = (active_parent or {}).get("checkpoint")
    result.update(
        primary_status_before_final_verification=prior_status,
        status="FAILED_TRANSIENT_COM_FINAL_VERIFICATION_UNAVAILABLE_RESTART_FROM_LATEST_ACCEPTED_CHECKPOINT",
        final_state_verified=False,
        live_matches_last_accepted=None,
        final_verification_error=str(exc),
        final_verification_error_type=type(exc).__name__,
        final_verification_transient=True,
        current_session_state_unverified=True,
        manual_reopen_required=False,
        safe_restart_from_latest_accepted_checkpoint=checkpoint is not None,
        restart_policy="START_NEW_RUN_FROM_LATEST_ACCEPTED_CHECKPOINT",
    )
    if checkpoint is not None:
        result["restart_checkpoint"] = checkpoint


class OvernightControl:
    def __init__(self, run_root, cfg, clock=time.monotonic):
        self.root = Path(run_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cfg = cfg
        self.clock = clock
        self.started = clock()
        self._recovery_depth = 0
        self.pending_stop_reason = None
        self.last_write = -1e30
        self.max_seconds = float(cfg.get("trial_calibration", {}).get("max_runtime_seconds", 36000.0))
        self.progress_interval = float(cfg.get("trial_calibration", {}).get("progress_interval_seconds", 2.0))
        self.progress = {
            "schema": "R1_15A2_V240_OVERNIGHT_PROGRESS_V1",
            "status": "RUNNING",
            "phase": "STARTING",
            "production_apply": False,
            "trial_writes": True,
            "load_version_called": False,
        }
        telemetry_cfg = cfg.get("performance", {}).get("telemetry", {})
        self.telemetry = (PerformanceTelemetry(self.root / "PERFORMANCE", clock=clock)
                          if telemetry_cfg.get("enabled") is True else None)
        self.stop_paths = (self.root / "STOP_REQUESTED", self.root.parent / "STOP_REQUESTED")
        self.checkpoint("STARTING", force=True)

    def elapsed(self):
        return self.clock() - self.started

    def remaining(self):
        return max(0.0, self.max_seconds - self.elapsed())

    def checkpoint(self, phase=None, force=False, **details):
        if phase is not None:
            self.progress["phase"] = str(phase)
        self.progress.update(details)
        now = self.clock()
        user_stop = any(p.exists() for p in self.stop_paths)
        time_stop = now - self.started >= self.max_seconds
        if self._recovery_depth:
            if user_stop or time_stop:
                self.pending_stop_reason = "USER_STOP_REQUESTED" if user_stop else "MAX_RUNTIME_SECONDS"
            self.progress.update(status="RECOVERING_MUTATED_STATE", pending_stop_reason=self.pending_stop_reason)
            if force or now - self.last_write >= self.progress_interval:
                self._write(now)
            return
        if user_stop:
            self.progress.update(status="STOP_REQUESTED", stop_reason="USER_STOP_REQUESTED")
            self._write(now)
            raise UserStopRequested("USER_STOP_REQUESTED")
        if now - self.started >= self.max_seconds:
            self.progress.update(status="TIME_BUDGET_REACHED", stop_reason="MAX_RUNTIME_SECONDS")
            self._write(now)
            raise TimeBudgetReached("MAX_RUNTIME_SECONDS")
        if force or now - self.last_write >= self.progress_interval:
            self._write(now)

    @contextmanager
    def recovery(self, reason):
        """Not a new trial: finish restoration despite a cooperative STOP/budget."""
        self._recovery_depth += 1
        previous = self.progress.get("recovery_reason")
        self.progress["recovery_reason"] = str(reason)
        try:
            yield
        finally:
            self._recovery_depth -= 1
            self.progress["recovery_reason"] = previous

    def _write(self, now):
        self.progress.update(
            elapsed_seconds=round(now - self.started, 3),
            remaining_seconds=round(max(0.0, self.max_seconds - (now - self.started)), 3),
            updated=datetime.now().astimezone().isoformat(),
        )
        atomic_json(self.root / "00_PROGRESS.json", self.progress)
        self.last_write = now

    def finish(self, status, **details):
        self.progress.update(status=status, phase="FINISHED", **details)
        self._write(self.clock())
        if self.telemetry is not None:
            self.telemetry.finish()


def _science_hash(cfg):
    ignored = {
        "config_path", "config_sha256", "implementation_hash",
        "long_authority_path", "long_authority_sha256",
        "tg_dependency_contract_path", "tg_dependency_contract_sha256",
    }
    return canonical_hash({k: v for k, v in cfg.items() if k not in ignored})


def _baseline_parameter_guard(before, after):
    for name in ("fixed_link_hash", "dseg_hash", "operations_hash",
                 "addval_hash", "generation_hash", "td_hash"):
        if before[name] != after[name]:
            raise SupplyContractError("BASELINE_RECOMPUTE_CHANGED_PARAMETER_CONTEXT:" + name)


def _accepted_state_cache_transition(adapter, state, diag, *, reason, phase):
    """Retain a V2.4.7 frozen path epoch when supported; otherwise invalidate."""
    if hasattr(adapter, "accepted_state_changed"):
        return adapter.accepted_state_changed(
            state, diag, reason=reason, phase=phase)
    if hasattr(adapter, "invalidate_cache"):
        adapter.invalidate_cache(reason, clear_proof=True)
    return {"retained": False, "reason": reason, "phase": phase}


def _planned_generation_rows(adapter, context, scale):
    preview = adapter.generation_preview(context, scale)
    rows = list(preview.get("candidate_rows", []))
    return preview, rows


def _write_acceptance(path, decision):
    atomic_json(path, decision)


def _candidate_signature(block, candidate, rows):
    if block == "SUPPLY_ADDVAL1":
        return canonical_hash([(r.get("key"), r.get("expected_old"), r.get("new"))
                               for r in candidate.get("changes", [])])
    if block == "GENERATION":
        return canonical_hash([(r.get("zone_no"), r.get("attr"), r.get("current"), r.get("proposed"))
                               for r in rows])
    return canonical_hash([(r.get("component"), r.get("candidate_b"), r.get("candidate_c"))
                           for r in rows])


def _first_sufficient_candidate(cfg, block, baseline_value, evaluation):
    """Return True only for a gate-accepted, materially improving live result.

    This is an explicit search policy, not a convergence claim.  If no trial
    satisfies it, callers must still exhaust the configured candidate set.
    """
    policy = cfg.get("performance", {}).get("first_sufficient", {})
    if policy.get("enabled") is not True or not evaluation or not evaluation.get("eligible"):
        return False
    key = "generation_min_relative_improvement" if block == "GENERATION" else "supply_min_relative_improvement"
    threshold = number(policy.get(key, 0.001), key)
    before = number(baseline_value.get("total"), "baseline objective")
    after = number(evaluation["after_value"].get("total"), "candidate objective")
    relative = (before-after)/max(abs(before), 1.0e-12)
    evaluation["first_sufficient_relative_improvement"] = relative
    evaluation["first_sufficient_threshold"] = threshold
    return relative >= threshold


def _apply_candidate(adapter, block, candidate, rows, context, before, folder):
    if block == "SUPPLY_ADDVAL1":
        adapter.apply_supply(candidate, before, folder)
        return rows
    if block == "GENERATION":
        got = adapter.apply_generation(context, float(candidate["scale"]), folder)
        # The preview used for rollback must describe the exact actual write.
        if _candidate_signature(block, candidate, got) != _candidate_signature(block, candidate, rows):
            raise SupplyContractError("GENERATION_PREVIEW_APPLY_MISMATCH")
        return got
    adapter.apply_td(rows)
    return rows


def _evaluate_candidate(adapter, cfg, policy, block, candidate, rows, context,
                        before, baseline_diag, baseline_value, anchors, reference,
                        folder, control):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    baseline_diag_hash = diagnostic_hash(baseline_diag)
    mutated = False
    primary_exc = None
    primary_tb = None
    evaluation = None
    rolled_diag = baseline_diag
    try:
        control.checkpoint("TRIAL_APPLY", block=block, candidate=_candidate_signature(block, candidate, rows))
        mutated = True  # fail-safe: rollback even if a write routine fails halfway.
        actual_rows = _apply_candidate(adapter, block, candidate, rows, context, before, folder)
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
        _write_acceptance(folder / "ACCEPTANCE.json", decision)
        evaluation = {
            "eligible": bool(decision.get("accepted")),
            "gap": gap,
            "after_snapshot": after,
            "after_diag_hash": diagnostic_hash(after_diag),
            "after_value": after_value,
            "decision": decision,
            "candidate": candidate,
            "rows": actual_rows,
            "signature": _candidate_signature(block, candidate, actual_rows),
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
                    raise SupplyContractError("V240_ROLLBACK_DIAGNOSTIC_VERIFICATION_FAILED_STATE_RESTORED:" + block) from rollback_exc
                raise SupplyContractError("V240_ROLLBACK_FAILED_MANUAL_REOPEN_LATEST_ACCEPTED:" + block) from rollback_exc
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
    })
    return evaluation, rolled_diag, None


def _adopt_candidate(adapter, cfg, policy, block, best, context, before,
                     baseline_diag, baseline_value, anchors, reference, folder, control):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    candidate = best["candidate"]
    rows = best["rows"]
    baseline_diag_hash = diagnostic_hash(baseline_diag)
    mutated = False
    try:
        if adapter.snapshot() != before:
            raise SupplyContractError("ADOPTION_NOT_FROM_IDENTICAL_ACCEPTED_PARENT")
        control.checkpoint("ADOPT_REAPPLY", block=block)
        mutated = True
        actual_rows = _apply_candidate(adapter, block, candidate, rows, context, before, folder)
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
                    folder / "ROLLBACK_AFTER_FAILED_ADOPTION", candidate_rows=rows, candidate=candidate,
                )
        raise


def _save_rotating_checkpoint(adapter, root, accepted_count):
    """Publish new bytes before replacing any checkpoint reference.

    Two retained slots, unique filenames: SaveVersion never overwrites the current
    accepted file and a failed save cannot masquerade as an existing old file.
    """
    import hashlib
    import uuid
    root = Path(root); store = root / "CHECKPOINTS"; store.mkdir(parents=True, exist_ok=True)
    slot = "A" if accepted_count % 2 else "B"
    slot_file = store / ("SLOT_%s.json" % slot)
    previous = None
    if slot_file.is_file():
        previous = json.loads(slot_file.read_text(encoding="utf-8"))
    target = store / ("ACCEPTED_%s_%04d_%s.ver" % (slot, accepted_count, uuid.uuid4().hex[:12]))
    cp = adapter.save(target)
    if not target.is_file() or not target.stat().st_size:
        raise SupplyContractError("CHECKPOINT_SAVE_DID_NOT_CREATE_NONEMPTY_FILE")
    h = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    if cp.get("sha256") != h.hexdigest() or Path(cp.get("path", "")).resolve() != target.resolve():
        raise SupplyContractError("CHECKPOINT_SAVE_METADATA_MISMATCH")
    record = {"accepted_count": accepted_count, "slot": slot, "checkpoint": cp}
    restart_cfg = dict(getattr(adapter, "cfg", {}).get("restart_authority", {}) or {})
    if restart_cfg.get("checkpoint_semantic_sidecar") is True:
        from r1_15a2_restart_v2494 import build_authority, sidecar_path
        semantic = build_authority(
            adapter.snapshot(), version_path=target, raw_ver_sha256=cp.get("sha256"),
            origin="ACCEPTED_CHECKPOINT_AFTER_SAVE")
        semantic_path = sidecar_path(target)
        atomic_json(semantic_path, semantic)
        if json.loads(semantic_path.read_text(encoding="utf-8")) != semantic:
            raise SupplyContractError("CHECKPOINT_SEMANTIC_SIDECAR_READBACK_MISMATCH")
        record["semantic_restart_authority"] = {
            "schema": semantic["schema"],
            "path": str(semantic_path),
            "semantic_state_hash": semantic["semantic_state_hash"],
            "semantic_hashes": semantic["semantic_hashes"],
            "raw_ver_sha_role": semantic["raw_ver_sha_role"],
            "raw_ver_sha_used_for_restart_acceptance": False,
        }
    if hasattr(adapter, "path_epoch_status"):
        epoch = adapter.path_epoch_status()
        record["path_epoch_checkpoint"] = {
            "enabled": epoch.get("enabled"),
            "epoch": epoch.get("epoch"),
            "epoch_origin_state_hash": epoch.get("epoch_origin_state_hash"),
            "live_state_hash": epoch.get("live_state_hash"),
            "basis_hash": epoch.get("basis_hash"),
            "comparison_basis_hash": epoch.get("comparison_basis_hash"),
            "persistent_cache_id": epoch.get("persistent_cache_id"),
            "persistent_cache_dir": epoch.get("persistent_cache_dir"),
        }
    latest_file = root / "LATEST_ACCEPTED_CHECKPOINT.json"
    # CP01: the canonical LATEST pointer is the LAST publish operation.  A
    # failure while writing a slot must not advance the accepted checkpoint.
    # The .ver payload is immutable and already SHA-verified above.
    slot_write_attempted = False
    try:
        slot_write_attempted = True
        atomic_json(slot_file, record)
        if json.loads(slot_file.read_text(encoding="utf-8")) != record:
            raise SupplyContractError("CHECKPOINT_SLOT_PUBLISH_READBACK_MISMATCH")
        atomic_json(latest_file, record)
    except BaseException:
        # Best-effort restore the supplementary slot if the canonical pointer
        # still names the old accepted state.  Never touch the canonical
        # LATEST pointer or delete a possibly-current Visum .ver after failure.
        try:
            latest = json.loads(latest_file.read_text(encoding="utf-8")) if latest_file.exists() else None
            if latest != record and slot_write_attempted:
                if previous is None:
                    slot_file.unlink(missing_ok=True)
                else:
                    atomic_json(slot_file, previous)
        except BaseException:
            # The next run must validate LATEST from actual bytes.  Failure to
            # restore a supplementary slot does not authorize a new checkpoint.
            pass
        raise
    if json.loads(latest_file.read_text(encoding="utf-8")) != record:
        raise SupplyContractError("CHECKPOINT_LATEST_PUBLISH_READBACK_MISMATCH")
    # Garbage collect only this slot's obsolete file after both durable pointers.
    if previous:
        old = Path(previous["checkpoint"]["path"])
        if old.parent.resolve() == store.resolve() and old.name.startswith("ACCEPTED_" + slot + "_") and old != target:
            try:
                old.unlink(missing_ok=True)
                # V2.4.9.4 checkpoints may have an adjacent semantic restart
                # authority. It is auxiliary to the immutable payload and may be
                # retired only after the new slot and canonical LATEST pointer
                # have both been durably published.
                old.with_name(old.name + ".semantic.json").unlink(missing_ok=True)
            except OSError:
                # A locked obsolete file is harmless. Never undo the published state.
                pass
    return cp


def run_overnight_calibration(adapter, cfg, folder, control):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    policy = SupplyPolicy.from_config(cfg)
    tcfg = cfg.get("trial_calibration", {})
    result = {
        "schema": "R1_15A2_V240_FULL_OVERNIGHT_TRIAL_CALIBRATION_V1",
        "repair_release": cfg.get("release", "V2.4.5"),
        "status": "STARTED", "production_apply": False, "trial_writes": True,
        "load_version_called": False, "direct_od_matrix_writes": False,
        "accepted_count": 0, "cycles": [], "blocks": [],
        "final_state_verified": False, "stationarity_confirmed": False,
        "full_network_link_eligibility": True,
        "candidate_edge_limit_is_local_not_global": True,
    }
    cfg_hash = _science_hash(cfg)
    atomic_json(folder / "EFFECTIVE_CONFIG.json", cfg)
    active_parent = None
    diag = None
    state = None
    try:
        control.checkpoint("LIVE_PREFLIGHT", force=True)
        result["preflight"] = adapter.preflight(folder / "PREFLIGHT")

        # Normalize the working copy to a fresh full active Procedure Sequence.
        pre_recompute = adapter.snapshot()
        control.checkpoint("BASELINE_FULL_RECOMPUTE", force=True)
        adapter.assign(folder / "BASELINE_FULL_RECOMPUTE", supply_only=False)
        state = adapter.snapshot()
        _baseline_parameter_guard(pre_recompute, state)
        control.checkpoint("BASELINE_DIAGNOSTICS", force=True)
        diag = adapter.diagnostics(folder / "BASELINE_DIAGNOSTICS", "BASELINE")
        if adapter.snapshot() != state:
            raise SupplyContractError("BASELINE_DIAGNOSTICS_CHANGED_MODEL")
        reference = build_reference(diag, cfg)
        anchors = dict(state["addval1"])
        value = ledger(diag, state, anchors, policy, reference, cfg)
        atomic_json(folder / "OBJECTIVE_REFERENCE.json", reference)
        atomic_json(folder / "ORIGINAL_ADDVAL1_ANCHORS.json", anchors)
        atomic_json(folder / "BASELINE_LEDGER.json", value)
        cp = _save_rotating_checkpoint(adapter, folder, 0)
        active_parent = {"snapshot": state, "diag": diag, "value": value, "checkpoint": cp}

        max_cycles = int(tcfg.get("max_cycles", 100))
        max_accepted = int(tcfg.get("max_accepted_states", 100))
        trials_cfg = tcfg.get("max_trials_per_block", {})
        schedule = list(cfg.get("block_schedule", []))
        if not schedule:
            raise SupplyContractError("V240_EMPTY_BLOCK_SCHEDULE")

        for cycle in range(1, max_cycles + 1):
            # Supply has its own acceptance clock.  Demand outer-cycle numbers
            # must not consume the route-choice exploration horizon.
            if schedule == ["SUPPLY_ADDVAL1"]:
                cfg["runtime_acceptance_supply_cycle"] = int(cycle)
                cfg["runtime_acceptance_outer_cycle"] = int(cycle)
                cfg["runtime_acceptance_scope"] = "SUPPLY_ADDVAL1"
                atomic_json(folder / ("SUPPLY_ACCEPTANCE_CONTEXT_%03d.json" % cycle), {
                    "supply_cycle": int(cycle),
                    "scope": "SUPPLY_ADDVAL1",
                    "policy": cfg.get("supply_route_choice_acceptance", {}),
                })
            control.checkpoint("CYCLE_START", force=True, cycle=cycle,
                               accepted_count=result["accepted_count"], objective=value["total"])
            accepted_this_cycle = 0
            cycle_rec = {"cycle": cycle, "accepted": 0, "objective_start": value["total"], "blocks": []}
            result["cycles"].append(cycle_rec)
            for block in schedule:
                control.checkpoint("BLOCK_DESIGN", force=True, cycle=cycle, block=block,
                                   accepted_count=result["accepted_count"], objective=value["total"])
                if result["accepted_count"] >= max_accepted:
                    result["status"] = "MAX_ACCEPTED_STATES_REACHED"
                    return result
                before = adapter.snapshot()
                if before != state:
                    raise SupplyContractError("ACCEPTED_STATE_MUTATED_BETWEEN_BLOCKS")
                out = folder / ("CYCLE_%03d_%s" % (cycle, block)); out.mkdir(parents=True, exist_ok=True)
                rec = {"cycle": cycle, "block": block, "status": "DESIGNING", "attempts": []}
                result["blocks"].append(rec); cycle_rec["blocks"].append(rec)
                context = None
                try:
                    if block == "SUPPLY_ADDVAL1":
                        design = adapter.supply_design(diag, out / "DESIGN", before)
                        candidates = list(design.get("candidates", []))
                        planned_rows = [None] * len(candidates)
                    elif block == "GENERATION":
                        context = adapter.generation_design(diag, out / "DESIGN")
                        candidates = [{"scale": float(s)} for s in cfg.get("backtracking_scales", [1.0, .5, .25])]
                        planned_rows = []
                        for cand in candidates:
                            preview, rows = _planned_generation_rows(adapter, context, cand["scale"])
                            atomic_json(out / ("GENERATION_PREVIEW_%s.json" % str(cand["scale"]).replace(".", "_")), preview)
                            planned_rows.append(rows)
                    else:
                        candidates = [{"scale": float(s)} for s in cfg.get("backtracking_scales", [1.0, .5, .25])]
                        planned_rows = []
                        for cand in candidates:
                            d = adapter.td_design(diag, block, cand["scale"], out / "DESIGN")
                            planned_rows.append(list(d.get("candidate_rows", [])))
                except Exception as exc:
                    rec.update(status="BLOCKED_DESIGN", error=str(exc), traceback=traceback.format_exc())
                    atomic_json(out / "BLOCK_RESULT.json", rec)
                    raise
                limit = int(trials_cfg.get(block, len(candidates)))
                if limit <= 0:
                    raise SupplyContractError("V245_EMPTY_TRIAL_BUDGET:" + block)
                if limit < len(candidates):
                    rec["candidate_search_truncated"] = True
                candidates = candidates[:limit]
                planned_rows = planned_rows[:len(candidates)]
                if not candidates:
                    rec["status"] = "NO_CANDIDATE"
                    atomic_json(out / "BLOCK_RESULT.json", rec)
                    continue
                best = None
                baseline_diag = diag
                for ordinal, (candidate, rows0) in enumerate(zip(candidates, planned_rows), start=1):
                    control.checkpoint("TRIAL_START", force=True, cycle=cycle, block=block, trial=ordinal)
                    if adapter.snapshot() != before:
                        raise SupplyContractError("TRIAL_NOT_FROM_IDENTICAL_ACCEPTED_PARENT")
                    if block == "SUPPLY_ADDVAL1":
                        rows = []
                    else:
                        rows = list(rows0 or [])
                        if not rows:
                            rec["attempts"].append({"trial": ordinal, "status": "NO_PARAMETER_CANDIDATE", "candidate": candidate})
                            continue
                    ev, rolled_diag, error = _evaluate_candidate(
                        adapter, cfg, policy, block, candidate, rows, context, before,
                        baseline_diag, value, anchors, reference, out / ("TRY_%02d" % ordinal), control,
                    )
                    # Exact rollback guarantee means this is the same accepted state.
                    diag = rolled_diag
                    attempt_rec = {"trial": ordinal, "candidate": candidate,
                                   "status": "FAILED" if ev is None else ("ELIGIBLE" if ev["eligible"] else "REJECTED")}
                    if error:
                        attempt_rec["error"] = error
                    if ev is not None:
                        attempt_rec["ledger"] = ev["after_value"]
                        attempt_rec["decision"] = ev["decision"]
                        if ev["eligible"] and (best is None or ev["after_value"]["total"] < best["after_value"]["total"]):
                            best = ev
                    rec["attempts"].append(attempt_rec)
                    atomic_json(out / "BLOCK_RESULT.json", rec)
                    if ev is None:
                        raise SupplyContractError("V245_TRIAL_ERROR_NOT_CONVERGENCE:" + str(error))
                    if _first_sufficient_candidate(cfg, block, value, ev):
                        rec["early_stop_policy"] = "FIRST_SUFFICIENT_GATE_ACCEPTED"
                        rec["early_stop_trial"] = ordinal
                        rec["early_stop_relative_improvement"] = ev["first_sufficient_relative_improvement"]
                        rec.pop("candidate_search_truncated", None)
                        break
                if best is None:
                    rec["status"] = "NO_ACCEPTED_CANDIDATE"
                    atomic_json(out / "BLOCK_RESULT.json", rec)
                    continue
                control.checkpoint("ADOPT_BEST", force=True, cycle=cycle, block=block)
                try:
                    new_state, new_diag, new_value, adopted_rows, gap = _adopt_candidate(
                        adapter, cfg, policy, block, best, context, before, diag, value,
                        anchors, reference, out / "ADOPTED", control,
                    )
                except Exception as exc:
                    rec.update(status="BEST_CANDIDATE_ADOPTION_FAILED_ROLLED_BACK",
                               error=str(exc), traceback=traceback.format_exc())
                    atomic_json(out / "BLOCK_RESULT.json", rec)
                    # Do not turn an adoption exception into a stationary cycle.
                    raise
                state, diag, value = new_state, new_diag, new_value
                cache_transition = _accepted_state_cache_transition(
                    adapter, state, diag, reason="ACCEPTED_STATE_CHANGED",
                    phase="SUPPLY" if block == "SUPPLY_ADDVAL1" else "DEMAND")
                result["accepted_count"] += 1
                accepted_this_cycle += 1
                cycle_rec["accepted"] = accepted_this_cycle
                cp = _save_rotating_checkpoint(adapter, folder, result["accepted_count"])
                active_parent = {"snapshot": state, "diag": diag, "value": value, "checkpoint": cp}
                accepted_record = {
                    "schema": "R1_15A2_V240_ACCEPTED_STATE_V1",
                    "accepted_count": result["accepted_count"], "cycle": cycle, "block": block,
                    "candidate": best["candidate"], "candidate_signature": best["signature"],
                    "state_hash": state["state_hash"], "diagnostic_hash": diagnostic_hash(diag),
                    "ledger": value, "gap": gap, "checkpoint": cp,
                    "production_apply": False, "trial_working_copy": True,
                }
                atomic_json(folder / "ACCEPTED_STATE.json", accepted_record)
                rec.update(status="ACCEPTED", accepted_count=result["accepted_count"],
                           selected_signature=best["signature"], ledger=value, gap=gap,
                           checkpoint=cp, path_epoch_transition=cache_transition)
                atomic_json(out / "BLOCK_RESULT.json", rec)
                control.checkpoint("BLOCK_ACCEPTED", force=True, cycle=cycle, block=block,
                                   accepted_count=result["accepted_count"], objective=value["total"])
            cycle_rec["objective_end"] = value["total"]
            if accepted_this_cycle == 0:
                if any(r.get("candidate_search_truncated") for r in cycle_rec["blocks"]):
                    result["status"] = "SEARCH_TRUNCATED_NO_CONVERGENCE_CLAIM"
                    return result
                if (schedule == ["SUPPLY_ADDVAL1"] and
                        hasattr(adapter, "path_epoch_plateau_gate")):
                    gate = adapter.path_epoch_plateau_gate(
                        diag, folder / "PATH_EPOCHS" / ("SUPPLY_PLATEAU_%03d" % cycle),
                        state, phase="SUPPLY")
                    cycle_rec["path_epoch_plateau_gate"] = gate
                    if gate.get("stationarity_confirmed") is not True:
                        cycle_rec["status"] = "PATH_EPOCH_REFRESHED_CONTINUE_SUPPLY"
                        atomic_json(folder / ("CYCLE_%03d_PATH_EPOCH_RESULT.json" % cycle), cycle_rec)
                        continue
                result["stationarity_confirmed"] = True
                result["status"] = "CONVERGED_NO_ACCEPTED_IMPROVEMENT"
                return result
        result["status"] = "MAX_CYCLES_REACHED"
        return result
    except UserStopRequested:
        result["status"] = "USER_STOPPED_AT_LAST_VERIFIED_ACCEPTED_STATE"
        return result
    except TimeBudgetReached:
        result["status"] = "TIME_BUDGET_REACHED_AT_LAST_VERIFIED_ACCEPTED_STATE"
        return result
    except Exception as exc:
        result.update(status="FAILED", error=str(exc), traceback=traceback.format_exc())
        # Candidate/adoption transactions own rollback.  The single finalizer
        # below performs a retry-aware semantic read and classifies the session.
        return result
    finally:
        result["elapsed_seconds"] = round(control.elapsed(), 3)
        if active_parent is not None:
            result["latest_accepted_checkpoint"] = active_parent["checkpoint"]
            prior_status = str(result.get("status", "UNKNOWN"))
            retry_audit = []
            try:
                live = _final_snapshot_with_retry(
                    adapter, cfg, "SUPPLY_FINAL_STATE_SNAPSHOT", retry_audit)
                if retry_audit:
                    result["final_verification_com_retry_events"] = retry_audit
                live_matches = live == active_parent["snapshot"]
                result["live_matches_last_accepted"] = live_matches
                if not live_matches:
                    result.update(
                        primary_status_before_final_verification=prior_status,
                        status="FAILED_MANUAL_REOPEN_LATEST_ACCEPTED_REQUIRED",
                        final_state_verified=False,
                        manual_reopen_required=True,
                        safe_restart_from_latest_accepted_checkpoint=True,
                    )
                elif result["status"].startswith("FAILED"):
                    # Primary failure is preserved, but the saved accepted state
                    # is proven intact and is the correct restart authority.
                    result.update(
                        final_state_verified=False,
                        manual_reopen_required=False,
                        safe_restart_from_latest_accepted_checkpoint=True,
                        restart_policy="START_NEW_RUN_FROM_LATEST_ACCEPTED_CHECKPOINT",
                    )
                else:
                    with recovery_scope(control, "SUPPLY_FINAL_READ_ONLY_VERIFICATION"):
                        final_diag = adapter.diagnostics(folder / "FINAL_VERIFICATION", "FINAL")
                    post = _final_snapshot_with_retry(
                        adapter, cfg, "SUPPLY_POST_DIAGNOSTIC_STATE_SNAPSHOT", retry_audit)
                    if retry_audit:
                        result["final_verification_com_retry_events"] = retry_audit
                    if (post != active_parent["snapshot"] or
                            diagnostic_hash(final_diag) != diagnostic_hash(active_parent["diag"])):
                        raise SupplyContractError("V245_FINAL_SUPPLY_DIAGNOSTICS_MISMATCH")
                    result.update(final_state_verified=True,
                                  final_state_hash=active_parent["snapshot"]["state_hash"],
                                  final_diagnostic_hash=diagnostic_hash(final_diag),
                                  manual_reopen_required=False)
            except BaseException as exc:
                if retry_audit:
                    result["final_verification_com_retry_events"] = retry_audit
                if com.is_retryable_com_error(exc) and active_parent.get("checkpoint"):
                    _mark_transient_final_verification_failure(
                        result, exc, active_parent, prior_status)
                else:
                    result.update(
                        primary_status_before_final_verification=prior_status,
                        status="FAILED_FINAL_VERIFICATION_MANUAL_REOPEN_REQUIRED",
                        final_state_verified=False,
                        final_verification_error=str(exc),
                        final_verification_error_type=type(exc).__name__,
                        manual_reopen_required=True,
                        safe_restart_from_latest_accepted_checkpoint=False,
                    )
        atomic_json(folder / "RUN_STATUS.json", result)
