# -*- coding: utf-8 -*-
"""Start only the V2.4.9.13 route-choice phase from a verified converged demand state.

Open the latest accepted V24912/V24913 .ver whose surrounding run contains a
matching DEMAND_CONVERGED.json, then execute this file from Visum.
"""
from __future__ import annotations

import importlib

_entry = importlib.import_module(
    "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_13")
if globals().get("Visum") is not None:
    _entry.Visum = globals().get("Visum")
if globals().get("COM") is not None:
    _entry.COM = globals().get("COM")
_entry.main("SUPPLY_ONLY")
