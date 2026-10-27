# -*- coding: utf-8 -*-
"""Compatibility and audit facade for the V2.4.9.12 severity policy.

The authoritative live implementation is embedded in :mod:`r1_15a2_core`.
Keeping the acceptance function inside the already-loaded numerical core avoids
late module discovery inside Visum helper/procedure contexts, which caused the
first V24912 live run to fail with ``No module named
'r1_15a2_guard_policy_v24912'`` even though the package archive contained this
file.

This module remains in the bundle for explicit imports, documentation, package
integrity checks and offline replay tools.  It is not required by the live
acceptance call path.
"""
from __future__ import annotations

from r1_15a2_core import (
    V24912_POLICY_ID as POLICY_ID,
    V24912_POLICY_LEVEL as POLICY_LEVEL,
    rebase_severity_guard_v24912,
)

EARLY_THROUGH_OUTER_CYCLE = 12
RUNTIME_EXTERNAL_POLICY_IMPORT_REQUIRED = False
IMPLEMENTATION_OWNER = "r1_15a2_core.py"

__all__ = [
    "POLICY_ID",
    "POLICY_LEVEL",
    "EARLY_THROUGH_OUTER_CYCLE",
    "RUNTIME_EXTERNAL_POLICY_IMPORT_REQUIRED",
    "IMPLEMENTATION_OWNER",
    "rebase_severity_guard_v24912",
]
