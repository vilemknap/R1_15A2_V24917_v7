"""FineCDF active-set hook for V24916 over the current parent implementation."""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from r1_15a2_demand_targeting_hooks_v24916p2c import select_td_components


def build_targeted_active_set(
    parent_ordered_components: Sequence[str],
    pressure_by_component: Mapping[str, float],
    *,
    enabled: bool,
    max_active_components: int,
    minimum_pressure: float = 0.0,
):
    if not enabled:
        return list(parent_ordered_components), {
            "status": "FEATURE_OFF",
            "parent_order_preserved": True,
            "selected": list(parent_ordered_components),
        }
    selected, audit = select_td_components(
        parent_ordered_components,
        pressure_by_component,
        max_active_components=max_active_components,
        minimum_pressure=minimum_pressure,
    )
    return selected, {"status": "TARGETED", "audit": audit.__dict__}


def assert_all_17_restored(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    if set(before) != set(after):
        raise AssertionError("V24916_TD_ROLLBACK_COMPONENT_SET_MISMATCH")
    bad=[]
    for c in before:
        if before[c] != after[c]: bad.append(c)
    if bad:
        raise AssertionError("V24916_TD_ROLLBACK_NOT_EXACT:" + ",".join(sorted(bad)))
