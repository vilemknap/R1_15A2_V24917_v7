"""Narrow targeting hooks for V24916 rebased on PERF2C.

Hooks preserve candidate row order and never perform Visum writes. They only
produce a transformed proposal plus an explicit audit payload. Acceptance is
still delegated to fresh assignment + live 12D/11D.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace, is_dataclass
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence
import copy
import hashlib
import json
import math

SCHEMA = "R1_15A2_V24916_PERF2C_TARGETING_HOOK_V1"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _get(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row[name]
    return getattr(row, name)


def _set_clone(row: Any, name: str, value: Any) -> Any:
    if isinstance(row, Mapping):
        out = dict(row)
        out[name] = value
        return out
    if is_dataclass(row):
        return replace(row, **{name: value})
    out = copy.copy(row)
    setattr(out, name, value)
    return out


@dataclass(frozen=True)
class GenerationTargetingAudit:
    schema: str
    row_count: int
    targeted_zone_count: int
    positive_inside_count: int
    positive_outside_count: int
    negative_count: int
    zero_count: int
    positive_inside_mass_before: float
    positive_inside_mass_after: float
    positive_outside_mass_before: float
    positive_outside_mass_after: float
    sign_flip_count: int
    order_preserved: bool
    outside_positive_factor: float
    rows_hash_before: str
    rows_hash_after: str


@dataclass(frozen=True)
class TDTargetingAudit:
    schema: str
    input_components: tuple[str, ...]
    selected_components: tuple[str, ...]
    frozen_components: tuple[str, ...]
    max_active_components: int
    input_order_preserved: bool
    selection_hash: str


def apply_generation_positive_damping(
    rows: Sequence[Any],
    target_zone_nos: Iterable[int],
    *,
    outside_positive_factor: float,
    zone_field: str = "zone_no",
    delta_field: str = "delta",
) -> tuple[list[Any], GenerationTargetingAudit]:
    """Preserve row order and only damp positive steps outside target zones.

    Negative/zero steps and all target-zone steps are byte-for-byte numeric
    equivalents of the incoming proposal. A sign flip is a hard error.
    """
    factor = float(outside_positive_factor)
    if not (0.0 <= factor <= 1.0):
        raise ValueError("V24916_GENERATION_DAMPING_FACTOR_OUT_OF_RANGE")
    targets = {int(v) for v in target_zone_nos}
    out: list[Any] = []
    pin_b = pin_a = pout_b = pout_a = 0.0
    c_in = c_out = c_neg = c_zero = sign_flips = 0
    before_repr = []
    after_repr = []
    for row in rows:
        zone = int(_get(row, zone_field))
        delta = float(_get(row, delta_field))
        if not math.isfinite(delta):
            raise ValueError("V24916_GENERATION_NONFINITE_DELTA")
        new_delta = delta
        if delta > 0.0:
            if zone in targets:
                c_in += 1
                pin_b += delta
                pin_a += delta
            else:
                c_out += 1
                pout_b += delta
                new_delta = delta * factor
                pout_a += new_delta
        elif delta < 0.0:
            c_neg += 1
        else:
            c_zero += 1
        if delta != 0.0 and new_delta != 0.0 and math.copysign(1.0, delta) != math.copysign(1.0, new_delta):
            sign_flips += 1
        new_row = _set_clone(row, delta_field, new_delta)
        out.append(new_row)
        before_repr.append((zone, delta))
        after_repr.append((zone, new_delta))
    if sign_flips:
        raise AssertionError("V24916_GENERATION_TARGETING_SIGN_FLIP")
    before_order = [int(_get(r, zone_field)) for r in rows]
    after_order = [int(_get(r, zone_field)) for r in out]
    order_preserved = before_order == after_order
    if not order_preserved:
        raise AssertionError("V24916_GENERATION_TARGETING_ROW_ORDER_CHANGED")
    audit = GenerationTargetingAudit(
        schema=SCHEMA,
        row_count=len(rows),
        targeted_zone_count=len(targets),
        positive_inside_count=c_in,
        positive_outside_count=c_out,
        negative_count=c_neg,
        zero_count=c_zero,
        positive_inside_mass_before=pin_b,
        positive_inside_mass_after=pin_a,
        positive_outside_mass_before=pout_b,
        positive_outside_mass_after=pout_a,
        sign_flip_count=0,
        order_preserved=True,
        outside_positive_factor=factor,
        rows_hash_before=_hash(before_repr),
        rows_hash_after=_hash(after_repr),
    )
    return out, audit


def recompute_generation_post_target_summary(
    rows: Sequence[Any],
    *,
    zone_field: str = "zone_no",
    delta_field: str = "delta",
    family_field: str | None = "family",
) -> dict[str, Any]:
    """Recompute summaries from actual post-target rows, never pre-target data."""
    total = pos = neg = 0.0
    positive_count = negative_count = zero_count = 0
    by_family: dict[str, dict[str, float | int]] = {}
    canonical_rows = []
    for row in rows:
        zone = int(_get(row, zone_field))
        delta = float(_get(row, delta_field))
        family = str(_get(row, family_field)) if family_field and ((isinstance(row, Mapping) and family_field in row) or hasattr(row, family_field)) else "UNSPECIFIED"
        total += delta
        if delta > 0:
            pos += delta; positive_count += 1
        elif delta < 0:
            neg += delta; negative_count += 1
        else:
            zero_count += 1
        b = by_family.setdefault(family, {"count": 0, "delta_sum": 0.0, "positive_sum": 0.0, "negative_sum": 0.0})
        b["count"] = int(b["count"]) + 1
        b["delta_sum"] = float(b["delta_sum"]) + delta
        b["positive_sum"] = float(b["positive_sum"]) + max(delta, 0.0)
        b["negative_sum"] = float(b["negative_sum"]) + min(delta, 0.0)
        canonical_rows.append((family, zone, delta))
    return {
        "schema": "R1_15A2_V24916_POST_TARGET_GENERATION_SUMMARY_V1",
        "row_count": len(rows),
        "delta_sum": total,
        "positive_sum": pos,
        "negative_sum": neg,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "zero_count": zero_count,
        "by_family": by_family,
        "rows_hash": _hash(canonical_rows),
        "summary_source": "ACTUAL_POST_TARGET_ROWS",
    }


def select_td_components(
    ordered_components: Sequence[str],
    pressure_by_component: Mapping[str, float],
    *,
    max_active_components: int,
    allowed_families: Sequence[str] = ("WORK", "SERV"),
    frozen_components: Sequence[str] = ("SCHOOL",),
    freeze_long: bool = True,
    minimum_pressure: float = 0.0,
) -> tuple[list[str], TDTargetingAudit]:
    """Select a bounded WORK/SERVICE active set and preserve input ordering."""
    limit = max(0, int(max_active_components))
    allowed = tuple(str(x).upper() for x in allowed_families)
    frozen_exact = {str(x) for x in frozen_components}

    candidates: list[tuple[float, int, str]] = []
    frozen: list[str] = []
    for idx, comp in enumerate(ordered_components):
        c = str(comp)
        cu = c.upper()
        family_ok = any(cu.startswith(prefix + "_") or cu == prefix for prefix in allowed)
        is_frozen = c in frozen_exact or (freeze_long and cu.startswith("LONG")) or not family_ok
        pressure = float(pressure_by_component.get(c, 0.0))
        if not math.isfinite(pressure):
            raise ValueError(f"V24916_TD_PRESSURE_NONFINITE:{c}")
        if is_frozen or pressure <= float(minimum_pressure):
            frozen.append(c)
            continue
        candidates.append((-pressure, idx, c))
    candidates.sort()
    chosen_set = {c for _, _, c in candidates[:limit]}
    selected = [str(c) for c in ordered_components if str(c) in chosen_set]
    # This ordering is intentionally inherited from ordered_components, not rank order.
    order_positions = [list(map(str, ordered_components)).index(c) for c in selected]
    order_preserved = order_positions == sorted(order_positions)
    if not order_preserved:
        raise AssertionError("V24916_TD_COMPONENT_ORDER_CHANGED")
    audit = TDTargetingAudit(
        schema=SCHEMA,
        input_components=tuple(str(c) for c in ordered_components),
        selected_components=tuple(selected),
        frozen_components=tuple(c for c in map(str, ordered_components) if c not in chosen_set),
        max_active_components=limit,
        input_order_preserved=True,
        selection_hash=_hash({"ordered": list(map(str, ordered_components)), "selected": selected, "pressure": {str(k): float(v) for k, v in pressure_by_component.items()}}),
    )
    return selected, audit
