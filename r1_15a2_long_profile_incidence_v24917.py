# -*- coding: utf-8 -*-
"""Read-only NATIVE_CL OD-to-profile incidence from official saved Visum routes.

This is current *vehicle-flow attribution*, not a derivative of LONG trip
generation. It cannot enable ADD_PROD_L/ADD_ATT_L: native TD, component- and
M9001-band-specific 20A kappa realization (9111..9115 to 9191..9195), and
20B bounded-IPF return (9191..9195 to 9291..9295) sit between TG and these
matrices. M929x shares already include both transformations; no global CL
vehicle-per-person multiplier is inferred.
The caller must establish that paths, M9291..M9295 and M9305 belong to the
same assignment/path epoch. No COM operations or matrix writes occur here.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

import r1_15a2_core as core
from r1_15a2_com_compat import exact_int, finite_float
from r1_15a2_skim_v24916p2c import ordered_zone_hash
from r1_15a2_path_incidence_v24917 import matrix_values_hash

RELEASE = "R1_15A2_V24917_LONG_OBSERVED_PATH_INCIDENCE_V2_STREAMED"
COMPONENT_MATRICES = (9291, 9292, 9293, 9294, 9295)
FINAL_MATRIX = 9305


def _matrix(values: Any, n: int, label: str) -> np.ndarray:
    a = np.asarray(values, dtype=np.float64)
    if a.shape != (n, n):
        raise ValueError("LONG_INCIDENCE_MATRIX_SHAPE:" + label)
    if not np.isfinite(a).all() or np.any(a < 0.0):
        raise ValueError("LONG_INCIDENCE_MATRIX_INVALID:" + label)
    return np.array(a, copy=True)


def build_observed_long_incidence(
    path_rows: Sequence[Mapping[str, Any]],
    pathlink_rows: Iterable[Mapping[str, Any]],
    profiles: Sequence[Mapping[str, Any]],
    zone_nos: Sequence[int],
    final_vehicle_od: Any,
    component_vehicle_od: Mapping[int, Any],
    *,
    absolute_tolerance: float = 1.0e-6,
    relative_tolerance: float = 1.0e-8,
) -> dict[str, Any]:
    """Build exact current CL path exposure, with OD and component parity gates.

    ``path_rows`` and ``pathlink_rows`` must be the official saved NATIVE_CL
    route lists. Positive interzonal OD mass must have complete path links.
    The five 929x matrices must sum cellwise to 9305. Intrazonal matrix mass
    is recorded separately because it need not have a network route.
    """
    if any(isinstance(z, (bool, np.bool_)) or not isinstance(z, (int, np.integer))
           for z in zone_nos):
        raise ValueError("LONG_INCIDENCE_ZONE_AXIS_INVALID")
    zones = tuple(int(z) for z in zone_nos)
    if not zones or any(z <= 0 for z in zones) or len(set(zones)) != len(zones):
        raise ValueError("LONG_INCIDENCE_ZONE_AXIS_INVALID")
    if not profiles:
        raise ValueError("LONG_INCIDENCE_NO_PROFILES")
    n = len(zones)
    zone_pos = {z: i for i, z in enumerate(zones)}
    atol, rtol = float(absolute_tolerance), float(relative_tolerance)
    if not np.isfinite([atol, rtol]).all() or atol < 0.0 or rtol < 0.0:
        raise ValueError("LONG_INCIDENCE_TOLERANCE_INVALID")
    final = _matrix(final_vehicle_od, n, "M9305")
    if set(component_vehicle_od) != set(COMPONENT_MATRICES):
        raise ValueError("LONG_INCIDENCE_COMPONENT_SET_INVALID")
    components = {no: _matrix(component_vehicle_od[no], n, "M%d" % no)
                  for no in COMPONENT_MATRICES}
    component_sum = np.zeros_like(final)
    for no in COMPONENT_MATRICES:
        component_sum += components[no]
    if not np.allclose(component_sum, final, rtol=rtol, atol=atol):
        raise ValueError("LONG_INCIDENCE_COMPONENT_TO_FINAL_OD_MISMATCH")
    if not np.any(final[~np.eye(n, dtype=bool)] > 0.0):
        raise ValueError("LONG_INCIDENCE_NO_INTERZONAL_FLOW")

    for raw in path_rows:
        for names in (core.PATH_ORIGIN_NAMES, core.PATH_DEST_NAMES, core.PATH_INDEX_NAMES):
            exact_int(core.first_value(raw, names), "LONG_PATH_KEY")
        if finite_float(core.first_value(raw, core.PATH_VOLUME_NAMES), "LONG_PATH_VOLUME") < 0.0:
            raise ValueError("LONG_INCIDENCE_INVALID_PATH_ROWS")
    paths, path_summary = core.parse_official_path_rows(path_rows)
    if path_summary["invalid_rows"] or path_summary["negative_volume_rows"]:
        raise ValueError("LONG_INCIDENCE_INVALID_PATH_ROWS")
    if not paths or any(p["dseg_code"] != "NATIVE_CL" for p in paths):
        raise ValueError("LONG_INCIDENCE_NOT_NATIVE_CL_PATHS")
    if any(p["raw_rows"] != 1 for p in paths):
        raise ValueError("LONG_INCIDENCE_DUPLICATE_PATH_KEY")
    path_by_key = {p["path_key"]: p for p in paths}
    path_od = np.zeros_like(final)
    for path in paths:
        o, d = int(path["origin"]), int(path["destination"])
        if o not in zone_pos or d not in zone_pos:
            raise ValueError("LONG_INCIDENCE_PATH_ZONE_OUTSIDE_AXIS")
        path_od[zone_pos[o], zone_pos[d]] += float(path["volume"])
    off = ~np.eye(n, dtype=bool)
    if (not np.allclose(path_od[off], final[off], rtol=rtol, atol=atol)
            or np.any(off & (final > 0.0) & (path_od <= 0.0))
            or np.any(off & (final <= 0.0) & (path_od > 0.0))):
        raise ValueError("LONG_INCIDENCE_PATH_TO_FINAL_OD_MISMATCH")

    link_to_profiles: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for idx, profile in enumerate(profiles):
        keys = core._profile_link_keys(profile)
        if not keys:
            raise ValueError("LONG_INCIDENCE_PROFILE_LINK_INVALID")
        for key in keys:
            link_to_profiles[key].append(idx)

    path_profile_hits: dict[tuple[Any, int], int] = defaultdict(int)
    path_with_links: set[Any] = set()
    # Only profile hits need retention; the bounded exporter can stream millions
    # of other link rows. A repeated physical link at a DIFFERENT position is a
    # real traversal, whereas a duplicate exported position must not double flow.
    hit_positions: set[Any] = set()
    for raw in pathlink_rows:
        try:
            for names in (core.PATH_ORIGIN_NAMES, core.PATH_DEST_NAMES,
                          core.PATHLINK_PATH_INDEX_NAMES, core.LINK_NO_NAMES,
                          core.FROM_NODE_NAMES, core.TO_NODE_NAMES):
                exact_int(core.first_value(raw, names), "LONG_PATHLINK_KEY")
        except RuntimeError as exc:
            raise ValueError("LONG_INCIDENCE_INVALID_OR_ORPHAN_PATHLINK") from exc
        key = core._path_key_from_row(raw, pathlink=True)
        link = core._link_key_from_row(raw)
        if key is None or link is None or key not in path_by_key:
            raise ValueError("LONG_INCIDENCE_INVALID_OR_ORPHAN_PATHLINK")
        path_with_links.add(key)
        indices = link_to_profiles.get(link, ())
        if indices:
            seq = exact_int(core.first_value(raw, core.PATHLINK_SEQ_NAMES), "LONG_PATHLINK_POSITION")
            if (key, seq) in hit_positions:
                raise ValueError("LONG_INCIDENCE_DUPLICATE_PROFILE_PATHLINK_POSITION")
            hit_positions.add((key, seq))
        for pidx in indices:
            path_profile_hits[(key, pidx)] += 1
    paths_hitting_profile = {key for key, _ in path_profile_hits}
    for path in paths:
        if (path["origin"] != path["destination"] and path["volume"] > 0.0
                and path["path_key"] not in path_with_links):
            raise ValueError("LONG_INCIDENCE_POSITIVE_PATH_WITHOUT_LINKS")
        if (path["origin"] == path["destination"] and path["volume"] > 0.0
                and path["path_key"] in paths_hitting_profile):
            raise ValueError("LONG_INCIDENCE_INTRAZONAL_PROFILE_PATH_UNSUPPORTED")

    od_keys = sorted((int(o), int(d))
                     for o, d in zip(*np.nonzero(final > 0.0)) if o != d)
    od_index = {key: idx for idx, key in enumerate(od_keys)}
    variables = [{"dseg_code": "NATIVE_CL", "family": "LONG", "origin": zones[o],
                  "destination": zones[d], "q_current": float(final[o, d]),
                  "component_vehicle_od": {str(no): float(components[no][o, d])
                                           for no in COMPONENT_MATRICES}}
                 for o, d in od_keys]
    through: dict[tuple[int, int], float] = defaultdict(float)
    for (key, pidx), multiplicity in path_profile_hits.items():
        path = path_by_key[key]
        o, d = zone_pos[int(path["origin"])], zone_pos[int(path["destination"])]
        if o == d:
            continue
        idx = od_index.get((o, d))
        if idx is None and path["volume"] > 0.0:
            raise ValueError("LONG_INCIDENCE_PATH_WITHOUT_FINAL_OD")
        if idx is not None:
            through[(pidx, idx)] += float(path["volume"]) * multiplicity
    items = sorted((key, value) for key, value in through.items() if value > 0.0)
    row = np.array([k[0] for k, _ in items], dtype=np.int64)
    col = np.array([k[1] for k, _ in items], dtype=np.int64)
    value = np.array([v for _, v in items], dtype=np.float64)
    operator = core.SparseOperator(row, col, value, len(profiles), len(variables))
    total_profile = np.bincount(row, weights=value, minlength=len(profiles)).astype(float)
    component_profile = {}
    for no in COMPONENT_MATRICES:
        share = np.array([components[no][o, d] / final[o, d] for o, d in od_keys])
        component_profile[str(no)] = np.bincount(
            row, weights=value * share[col], minlength=len(profiles)).astype(float)
    if not np.allclose(sum(component_profile.values(), np.zeros(len(profiles))),
                       total_profile, rtol=rtol, atol=atol):
        raise ValueError("LONG_INCIDENCE_COMPONENT_PROFILE_PARITY_FAILED")
    return {
        "release": RELEASE,
        "status": "OBSERVED_LONG_OD_PROFILE_ONLY",
        "source_status": "CALLER_SUPPLIED_INPUTS_LIVE_EPOCH_UNVERIFIED",
        "tg_sensitivity_verified": False,
        "long_generation_permitted": False,
        "zone_order_sha256": ordered_zone_hash(zones),
        "matrix_values_sha256": {"9305": matrix_values_hash(final),
                                 **{str(no): matrix_values_hash(components[no])
                                    for no in COMPONENT_MATRICES}},
        "path_summary": path_summary,
        "matrix_parity_max_abs": float(np.max(np.abs(component_sum - final))),
        "path_od_parity_max_abs_offdiag": float(np.max(np.abs(path_od[off] - final[off]), initial=0.0)),
        "unrouted_intrazonal_volume": float(np.trace(final)),
        "vehicle_production": np.sum(final, axis=1),
        "vehicle_attraction": np.sum(final, axis=0),
        "vehicle_total": float(np.sum(final)),
        "profile_identity": [p.get("countlocation_no", p.get("profile_id", i))
                             for i, p in enumerate(profiles)],
        "variables": variables,
        "incidence": operator,
        "profile_long_vehicle_flow": total_profile,
        "component_profile_vehicle_flow": component_profile,
    }


__all__ = ["RELEASE", "COMPONENT_MATRICES", "FINAL_MATRIX", "build_observed_long_incidence"]
