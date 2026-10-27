# -*- coding: utf-8 -*-
"""Run manually from Visum Scripts, NOT inside Procedure Sequence.

V2.3.7: live-scoped PrT quality GAP readback candidate; 09F4 TG unchanged. Default: design-only. ADDVAL1 +1 = +10 generalized SECONDS.
Live APPLY requires approved operation IDs/types/DSeg scope and gap readback.
"""
from pathlib import Path
import json
import os
import sys
import csv
from datetime import datetime

HERE = Path(__file__).resolve().parent
# A Visum interpreter survives repeated Script operations. Do not reuse a
# cached module from a different package/release; do not touch PTV or other apps.
if globals().get("Visum") is not None or globals().get("COM") is not None:
    if getattr(sys, "_r1_15a2_calibration_busy", False):
        raise RuntimeError("RECURSIVE_CALIBRATION_MASTER: run master outside Procedure Sequence")
    for name in list(sys.modules):
        if name.startswith("r1_15a2_"):
            del sys.modules[name]
sys.path.insert(0, str(HERE))
import r1_15a2_com_compat as com
import r1_15a2_live_api_audit as api_audit
import r1_15a2_visum_parameters as vp
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply_visum_v23 import VisumAdapter
from r1_15a2_controller_v22 import run_calibration
from r1_15a2_supply import canonical_hash


def load_config():
    path = HERE / "R1_15A2_CONFIG_V2_3_7.json"
    cfg = rt.read_json(path)
    cfg["apply"] = rt.env_bool("R1_15A2_V237_APPLY", cfg["apply"])
    cfg["config_path"] = str(path)
    cfg["config_sha256"] = rt.sha256_file(path)
    implementation_files = [
        "R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_7.py", "r1_15a2_com_compat.py",
        "r1_15a2_live_api_audit.py", "r1_15a2_controller_v22.py",
        "r1_15a2_sequence_v23.py", "r1_15a2_supply_visum_v23.py",
        "r1_15a2_supply.py", "r1_15a2_supply_visum.py", "r1_15a2_runtime_v1.py",
        "r1_15a2_core.py", "r1_15a2_multiblock.py", "r1_15a2_visum_parameters.py",
        "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py",
        "helpers/R1_11D_V1_3_COMPONENT_DIST_BEHAVIOR_DIAGNOSTICS.py",
        "helpers/R1_12D_CSD2022_GEH_FORENSIC_444_PROCSEQ_EMBEDDED.py",
        "helpers/R1_12D_CSD2022_GEH_FORENSIC_408_APPROVED.py",
        "helpers/R1_12D_CSD408_CITY90_RPDI_498_APPROVED.py",
        "authorities/R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv",
        "authorities/R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_90.csv"]
    cfg["implementation_hash"] = canonical_hash({name: rt.sha256_file(HERE / name) for name in implementation_files})
    for key, target in (("tg_dependency_contract_file", "tg_dependency_contract"),
                        (None, "long_authority")):
        rel = cfg[key] if key else cfg["td"]["long_authority_file"]
        p = HERE / rel
        cfg[target] = rt.read_json(p)
        cfg[target + "_path"] = str(p)
        cfg[target + "_sha256"] = rt.sha256_file(p)
    cfg["api_approved_observations"] = []
    for filename in ("R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv", "R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_90.csv"):
        with (HERE / "authorities" / filename).open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                cfg["api_approved_observations"].append({"no": int(row["countlocation_no"]),
                    "observed": float(row["observed_passenger_cars_O"]), "role": row["role"],
                    "weight": float(row["live_weight"]),
                    "edge_key": [int(row[k]) for k in ("current_link_no","current_from_node_no","current_to_node_no")],
                    "direction": row.get("observation_direction", "DIRECTIONAL"),
                    "countlocation_code": row["countlocation_code"],
                    "profile_id": row["profile_id"],
                    "period_basis": row["period_basis"],
                    "observed_scope": row.get("vehicle_scope_original", row.get("vehicle_scope"))})
    return cfg


def main():
    # No GetActiveObject/Dispatch fallback. Never start a blank Visum instance.
    visum, connection = com.bind_injected(globals())
    cfg = load_config()
    root, output_source = api_audit.project_output_root(visum)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    folder = root.parent / "R1_15A2_V2_3_7_RUNS" / ("RUN_" + stamp)
    folder.mkdir(parents=True, exist_ok=False)
    rt.Visum = visum
    def td_check():
        state = vp.read_td_parameter_state(visum)
        return {"passes": all(x["status"] == "OK" for x in state["rows"]),
                "rows": state["rows"], "operation_rows": state["operation_rows"]}
    if cfg.get("run_full_com_api_audit", True):
        report = api_audit.collect_live_api(visum, cfg, folder / "API_PREFLIGHT", extra_checks=(
            ("TG_FORMULA_PARAMETER_BINDINGS", lambda: vp.audit_trip_generation_contract(visum, cfg)),
            ("TD_COMPONENT_PARAMETER_BINDINGS", td_check),
            ("PROCSEQ_TYPE_ORDER", lambda: rt.audit_procseq(visum, folder / "API_PREFLIGHT", cfg))))
        if report["required_failures"] or cfg.get("api_audit_only", False):
            result = {"status": report["status"], "calibration_started": False,
                      "report": str(folder / "API_PREFLIGHT" / "COM_API_PREFLIGHT.json")}
            rt.write_json(folder / "00_RESULT.json", result)
            return result
    if cfg["apply"]:
        for flag in ("csd408_mapping_review_acknowledged", "city90_bidirectional_qa_acknowledged"):
            if not cfg.get(flag, False):
                result = {"status": "APPLY_REVIEW_PENDING", "reason": flag, "calibration_started": False}
                rt.write_json(folder / "00_RESULT.json", result)
                return result
    adapter = VisumAdapter(visum, cfg)
    sys._r1_15a2_calibration_busy = True
    try:
        result = run_calibration(adapter, cfg, folder / "CALIBRATION",
                   resume_from=os.environ.get("R1_15A2_V237_RESUME_FROM") or None)
    finally:
        sys._r1_15a2_calibration_busy = False
    rt.write_json(folder / "00_RESULT.json", result)
    return result


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
