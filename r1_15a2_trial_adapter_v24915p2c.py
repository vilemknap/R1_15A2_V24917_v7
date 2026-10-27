# -*- coding: utf-8 -*-
"""PERF2C adapter: single-pass exact full snapshot with fail-safe fallback."""
from __future__ import annotations

from typing import Any, Dict, Mapping

from r1_15a2_trial_adapter_v24915p2 import VisumAdapter as _PERF2
from r1_15a2_single_pass_snapshot_v24915p2c import single_pass_exact_snapshot


class VisumAdapter(_PERF2):
    runtime_backend = "VISUM_COM_V24915_PERF2C_SINGLE_PASS_EXACT_SNAPSHOT"

    def __init__(self, visum, cfg, control=None):
        super().__init__(visum, cfg, control)
        feature = (cfg.get("v24915_perf2c_runtime_options") or
                   ((cfg.get("performance", {}) or {}).get(
                       "v24915_perf2c_single_pass_snapshot", {}) or {}))
        self.perf2c_snapshot_enabled = feature.get("enabled", True) is True
        self.perf2c_shadow_parity_once = feature.get(
            "shadow_parity_once", True) is True
        self.perf2c_fallback_to_legacy = feature.get(
            "fallback_to_legacy", True) is True
        self._perf2c_shadow_pending = self.perf2c_shadow_parity_once
        self._perf2c_runtime_disabled = False
        self.last_perf2c_snapshot_parity: Dict[str, Any] = {
            "status": "NOT_RUN",
            "public_snapshot_schema_changed": False,
            "cross_call_cache": False,
        }

    @staticmethod
    def _component_hashes(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "addval_hash", "fixed_link_hash", "matrix_hash", "dseg_hash",
            "generation_hash", "td_hash", "operations_hash", "state_hash",
        )
        return {key: snapshot.get(key) for key in keys}

    def _record_snapshot_event(self, name: str, **payload: Any) -> None:
        manager = getattr(self, "readback_manager", None)
        if manager is not None:
            manager._event(name, **payload)  # PERF2 telemetry API

    def _disable_perf2c(self, reason: str, error: str = "") -> None:
        self._perf2c_runtime_disabled = True
        self.last_perf2c_snapshot_parity = {
            "status": "DISABLED_FALLBACK_TO_LEGACY",
            "reason": reason,
            "error": error,
            "public_snapshot_schema_changed": False,
            "cross_call_cache": False,
        }
        self._record_snapshot_event(
            "PERF2C_SINGLE_PASS_FALLBACK", reason=reason, error=error)

    def legacy_snapshot_from_live_visum(self):
        """Return exact full snapshot; optimize only the internals of this call.

        The first live call performs an exact object-level parity check against
        the untouched parent implementation.  A mismatch or any optimized-read
        exception permanently disables PERF2C for this adapter instance and
        returns the already-read legacy payload.
        """

        self._sync_readback_telemetry()
        if not self.perf2c_snapshot_enabled or self._perf2c_runtime_disabled:
            return super().legacy_snapshot_from_live_visum()

        if self._perf2c_shadow_pending:
            legacy = super().legacy_snapshot_from_live_visum()
            try:
                optimized = single_pass_exact_snapshot(self)
            except Exception as exc:
                self._disable_perf2c(
                    "FIRST_CALL_OPTIMIZED_READ_FAILED", type(exc).__name__ + ":" + str(exc))
                if not self.perf2c_fallback_to_legacy:
                    raise
                return legacy
            if optimized != legacy:
                self.last_perf2c_snapshot_parity = {
                    "status": "EXACT_PARITY_MISMATCH_FALLBACK_TO_LEGACY",
                    "legacy_hashes": self._component_hashes(legacy),
                    "optimized_hashes": self._component_hashes(optimized),
                    "legacy_keys": sorted(legacy),
                    "optimized_keys": sorted(optimized),
                    "public_snapshot_schema_changed": sorted(legacy) != sorted(optimized),
                    "cross_call_cache": False,
                }
                self._perf2c_runtime_disabled = True
                self._record_snapshot_event(
                    "PERF2C_SINGLE_PASS_PARITY_FAIL",
                    legacy_state_hash=legacy.get("state_hash"),
                    optimized_state_hash=optimized.get("state_hash"))
                if not self.perf2c_fallback_to_legacy:
                    raise RuntimeError("V24915P2C_SINGLE_PASS_SNAPSHOT_PARITY_FAIL")
                return legacy
            self._perf2c_shadow_pending = False
            self.last_perf2c_snapshot_parity = {
                "status": "EXACT_PARITY_PASS",
                "state_hash": optimized.get("state_hash"),
                "component_hashes": self._component_hashes(optimized),
                "public_snapshot_schema_changed": False,
                "cross_call_cache": False,
            }
            self._record_snapshot_event(
                "PERF2C_SINGLE_PASS_PARITY_PASS",
                state_hash=optimized.get("state_hash"))
            return optimized

        try:
            optimized = single_pass_exact_snapshot(self)
            # Keep the parent telemetry counter semantics: this is still a full
            # legacy-equivalent semantic snapshot, only read more efficiently.
            self._record_snapshot_event("LEGACY_SNAPSHOT_TOTAL")
            self._record_snapshot_event(
                "PERF2C_SINGLE_PASS_SNAPSHOT_TOTAL",
                state_hash=optimized.get("state_hash"))
            return optimized
        except Exception as exc:
            self._disable_perf2c(
                "OPTIMIZED_READ_FAILED", type(exc).__name__ + ":" + str(exc))
            if not self.perf2c_fallback_to_legacy:
                raise
            return super().legacy_snapshot_from_live_visum()


__all__ = ["VisumAdapter"]
