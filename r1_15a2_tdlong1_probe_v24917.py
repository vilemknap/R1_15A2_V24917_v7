# -*- coding: utf-8 -*-
"""Read-only Visum TD schema probe for TDLONG1; never executes procedures."""
from __future__ import annotations

from typing import Any

import r1_15a2_com_compat as com

RELEASE = "R1_15A2_V24917_TDLONG1_READ_ONLY_PROBE_20261027"


def inspect_read_only(visum: Any) -> dict:
    """Report operation 46 and its declared strata using known read members.

    This does not introspect speculative COM member names, write attributes,
    activate operations, call Calculate/Execute, touch OD matrices or save a
    version.  DStratSet membership is not evidence of an OD-pair support filter.
    """
    rows = com.operation_rows(visum)
    try:
        import r1_15a2_multiblock as mb
        long_codes = {str(row["dstrat_code"]) for row in mb.COMPONENT_REGISTRY.values()
                      if str(row.get("family", "")).upper() == "LONG"}
    except Exception as exc:
        return {"release": RELEASE, "status": "UNVERIFIED_NATIVE_FILTER",
                "error": "LONG_COMPONENT_REGISTRY_UNAVAILABLE:%s" % type(exc).__name__,
                "operations": [], "native_filter_verified": False,
                "long_generation_permitted": False, "read_only": True}

    operations = []
    for source_row in rows:
        if int(source_row["type"]) != 46:
            continue
        op = source_row.get("object")
        params, param_source = None, None
        for prop in ("TripDistributionParameters", "TripDistributionParameter"):
            try:
                candidate = getattr(op, prop)
                if candidate is not None:
                    params, param_source = candidate, prop
                    break
            except Exception:
                continue
        dstratset, dstrat_source = "", None
        if params is not None:
            for attr in ("DSTRATSET", "DStratSet", "DEMANDSTRATUMSET"):
                try:
                    value = params.AttValue(attr)
                except Exception:
                    try:
                        value = getattr(params, attr)
                    except Exception:
                        continue
                if value not in (None, ""):
                    dstratset, dstrat_source = str(value), attr
                    break
        tokens = com.code_set(dstratset, "TDLONG1_DSTRATSET") if dstratset.strip() else set()
        operations.append({
            "position": int(source_row["position"]),
            "active": bool(source_row["active"]),
            "name": str(source_row.get("name", "")),
            "comment": str(source_row.get("comment", "")),
            "parameter_source": param_source,
            "parameter_status": "READABLE" if params is not None else "UNREADABLE",
            "dstratset_source": dstrat_source,
            "dstratset_codes": sorted(tokens),
            "long_components_present": sorted(tokens & {x.upper() for x in long_codes}),
            "long_components_missing": sorted({x.upper() for x in long_codes} - tokens),
        })
    return {
        "release": RELEASE,
        "status": "UNVERIFIED_NATIVE_FILTER",
        "operation_type": 46,
        "operations": operations,
        "known_long_dstrat_codes": sorted(long_codes),
        "native_pair_filter_api": "UNVERIFIED_NOT_PROBED_BY_GUESS",
        "dstratset_is_pair_filter_evidence": False,
        "native_filter_verified": False,
        "long_generation_permitted": False,
        "read_only": True,
        "mutating_calls_made": [],
    }


__all__ = ["RELEASE", "inspect_read_only"]
