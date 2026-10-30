# -*- coding: utf-8 -*-
"""AMDY source-faithful LONG coefficients: not a blanket P/A scaling.

AMDY technical summary (December 2025), tables 13/14 and section 6:
  FP_3_LONG_* = (h * [E_S] * NOT_ZAHR / 2.8) * ADD_PROD_L
  FA_3_LONG   = (0.4*POP_ZP + 0.6*NUM_PM
                 + ADD_ATT_L*PRENOC_SVK) * NOT_ZAHR
The historical constants in both positions are 0.2. The attraction
coefficient applies ONLY to the overnight term.  Native formulas are
user-maintained in Visum; this read-only module never writes formulas.
"""
from __future__ import annotations

from typing import Mapping, Sequence
import math

import numpy as np

import r1_15a2_runtime_v1 as rt

RELEASE = "R1_V24917_LONG_AMDY_02_SOURCE_FORMULA"
PRODUCTION_REFERENCE = 0.2
OVERNIGHT_REFERENCE = 0.2
ATTRACTION_ATTR = "FA_3_LONG"
ATTRACTION_FIELDS = ("ADD_ATT_L", "PRENOC_SVK", "POP_ZP", "NUM_PM",
                     "NOT_ZAHR", ATTRACTION_ATTR)
ATOL = 1.e-5
RTOL = 1.e-8


def source_production(h: float, population: float, not_foreign: float,
                      coefficient: float) -> float:
    return (float(h) * float(population) * float(not_foreign)
            / 2.8 * float(coefficient))


def source_attraction(pop_zp: float, num_pm: float, prenoc_svk: float,
                      not_foreign: float, coefficient: float) -> float:
    return ((0.4 * float(pop_zp) + 0.6 * float(num_pm)
             + float(coefficient) * float(prenoc_svk))
            * float(not_foreign))


def source_overnight_elasticity(fa_long: float, prenoc_svk: float,
                               coefficient: float, not_foreign: float) -> float:
    fa = float(fa_long)
    contribution = (float(coefficient) * float(prenoc_svk)
                    * float(not_foreign))
    if not math.isfinite(fa) or not math.isfinite(contribution):
        raise ValueError("LONG_ATT_NONFINITE_NATIVE_INPUT")
    if fa < 0.0 or contribution < 0.0 or contribution > fa + ATOL + RTOL * fa:
        raise ValueError("LONG_ATT_OVERNIGHT_CONTRIBUTION_INVALID")
    if fa <= 1.e-12:
        if contribution > 1.e-12:
            raise ValueError("LONG_ATT_ZERO_FA_WITH_OVERNIGHT")
        return 0.0
    return min(1.0, contribution / fa)


def inspect_native(visum, zones: Sequence[int], retry_policy=None) -> dict:
    """Readback native LONG attraction formula and derive its exact elasticity.

    Every domestic zone must satisfy table 14's actual formula.  A correct
    baseline alone cannot prove the native coefficient dependency; repeat
    this readback AFTER each ADD_ATT_L candidate and compare to its new value.
    Missing/non-numeric attributes or formula deviations always fail closed.
    """
    axis = tuple(int(z) for z in zones)
    if not axis or len(set(axis)) != len(axis):
        raise ValueError("LONG_ATT_INVALID_ZONE_ORDER")
    fields = {}
    for name in ATTRACTION_FIELDS:
        values = np.asarray(rt.read_zone_attr_strict(
            visum, name, axis, retry_policy=retry_policy), dtype=np.float64)
        if values.shape != (len(axis),) or not np.isfinite(values).all():
            raise ValueError("LONG_ATT_INVALID_NATIVE_ATTRIBUTE:" + name)
        fields[name] = values
    c = fields["ADD_ATT_L"]
    p = fields["PRENOC_SVK"]
    pop = fields["POP_ZP"]
    jobs = fields["NUM_PM"]
    mask = fields["NOT_ZAHR"]
    measured = fields[ATTRACTION_ATTR]
    if (np.any(c <= 0.0) or np.any(p < 0.0) or np.any(pop < 0.0)
            or np.any(jobs < 0.0) or np.any(measured < 0.0)
            or np.any((mask != 0.0) & (mask != 1.0))):
        raise ValueError("LONG_ATT_SOURCE_ATTRIBUTES_OUT_OF_DOMAIN")
    expected = (0.4 * pop + 0.6 * jobs + c * p) * mask
    atol = ATOL + RTOL * np.maximum(np.abs(expected), np.abs(measured))
    broken = np.flatnonzero(np.abs(measured - expected) > atol)
    if broken.size:
        i = int(broken[0])
        raise ValueError(
            "LONG_ATT_AMDY_FORMULA_MISMATCH:zone=%s:actual=%.9g:expected=%.9g"
            % (axis[i], measured[i], expected[i]))
    elasticities = {
        z: source_overnight_elasticity(measured[i], p[i], c[i], mask[i])
        for i, z in enumerate(axis)
    }
    return {
        "status": "AMDY_TABLE14_OVERNIGHT_COEFFICIENT_NATIVE_READBACK",
        "reference_coefficient": OVERNIGHT_REFERENCE,
        "attraction_formula": ATTRACTION_ATTR,
        "source_weights": {"POP_ZP": 0.4, "NUM_PM": 0.6,
                           "PRENOC_SVK": "ADD_ATT_L"},
        "zones": list(axis),
        "attraction_elasticity": elasticities,
        "current_coefficient": {z: float(c[i]) for i, z in enumerate(axis)},
        "attraction": {z: float(measured[i]) for i, z in enumerate(axis)},
        "overnights": {z: float(p[i]) for i, z in enumerate(axis)},
        "active_overnight_zones": sum(
            elasticities[z] > 1.e-12 and mask[i] > 0.0
            for i, z in enumerate(axis)),
        "zero_overnight_zones": sum(p[i] == 0.0 and mask[i] > 0.0
                                    for i in range(len(axis))),
    }


__all__ = ["RELEASE", "PRODUCTION_REFERENCE", "OVERNIGHT_REFERENCE",
           "source_production", "source_attraction",
           "source_overnight_elasticity", "inspect_native"]
