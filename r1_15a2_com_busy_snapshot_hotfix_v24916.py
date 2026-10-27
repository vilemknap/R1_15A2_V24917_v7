# -*- coding: utf-8 -*-
"""V24916 read-only COM-busy retry for startup and semantic snapshots.

Ported from the approved Aggressive FIX1 COMBUSY hotfix, but bound directly to
V24916/PERF2C.  Only transient RPC_E_CALL_REJECTED and
RPC_E_SERVERCALL_RETRYLATER failures are retried.  The patch is read-only and
never starts another Visum instance, loads a version, executes a procedure, or
writes OD/matrix data.
"""
from __future__ import annotations

from functools import wraps
import logging
from typing import Any, Callable, Dict

import r1_15a2_com_compat as com
import r1_15a2_supply_visum as supply_visum
import r1_15a2_single_pass_snapshot_v24915p2c as optimized
import r1_15a2_trial_adapter_v24915p2c as adapter_mod

RELEASE = "R1_15A2_V24916_COMBUSY_SNAPSHOT_RETRY_V1_20261023"
SCOPE = "startup_snapshot_read"
DEFAULTS = {
    "max_attempts": 64,
    "initial_delay_seconds": 0.15,
    "backoff_factor": 1.5,
    "max_delay_seconds": 1.5,
    "max_elapsed_seconds": 75.0,
}

_ACTIVE = False


def policy_payload() -> Dict[str, Any]:
    return {
        "status": "ACTIVE",
        "release": RELEASE,
        "scope": SCOPE,
        "default_retry": dict(DEFAULTS),
        "execution": "READ_ONLY_TRANSIENT_COM_RPC_ONLY",
        "patched_read_paths": [
            "r1_15a2_supply_visum.VisumAdapter.read_links",
            "r1_15a2_supply_visum.VisumAdapter.snapshot",
            "r1_15a2_single_pass_snapshot_v24915p2c.single_pass_exact_snapshot",
            "r1_15a2_trial_adapter_v24915p2c.single_pass_exact_snapshot",
        ],
        "calibration_math_changed": False,
        "assignment_method_changed": False,
        "visum_writes_added": False,
    }


def _policy(adapter: Any) -> Dict[str, Any]:
    raw = dict(
        getattr(adapter, "com_retry_policy", None)
        or (getattr(adapter, "cfg", {}) or {}).get("com_resilience", {})
        or {}
    )
    merged = com.scoped_retry_policy(raw, SCOPE)
    if merged.get("enabled") is True:
        original_scope = (raw.get("scoped_policies", {}) or {}).get(SCOPE, {}) or {}
        for key, value in DEFAULTS.items():
            if key not in original_scope:
                merged[key] = value
    return merged


def _telemetry(adapter: Any, name: str, label: str, event: Dict[str, Any]) -> None:
    try:
        records = getattr(adapter, "r1_com_busy_read_retry_events", None)
        if records is None:
            records = []
            setattr(adapter, "r1_com_busy_read_retry_events", records)
        if len(records) < 1000:
            records.append(
                {
                    "event": name,
                    "label": label,
                    "com_call_label": event.get("label"),
                    **{k: v for k, v in event.items() if k != "label"},
                }
            )
        if name == "RETRY" and event.get("attempt") in (1, 5, 15, 30, 50):
            logging.warning(
                "%s %s: COM busy (%s), retry %s/%s, pause %.3fs",
                RELEASE,
                label,
                event.get("hresult"),
                event.get("next_attempt"),
                event.get("max_attempts"),
                event.get("delay_seconds", 0.0),
            )
        if name == "EXHAUSTED":
            logging.error(
                "%s %s: COM remained busy after %s attempts (%s)",
                RELEASE,
                label,
                event.get("attempt"),
                event.get("error"),
            )
    except Exception:
        pass


def _read_retry(adapter: Any, label: str, call: Callable[[], Any]) -> Any:
    # snapshot() calls read_links(); one outer read owns the bounded retry lease.
    depth = int(getattr(adapter, "_r1_combusy_read_retry_depth", 0))
    if depth:
        return call()
    setattr(adapter, "_r1_combusy_read_retry_depth", depth + 1)
    try:
        return com.com_call_with_retry(
            call,
            label="%s:%s" % (SCOPE, label),
            retry_policy=_policy(adapter),
            on_retry=lambda event: _telemetry(adapter, "RETRY", label, event),
            on_exhausted=lambda event: _telemetry(adapter, "EXHAUSTED", label, event),
        )
    finally:
        setattr(adapter, "_r1_combusy_read_retry_depth", depth)


def _method_retry(method: Callable[..., Any], label: str) -> Callable[..., Any]:
    @wraps(method)
    def wrapped(adapter: Any, *args: Any, **kwargs: Any) -> Any:
        return _read_retry(adapter, label, lambda: method(adapter, *args, **kwargs))

    wrapped._r1_v24916_combusy_original = method  # type: ignore[attr-defined]
    return wrapped


def _optimized_retry(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def wrapped(adapter: Any) -> Any:
        return _read_retry(
            adapter,
            "PERF2C_SINGLE_PASS_SNAPSHOT",
            lambda: method(adapter),
        )

    wrapped._r1_v24916_combusy_original = method  # type: ignore[attr-defined]
    return wrapped


def activate() -> Dict[str, Any]:
    """Install the read-only patch once before the first live snapshot."""
    global _ACTIVE
    if _ACTIVE:
        return {"active": True, "release": RELEASE, "idempotent": True, **policy_payload()}

    for name in ("read_links", "snapshot"):
        original = getattr(supply_visum.VisumAdapter, name)
        if getattr(original, "_r1_v24916_combusy_original", None) is not None:
            raise RuntimeError("V24916_COMBUSY_ALREADY_PATCHED_DIFFERENT_ACTIVATION:" + name)
        setattr(
            supply_visum.VisumAdapter,
            name,
            _method_retry(original, "SUPPLY_VISUM_" + name.upper()),
        )

    original_optimized = optimized.single_pass_exact_snapshot
    if getattr(original_optimized, "_r1_v24916_combusy_original", None) is not None:
        raise RuntimeError("V24916_COMBUSY_OPTIMIZED_ALREADY_PATCHED")
    wrapped_optimized = _optimized_retry(original_optimized)
    optimized.single_pass_exact_snapshot = wrapped_optimized
    # PERF2C imported this function by value, not through the source module.
    adapter_mod.single_pass_exact_snapshot = wrapped_optimized

    _ACTIVE = True
    return {"active": True, "release": RELEASE, "idempotent": False, **policy_payload()}


__all__ = [
    "RELEASE",
    "SCOPE",
    "DEFAULTS",
    "activate",
    "policy_payload",
    "_policy",
    "_read_retry",
]
