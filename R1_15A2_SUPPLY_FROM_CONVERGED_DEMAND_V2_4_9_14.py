# -*- coding: utf-8 -*-
"""Start only the V2.4.9.14 route-choice phase from verified converged demand.

This launcher is not for the A0009 continuation itself.  Use the full V24914
launcher to continue cycles 6-12.  Supply-only remains fail-closed and requires
a matching DEMAND_CONVERGED.json authority.
"""
from __future__ import annotations

import importlib

_entry = importlib.import_module(
    "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_14")
if globals().get("Visum") is not None:
    _entry.Visum = globals().get("Visum")
if globals().get("COM") is not None:
    _entry.COM = globals().get("COM")
_entry.main("SUPPLY_ONLY")
