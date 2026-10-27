# -*- coding: utf-8 -*-
"""Run manually from Visum Scripts, NOT inside Procedure Sequence.

Default: design-only. ADDVAL1 +1 = +10 generalized SECONDS.
Live APPLY requires approved operation IDs/types/DSeg scope and gap readback.
"""
from pathlib import Path
import json
import os
import sys
from datetime import datetime

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply_visum_v23 import VisumAdapter
from r1_15a2_controller_v22 import run_calibration
from r1_15a2_supply import canonical_hash


def load_config():
    path = HERE / "R1_15A2_CONFIG_V2_3.json"
    cfg = rt.read_json(path)
    cfg["apply"] = rt.env_bool("R1_15A2_V23_APPLY", cfg["apply"])
    cfg["config_path"] = str(path)
    cfg["config_sha256"] = rt.sha256_file(path)
    implementation_files = [
        "R1_15A2_SUPPLY_DEMAND_MASTER_V2_3.py", "r1_15a2_controller_v22.py",
        "r1_15a2_sequence_v23.py", "r1_15a2_supply_visum_v23.py",
        "r1_15a2_supply.py", "r1_15a2_supply_visum.py", "r1_15a2_runtime_v1.py",
        "r1_15a2_core.py", "r1_15a2_multiblock.py", "r1_15a2_visum_parameters.py",
        "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py",
        "helpers/R1_11D_V1_3_COMPONENT_DIST_BEHAVIOR_DIAGNOSTICS.py",
        "helpers/R1_12D_CSD2022_GEH_FORENSIC_444_PROCSEQ_EMBEDDED.py"]
    cfg["implementation_hash"] = canonical_hash({name: rt.sha256_file(HERE / name) for name in implementation_files})
    for key, target in (("tg_dependency_contract_file", "tg_dependency_contract"),
                        (None, "long_authority")):
        rel = cfg[key] if key else cfg["td"]["long_authority_file"]
        p = HERE / rel
        cfg[target] = rt.read_json(p)
        cfg[target + "_path"] = str(p)
        cfg[target + "_sha256"] = rt.sha256_file(p)
    return cfg


def main():
    cfg = load_config()
    visum = globals().get("Visum")
    if visum is None:
        visum = globals().get("COM")
    if visum is None:
        visum, _ = rt.get_visum()
    adapter = VisumAdapter(visum, cfg)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    folder = HERE / "R1_15A2_V2_3_RUNS" / ("RUN_" + stamp)
    result = run_calibration(adapter, cfg, folder, resume_from=os.environ.get("R1_15A2_V23_RESUME_FROM") or None)
    print("R1 15A2 V2.3: %s; evidence: %s" % (result["status"], folder))
    return result


if __name__ == "__main__":
    main()
