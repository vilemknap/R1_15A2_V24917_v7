# -*- coding: utf-8 -*-
"""Read-only shadow classifier retained for V24916 compatibility.

This helper is diagnostic only.  It never becomes an actuator or acceptance
term; its labels are descriptive hints for review.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence
import math


def _finite(value):
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def classify_shadow_rows(rows: Sequence[Mapping[str, Any]], skims: Any):
    out=[]
    for raw in rows or []:
        row=dict(raw)
        dseg=str(row.get('dseg_code',''))
        o=row.get('origin'); d=row.get('destination')
        def val(code):
            try: return _finite(skims.value(dseg, code, o, d))
            except Exception: return None
        tt0,ttc,ad1,imp=val('TT0'),val('TTC'),val('AD1'),val('IMP')
        if tt0 is not None and ttc is not None and ttc > tt0 + 1e-12:
            label='LIKELY_SUPPLY_OR_ROUTE_CHOICE_REVIEW'
        elif imp is not None or ad1 is not None:
            label='SKIM_CONTEXT_AVAILABLE_NO_ACTUATION'
        else:
            label='INSUFFICIENT_OPTIONAL_SKIM_CONTEXT'
        row.update({
            'shadow_class':label,
            'shadow_tt0':tt0,'shadow_ttc':ttc,'shadow_ad1':ad1,'shadow_imp':imp,
            'actuator':False,
            'objective_or_acceptance_term':False,
            'role':'SHADOW_DIAGNOSTIC_ONLY',
        })
        out.append(row)
    return out


__all__=['classify_shadow_rows']
