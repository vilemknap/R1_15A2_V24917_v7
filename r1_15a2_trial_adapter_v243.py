# -*- coding: utf-8 -*-
"""V2.4.3 hotfix adapter: guarantee trial output directories exist before any Visum recompute."""
from pathlib import Path
from r1_15a2_trial_adapter_v240 import VisumAdapter as _V240

class VisumAdapter(_V240):
    def assign(self, folder, *, supply_only):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        return super().assign(folder, supply_only=supply_only)
