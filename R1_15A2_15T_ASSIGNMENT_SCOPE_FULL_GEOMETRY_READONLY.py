# -*- coding: utf-8 -*-
"""R1 15A2 15T: read-only assignment-scope and full path-link identity gate."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import json
import traceback

import r1_15a2_runtime_v1 as rt
from r1_15a2_supply_visum import VisumAdapter
from r1_15a2_assignment_authority_v239 import audit_assignment_scope
from r1_15a2_full_geometry_gate_v239 import GateControl, GateStop, atomic_json, audit_full_geometry

PASSENGERS = [
    "NATIVE_CW", "NATIVE_CW_noT", "NATIVE_CS", "NATIVE_CS_noT", "NATIVE_CL", "NATIVE_CF",
    "EXOG_EE_CW", "EXOG_EE_CW_noT", "EXOG_EE_CS", "EXOG_EE_CS_noT", "EXOG_EE_CL", "EXOG_EE_CF",
]


def _load_cfg():
    here = Path(__file__).resolve().parent
    return json.loads((here / "R1_15A2_CONFIG_V2_3_9.json").read_text(encoding="utf-8"))


def _version_path(visum):
    p = Path(str(visum.IO.CurrentVersionFile))
    if not p.exists():
        raise RuntimeError("CURRENT_VERSION_FILE_NOT_FOUND")
    return p


def main(visum):
    ver = _version_path(visum)
    root = ver.parent / "R1_15A2_15T_SAFETY_GATE"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run = root / ("RUN_" + stamp)
    run.mkdir()
    (root / "LATEST_RUN.txt").write_text(str(run), encoding="utf-8")
    control = GateControl(run, max_seconds=8*3600.0)
    result = {"schema": "R1_15A2_15T_SAFETY_GATE_V239", "status": "STARTED",
              "loaded_version_file": str(ver), "version_sha256": rt.sha256_file(ver),
              "apply": False, "assignment_executed": False,
              "writes_to_visum": False, "load_version_called": False, "save_version_called": False}
    try:
        adapter = VisumAdapter(visum, _load_cfg())
        before_state = adapter.snapshot()
        result["model_state_hash_before"] = before_state["state_hash"]
        scope = audit_assignment_scope(visum)
        atomic_json(run / "15T_ASSIGNMENT_SCOPE.json", scope)
        result["assignment_scope"] = scope
        if not scope["passes"]:
            raise RuntimeError("ASSIGNMENT_SCOPE_GATE_FAILED:" + ";".join(scope["failures"]))
        control.checkpoint("ASSIGNMENT_SCOPE_PASS", force=True)
        geometry = audit_full_geometry(visum, PASSENGERS, run, control)
        result["full_geometry"] = geometry
        if not geometry.get("full_geometry_identity_proven"):
            raise RuntimeError("FULL_GEOMETRY_IDENTITY_NOT_PROVEN")
        after_state = adapter.snapshot()
        result["model_state_hash_after"] = after_state["state_hash"]
        result["model_state_unchanged"] = after_state == before_state
        if after_state != before_state:
            raise RuntimeError("15T_READ_ONLY_STATE_DRIFT")
        result["status"] = "PASS_ASSIGNMENT_SCOPE_AND_FULL_GEOMETRY_IDENTITY"
        control.finish(result["status"])
    except GateStop as exc:
        result.update(status="STOPPED", error=str(exc))
        control.finish("STOPPED", error=str(exc))
    except Exception as exc:
        result.update(status="FAILED", error=str(exc), traceback=traceback.format_exc())
        try:
            control.finish("FAILED", error=str(exc))
        except Exception:
            pass
    finally:
        atomic_json(run / "15T_SAFETY_GATE_RESULT.json", result)
        (run / "00_FINAL_STATUS.txt").write_text(result["status"] + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    main(Visum)
