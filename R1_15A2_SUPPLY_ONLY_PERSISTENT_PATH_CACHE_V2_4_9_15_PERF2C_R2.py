# -*- coding: utf-8 -*-
"""Verified Supply-only resume launcher for PERF2C R2.

Use only with a checkpoint that sits below a run containing a valid
DEMAND_CONVERGED.json.  The parent supply-handoff gate compares the opened live
state_hash to that authority before any Supply trial write is allowed.
"""
from __future__ import annotations

import R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C as perf2c

_INJECTED_VISUM = globals().get("Visum")
_INJECTED_COM = globals().get("COM")


def main():
    # The imported PERF2C module cannot see injected Visum/COM from this wrapper
    # automatically, so forward them explicitly before activating its overlay.
    perf2c._INJECTED_VISUM = _INJECTED_VISUM
    perf2c._INJECTED_COM = _INJECTED_COM
    return perf2c.main("SUPPLY_ONLY")


if __name__ == "__main__" or _INJECTED_VISUM is not None or _INJECTED_COM is not None:
    main()
