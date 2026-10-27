# -*- coding: utf-8 -*-
"""Run manually in Visum to print operation-46/DStratSet compatibility evidence.

No procedure is executed and no model object is changed. Importing this file
does nothing; the operator must choose Scripts -> Run script file in Visum.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


def main(visum):
    if visum is None:
        raise RuntimeError("TDLONG1_READ_ONLY_VISUM_REQUIRED")
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from r1_15a2_tdlong1_probe_v24917 import inspect_read_only
    return inspect_read_only(visum)


if __name__ == "__main__":
    print(json.dumps(main(globals().get("Visum")), ensure_ascii=False,
                     sort_keys=True, indent=2))
