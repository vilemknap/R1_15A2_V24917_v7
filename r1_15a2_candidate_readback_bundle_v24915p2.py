# -*- coding: utf-8 -*-
"""Exact-state CandidateReadbackBundle for R1 15A2 V24915 PERF2.

The bundle is an ephemeral, read-only materialization of one live Visum state.
It never changes calibration mathematics and is valid only while the exact
session/run/parent/block/candidate and mutation/assignment epochs match.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import copy
import hashlib
import json
import math
import numbers
import time
import uuid
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from r1_15a2_supply import SupplyContractError, canonical_hash

SCHEMA = "R1_15A2_V24915_PERF2_CANDIDATE_READBACK_BUNDLE_V1"
RELEASE = "R1_15A2_V2_4_9_15_PERF2_CANDIDATE_READBACK_BUNDLE_20261019"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deepcopy(value: Any) -> Any:
    return copy.deepcopy(value)


def _diagnostic_hashable(value: Any) -> Any:
    """Return a deterministic JSON-safe view used only for PERF2 diagnostics evidence.

    Live 12D/11D diagnostics legitimately use non-finite sentinels (for example
    an infinite objective when a denominator is zero).  CandidateReadbackBundle
    is a performance/evidence layer and must never turn such a legacy-valid
    diagnostic payload into a calibration failure.  Finite JSON-native values
    are preserved exactly, so existing finite-payload hashes remain unchanged.
    Non-finite reals are encoded explicitly rather than silently coerced.
    """
    if isinstance(value, dict):
        return {k: _diagnostic_hashable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_diagnostic_hashable(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        out = float(value)
        if math.isfinite(out):
            return out
        if math.isnan(out):
            tag = "NAN"
        elif out > 0.0:
            tag = "POS_INF"
        else:
            tag = "NEG_INF"
        return {"__r1_nonfinite_float__": tag}
    if hasattr(value, "tolist"):
        return _diagnostic_hashable(value.tolist())
    return value


def diagnostic_reference_hash(value: Any) -> str:
    return canonical_hash(_diagnostic_hashable(value))


def _bundle_payload_dict(bundle: "CandidateReadbackBundle") -> Dict[str, Any]:
    return {
        "schema": bundle.schema,
        "release": bundle.release,
        "visum_session_token": bundle.visum_session_token,
        "run_token": bundle.run_token,
        "accepted_parent_state_hash": bundle.accepted_parent_state_hash,
        "block": bundle.block,
        "candidate_write_signature": bundle.candidate_write_signature,
        "mutation_epoch": bundle.mutation_epoch,
        "assignment_epoch": bundle.assignment_epoch,
        "readback_epoch": bundle.readback_epoch,
        "capture_started_utc": bundle.capture_started_utc,
        "capture_completed_utc": bundle.capture_completed_utc,
        "complete": bundle.complete,
        "assignment_evidence": _deepcopy(bundle.assignment_evidence),
        "semantic_snapshot_payload": _deepcopy(bundle.semantic_snapshot_payload),
        "parameter_evidence": _deepcopy(bundle.parameter_evidence),
        "profile_volume_payload": _deepcopy(bundle.profile_volume_payload),
        "diagnostics_reference": _deepcopy(bundle.diagnostics_reference),
        "procedure_plan_hash": bundle.procedure_plan_hash,
    }


def bundle_hash(bundle: "CandidateReadbackBundle") -> str:
    return canonical_hash(_bundle_payload_dict(bundle))


@dataclass(frozen=True)
class CandidateReadbackBundle:
    schema: str
    release: str
    visum_session_token: str
    run_token: str
    accepted_parent_state_hash: str
    block: str
    candidate_write_signature: str
    mutation_epoch: int
    assignment_epoch: int
    readback_epoch: int
    capture_started_utc: str
    capture_completed_utc: str
    complete: bool
    assignment_evidence: Mapping[str, Any]
    semantic_snapshot_payload: Mapping[str, Any]
    parameter_evidence: Any
    profile_volume_payload: Any
    diagnostics_reference: Any
    procedure_plan_hash: Optional[str]
    payload_hash: str

    def to_dict(self) -> Dict[str, Any]:
        result = _bundle_payload_dict(self)
        result["payload_hash"] = self.payload_hash
        return result

    def snapshot(self) -> Dict[str, Any]:
        return _deepcopy(dict(self.semantic_snapshot_payload))


class CandidateReadbackManager:
    """State/epoch authority for one adapter instance.

    Publication is atomic: the current bundle is assigned only after all reads,
    epoch checks and payload hashing complete successfully.
    """

    def __init__(self, cfg: Mapping[str, Any], *, telemetry: Any = None,
                 clock: Callable[[], float] = time.monotonic,
                 visum_session_token: Optional[str] = None,
                 run_token: Optional[str] = None) -> None:
        self.cfg = cfg
        self.telemetry = telemetry
        self.clock = clock
        self.visum_session_token = visum_session_token or uuid.uuid4().hex
        self.run_token = run_token or uuid.uuid4().hex
        self.mutation_epoch = 0
        self.assignment_epoch = 0
        self.readback_epoch = 0
        self.assignment_in_progress = False
        self.assignment_completed = False
        self.current: Optional[CandidateReadbackBundle] = None
        self.context: Optional[Dict[str, Any]] = None
        self.pending_diagnostics_reference: Optional[Dict[str, Any]] = None
        # Stable telemetry registry.  Counts are intentionally initialized even
        # when a live Visum run never exercises a particular path, so the final
        # benchmark can distinguish zero from missing instrumentation.
        self.telemetry_counts: Dict[str, int] = {
            "BUNDLE_CAPTURE_TOTAL": 0,
            "BUNDLE_CAPTURE_LINKS": 0,
            "BUNDLE_CAPTURE_DSEGS": 0,
            "BUNDLE_CAPTURE_MATRICES": 0,
            "BUNDLE_CAPTURE_GENERATION": 0,
            "BUNDLE_CAPTURE_TD": 0,
            "BUNDLE_CAPTURE_OPERATIONS": 0,
            "BUNDLE_CAPTURE_PROFILE_VOLUMES": 0,
            "BUNDLE_HIT": 0,
            "BUNDLE_MISS": 0,
            "BUNDLE_INVALIDATE": 0,
            "BUNDLE_FALLBACK": 0,
            "SNAPSHOT_FROM_BUNDLE": 0,
            "LEGACY_SNAPSHOT_TOTAL": 0,
            "MATRIX_GETVALUES_COUNT": 0,
            "COM_LINK_BULK_READ_COUNT": 0,
            "GENERATION_READ_COUNT": 0,
            "TD_READ_COUNT": 0,
            "OPERATION_INVENTORY_READ_COUNT": 0,
        }
        self.telemetry_durations: Dict[str, float] = {
            "BUNDLE_CAPTURE_SECONDS": 0.0,
            "LEGACY_SNAPSHOT_SECONDS": 0.0,
            "PROFILE_VOLUME_READ_SECONDS": 0.0,
            # Exact matrix-only timing requires live COM instrumentation and is
            # deliberately not inferred from whole-snapshot time.
            "MATRIX_GETVALUES_SECONDS": 0.0,
        }

    @property
    def feature_cfg(self) -> Mapping[str, Any]:
        return (self.cfg.get("performance", {}) or {}).get(
            "v24915_perf2_candidate_readback_bundle", {}) or {}

    @property
    def enabled(self) -> bool:
        return self.feature_cfg.get("enabled") is True

    def _event(self, name: str, **details: Any) -> None:
        self.telemetry_counts[name] = int(self.telemetry_counts.get(name, 0)) + 1
        if self.telemetry is not None and hasattr(self.telemetry, "event"):
            self.telemetry.event(name, **details)

    def add_count(self, name: str, value: int = 1, **details: Any) -> None:
        value = int(value)
        if value < 0:
            raise SupplyContractError("V24915P2_NEGATIVE_TELEMETRY_COUNT:" + str(name))
        self.telemetry_counts[name] = int(self.telemetry_counts.get(name, 0)) + value
        if self.telemetry is not None and hasattr(self.telemetry, "event"):
            self.telemetry.event(name, increment=value, **details)

    def add_duration(self, name: str, seconds: float, **details: Any) -> None:
        seconds = float(seconds)
        if seconds < 0:
            raise SupplyContractError("V24915P2_NEGATIVE_TELEMETRY_DURATION:" + str(name))
        self.telemetry_durations[name] = float(self.telemetry_durations.get(name, 0.0)) + seconds
        if self.telemetry is not None and hasattr(self.telemetry, "event"):
            self.telemetry.event(name, elapsed_seconds=seconds, **details)

    def begin_candidate(self, *, accepted_parent_state_hash: str, block: str,
                        candidate_write_signature: str,
                        parameter_evidence: Any = None,
                        baseline_profile_rows: Optional[Sequence[Mapping[str, Any]]] = None) -> None:
        if not isinstance(accepted_parent_state_hash, str) or len(accepted_parent_state_hash) != 64:
            raise SupplyContractError("V24915P2_PARENT_STATE_HASH_INVALID")
        if not isinstance(candidate_write_signature, str) or len(candidate_write_signature) != 64:
            raise SupplyContractError("V24915P2_CANDIDATE_SIGNATURE_INVALID")
        self.invalidate("CANDIDATE_CONTEXT_SWITCH", mutation=False)
        self.context = {
            "accepted_parent_state_hash": accepted_parent_state_hash,
            "block": str(block).upper(),
            "candidate_write_signature": candidate_write_signature,
            "parameter_evidence": _deepcopy(parameter_evidence),
            "baseline_profile_rows": _deepcopy(list(baseline_profile_rows or [])),
            "assignment_evidence": None,
            "procedure_plan": None,
        }
        self.assignment_completed = False
        self.assignment_in_progress = False
        self.pending_diagnostics_reference = None

    def end_candidate(self, reason: str = "CANDIDATE_CONTEXT_END") -> None:
        self.invalidate(reason, mutation=False)
        self.context = None
        self.assignment_completed = False
        self.assignment_in_progress = False
        self.pending_diagnostics_reference = None

    def invalidate(self, reason: str, *, mutation: bool = True) -> None:
        had_bundle = self.current is not None
        self.current = None
        if mutation:
            self.mutation_epoch += 1
        self._event(
            "BUNDLE_INVALIDATE", reason=str(reason), mutation=bool(mutation),
            mutation_epoch=self.mutation_epoch,
            assignment_epoch=self.assignment_epoch, had_bundle=had_bundle)

    def mark_assignment_started(self, *, reason: str, procedure_plan: Any = None) -> None:
        self.invalidate(reason, mutation=True)
        self.assignment_epoch += 1
        self.assignment_in_progress = True
        self.assignment_completed = False
        if self.context is not None:
            self.context["procedure_plan"] = _deepcopy(procedure_plan)
            self.context["assignment_evidence"] = None

    def mark_assignment_completed(self, assignment_evidence: Mapping[str, Any]) -> None:
        if not self.assignment_in_progress:
            raise SupplyContractError("V24915P2_ASSIGNMENT_COMPLETED_WITHOUT_START")
        self.assignment_in_progress = False
        self.assignment_completed = True
        if self.context is not None:
            self.context["assignment_evidence"] = _deepcopy(dict(assignment_evidence))

    def mark_assignment_failed(self, reason: str) -> None:
        self.assignment_in_progress = False
        self.assignment_completed = False
        self.current = None
        self._event("BUNDLE_FALLBACK", reason="ASSIGNMENT_FAILED:" + str(reason))

    def can_capture(self) -> bool:
        return bool(
            self.enabled and self.context is not None and
            self.assignment_completed and not self.assignment_in_progress)

    def capture(self, *, snapshot_factory: Callable[[], Mapping[str, Any]],
                profile_factory: Optional[Callable[[Sequence[Mapping[str, Any]]], Any]] = None) -> CandidateReadbackBundle:
        if not self.can_capture():
            raise SupplyContractError("V24915P2_BUNDLE_CAPTURE_NOT_READY")
        assert self.context is not None
        started_utc = _utc_now()
        started_mutation_epoch = self.mutation_epoch
        started_assignment_epoch = self.assignment_epoch
        started = self.clock()
        # Never retain or publish a prior/partial bundle while a new capture is
        # in progress.  Any exception therefore leaves the manager fail-closed.
        self.current = None
        snapshot_started = self.clock()
        raw_snapshot = snapshot_factory()
        snapshot_elapsed = self.clock() - snapshot_started
        if not isinstance(raw_snapshot, Mapping):
            raise SupplyContractError("V24915P2_LEGACY_SNAPSHOT_NOT_MAPPING")
        snapshot = _deepcopy(dict(raw_snapshot))
        required_snapshot_keys = (
            "addval_hash", "fixed_link_hash", "matrix_hash", "dseg_hash",
            "generation_hash", "td_hash", "operations_hash", "state_hash",
        )
        missing = [key for key in required_snapshot_keys if key not in snapshot]
        if missing:
            raise SupplyContractError(
                "V24915P2_LEGACY_SNAPSHOT_KEYS_MISSING:" + ",".join(missing))
        for key in required_snapshot_keys:
            if not isinstance(snapshot[key], str) or len(snapshot[key]) != 64:
                raise SupplyContractError(
                    "V24915P2_LEGACY_SNAPSHOT_HASH_INVALID:" + key)
        rows = list(self.context.get("baseline_profile_rows") or [])
        profile_payload = None
        profile_elapsed = 0.0
        if rows and profile_factory is not None:
            profile_started = self.clock()
            profile_payload = _deepcopy(profile_factory(rows))
            profile_elapsed = self.clock() - profile_started
        if (self.mutation_epoch != started_mutation_epoch or
                self.assignment_epoch != started_assignment_epoch or
                self.assignment_in_progress):
            raise SupplyContractError("V24915P2_MODEL_MUTATED_DURING_CAPTURE")
        self.readback_epoch += 1
        completed_utc = _utc_now()
        procedure_plan = self.context.get("procedure_plan")
        bundle = CandidateReadbackBundle(
            schema=SCHEMA,
            release=RELEASE,
            visum_session_token=self.visum_session_token,
            run_token=self.run_token,
            accepted_parent_state_hash=self.context["accepted_parent_state_hash"],
            block=self.context["block"],
            candidate_write_signature=self.context["candidate_write_signature"],
            mutation_epoch=started_mutation_epoch,
            assignment_epoch=started_assignment_epoch,
            readback_epoch=self.readback_epoch,
            capture_started_utc=started_utc,
            capture_completed_utc=completed_utc,
            complete=True,
            assignment_evidence=_deepcopy(self.context.get("assignment_evidence") or {}),
            semantic_snapshot_payload=snapshot,
            parameter_evidence=_deepcopy(self.context.get("parameter_evidence")),
            profile_volume_payload=profile_payload,
            diagnostics_reference=_deepcopy(self.pending_diagnostics_reference),
            procedure_plan_hash=(canonical_hash(procedure_plan) if procedure_plan is not None else None),
            payload_hash="",
        )
        bundle = replace(bundle, payload_hash=bundle_hash(bundle))
        # Re-check immediately before publication.
        if (self.mutation_epoch != started_mutation_epoch or
                self.assignment_epoch != started_assignment_epoch or
                self.assignment_in_progress):
            raise SupplyContractError("V24915P2_MODEL_MUTATED_BEFORE_BUNDLE_PUBLICATION")
        self.current = bundle
        capture_elapsed = self.clock() - started
        self._event(
            "BUNDLE_CAPTURE_TOTAL", elapsed_seconds=capture_elapsed,
            mutation_epoch=self.mutation_epoch,
            assignment_epoch=self.assignment_epoch,
            readback_epoch=self.readback_epoch,
            state_hash=snapshot.get("state_hash"),
            has_profile_volume_payload=profile_payload is not None)
        self.add_duration("BUNDLE_CAPTURE_SECONDS", capture_elapsed)
        self.add_duration("LEGACY_SNAPSHOT_SECONDS", snapshot_elapsed)
        self.add_duration("PROFILE_VOLUME_READ_SECONDS", profile_elapsed)
        link_count = len(snapshot.get("addval1") or {})
        dseg_count = len(snapshot.get("dseg_map") or {})
        matrix_count = len(snapshot.get("matrices") or [])
        generation_count = len(snapshot.get("generation_values") or {})
        td_count = len(snapshot.get("td_values") or [])
        self.add_count("BUNDLE_CAPTURE_LINKS", link_count)
        self.add_count("BUNDLE_CAPTURE_DSEGS", dseg_count)
        self.add_count("BUNDLE_CAPTURE_MATRICES", matrix_count)
        self.add_count("BUNDLE_CAPTURE_GENERATION", generation_count)
        self.add_count("BUNDLE_CAPTURE_TD", td_count)
        self.add_count("BUNDLE_CAPTURE_OPERATIONS", 1 if snapshot.get("operations_hash") else 0)
        self.add_count("BUNDLE_CAPTURE_PROFILE_VOLUMES", 1 if profile_payload is not None else 0)
        # Legacy snapshot fingerprints every listed matrix through GetValues
        # exactly once.  This is an exact call-count proxy; matrix-only wall time
        # remains a live benchmark measurement rather than an invented value.
        self.add_count("MATRIX_GETVALUES_COUNT", matrix_count)
        self.add_count("COM_LINK_BULK_READ_COUNT", 1)
        self.add_count("GENERATION_READ_COUNT", 1)
        self.add_count("TD_READ_COUNT", 1)
        self.add_count("OPERATION_INVENTORY_READ_COUNT", 1)
        return bundle

    def _matches_context(self, bundle: CandidateReadbackBundle) -> bool:
        if self.context is None:
            return False
        return (
            bundle.visum_session_token == self.visum_session_token and
            bundle.run_token == self.run_token and
            bundle.mutation_epoch == self.mutation_epoch and
            bundle.assignment_epoch == self.assignment_epoch and
            bundle.accepted_parent_state_hash == self.context["accepted_parent_state_hash"] and
            bundle.block == self.context["block"] and
            bundle.candidate_write_signature == self.context["candidate_write_signature"] and
            bundle.complete is True and
            bundle.payload_hash == bundle_hash(bundle)
        )

    def require_current(self) -> CandidateReadbackBundle:
        bundle = self.current
        if bundle is None or not self._matches_context(bundle):
            self.current = None
            self._event("BUNDLE_MISS", reason="NO_CURRENT_OR_CONTEXT_HASH_MISMATCH")
            raise SupplyContractError("V24915P2_BUNDLE_NOT_CURRENT")
        self._event("BUNDLE_HIT", readback_epoch=bundle.readback_epoch)
        return bundle

    def try_current(self) -> Optional[CandidateReadbackBundle]:
        try:
            return self.require_current()
        except SupplyContractError:
            return None

    def snapshot_from_current(self) -> Dict[str, Any]:
        bundle = self.require_current()
        self._event("SNAPSHOT_FROM_BUNDLE", state_hash=bundle.semantic_snapshot_payload.get("state_hash"))
        return bundle.snapshot()

    def attach_diagnostics(self, diagnostics: Mapping[str, Any]) -> None:
        # Diagnostics are live acceptance authority, whereas this reference is
        # PERF2 evidence only.  Some valid diagnostic summaries intentionally
        # contain +/-inf sentinels.  Hash a deterministic non-finite-safe view
        # and, for any unexpected serialization type, fall back to legacy
        # behavior rather than failing an otherwise valid calibration run.
        try:
            reference = {
                "diagnostics_payload_hash": diagnostic_reference_hash(diagnostics),
                "d12_hash": diagnostic_reference_hash((diagnostics.get("d12") or {})),
                "d11_hash": diagnostic_reference_hash((diagnostics.get("d11") or {})),
                "signals_hash": diagnostic_reference_hash((diagnostics.get("signals") or {})),
                "mutation_epoch": self.mutation_epoch,
                "assignment_epoch": self.assignment_epoch,
            }
        except (TypeError, ValueError, OverflowError) as exc:
            self.pending_diagnostics_reference = None
            self._event(
                "BUNDLE_FALLBACK",
                reason="DIAGNOSTICS_REFERENCE_HASH_UNAVAILABLE",
                error=type(exc).__name__,
            )
            return
        self.pending_diagnostics_reference = reference
        bundle = self.try_current()
        if bundle is None:
            return
        updated = replace(bundle, diagnostics_reference=_deepcopy(reference), payload_hash="")
        updated = replace(updated, payload_hash=bundle_hash(updated))
        self.current = updated

    def update_parameter_evidence(self, value: Any) -> None:
        if self.context is not None:
            self.context["parameter_evidence"] = _deepcopy(value)
        bundle = self.try_current()
        if bundle is None:
            return
        updated = replace(bundle, parameter_evidence=_deepcopy(value), payload_hash="")
        updated = replace(updated, payload_hash=bundle_hash(updated))
        self.current = updated

    def telemetry_snapshot(self) -> Dict[str, Any]:
        return {
            "schema": "R1_15A2_V24915_PERF2_READBACK_TELEMETRY_V1",
            "visum_session_token": self.visum_session_token,
            "run_token": self.run_token,
            "mutation_epoch": self.mutation_epoch,
            "assignment_epoch": self.assignment_epoch,
            "readback_epoch": self.readback_epoch,
            "assignment_in_progress": self.assignment_in_progress,
            "assignment_completed": self.assignment_completed,
            "has_current_bundle": self.current is not None,
            "MODEL_MUTATION_EPOCH": self.mutation_epoch,
            "ASSIGNMENT_EPOCH": self.assignment_epoch,
            "counts": dict(sorted(self.telemetry_counts.items())),
            "durations_seconds": dict(sorted(self.telemetry_durations.items())),
        }


__all__ = [
    "SCHEMA", "RELEASE", "CandidateReadbackBundle", "CandidateReadbackManager",
    "bundle_hash",
]
