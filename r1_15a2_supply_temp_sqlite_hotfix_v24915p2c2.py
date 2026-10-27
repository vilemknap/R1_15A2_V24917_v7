# -*- coding: utf-8 -*-
"""PERF2C R2: preserve main SQLite cache read-only, allow local TEMP joins.

V248 deliberately reopens a persistent path cache with SQLite URI ``mode=ro``.
It additionally enabled ``PRAGMA query_only=ON``.  That second guard is broader
than the file-level read-only contract: it also forbids connection-local TEMP
schema writes.  Supply design uses a TEMP table only as a join accelerator in
``TwoModeRouteCollector.impact()`` and therefore failed before producing any
candidate.

This additive runtime overlay leaves the parent V238 source/hash untouched.  It
wraps only ``open_existing``: after the parent has validated and reopened the
cache via ``mode=ro``, query_only is disabled, TEMP storage is forced to memory,
and a tiny TEMP-schema probe is performed.  The main database remains protected
by the already-open read-only URI connection.
"""
from __future__ import annotations

from typing import Any

import r1_15a2_core as core
from r1_15a2_supply import SupplyContractError, number
from r1_15a2_two_mode_v238 import TwoModeRouteCollector

_PATCH_MARKER = "_r1_perf2c_r2_supply_temp_hotfix_active"
_ORIGINAL_OPEN_EXISTING = TwoModeRouteCollector.open_existing.__func__


def _prepare_read_only_temp_schema(collector: TwoModeRouteCollector) -> TwoModeRouteCollector:
    if not bool(getattr(collector, "read_only", False)):
        return collector
    db = collector.db
    try:
        # URI mode=ro on the already-open connection remains the protection for
        # the persistent main database.  query_only is disabled solely because
        # it also blocks TEMP schema writes required by impact().
        db.execute("PRAGMA query_only=OFF")
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("DROP TABLE IF EXISTS temp.__r1_perf2c_r2_temp_probe")
        db.execute("CREATE TEMP TABLE __r1_perf2c_r2_temp_probe(x INTEGER)")
        db.execute("INSERT INTO __r1_perf2c_r2_temp_probe VALUES(1)")
        row = db.execute("SELECT x FROM __r1_perf2c_r2_temp_probe").fetchone()
        if row != (1,):
            raise SupplyContractError("PERF2C_R2_TEMP_SCHEMA_PROBE_MISMATCH")
        db.execute("DROP TABLE temp.__r1_perf2c_r2_temp_probe")
    except BaseException as exc:
        try:
            collector.close()
        finally:
            if isinstance(exc, SupplyContractError):
                raise
            raise SupplyContractError(
                "PERF2C_R2_READONLY_CACHE_TEMP_SCHEMA_UNAVAILABLE:%s" % exc
            ) from exc
    # V238 fresh collectors initialize these two read-only diagnostic index
    # sets in __init__, but open_existing() historically omitted them.  Rebuild
    # them exactly from the reopened profile authority before Supply impact().
    # This is state reconstruction, not a new selection rule.
    collector.protected = {
        i for i, row in enumerate(collector.profiles)
        if str(row.get("role", "")).upper() == "CALIBRATION"
        and number(row["observed"]) > 0
        and core.geh(number(row["model"]), number(row["observed"])) < 5.0
    }
    collector.cal_indices = {
        i for i, row in enumerate(collector.profiles)
        if str(row.get("role", "")).upper() == "CALIBRATION"
    }
    summary = getattr(collector, "summary", None)
    if isinstance(summary, dict):
        summary["persistent_cache_main_database_mode"] = "URI_MODE_RO"
        summary["persistent_cache_main_database_writable"] = False
        summary["persistent_cache_temp_schema"] = "MEMORY_WRITABLE_CONNECTION_LOCAL"
        summary["persistent_cache_query_only"] = False
    return collector


def activate_supply_temp_sqlite_hotfix() -> bool:
    """Install the wrapper once on the shared V238 collector class."""
    if getattr(TwoModeRouteCollector, _PATCH_MARKER, False):
        return False

    original = _ORIGINAL_OPEN_EXISTING

    def _open_existing(
        cls,
        profiles,
        policy,
        links,
        db_path,
        settings=None,
        control=None,
        duplicate_scope_policy="FAIL",
        max_unique_sequences=100000,
        max_pairs_per_market=64,
        read_only=True,
        require_profile_metadata=False,
    ):
        collector = original(
            cls,
            profiles,
            policy,
            links,
            db_path,
            settings,
            control,
            duplicate_scope_policy,
            max_unique_sequences,
            max_pairs_per_market,
            read_only,
            require_profile_metadata,
        )
        return _prepare_read_only_temp_schema(collector)

    TwoModeRouteCollector.open_existing = classmethod(_open_existing)
    setattr(TwoModeRouteCollector, _PATCH_MARKER, True)
    return True


__all__ = ["activate_supply_temp_sqlite_hotfix"]
