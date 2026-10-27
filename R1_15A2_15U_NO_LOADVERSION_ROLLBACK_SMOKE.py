# -*- coding: utf-8 -*-
"""R1 15A2 15U: controlled working-copy rollback smoke without LoadVersion.

This script TEMPORARILY mutates one supply parameter, one generation parameter,
and one TD parameter. Each mutation is recomputed, restored, recomputed again,
and required to return to the exact baseline snapshot and diagnostics.
Run only on a disposable working copy of the saved .ver.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import copy
import json
import traceback

import r1_15a2_runtime_v1 as rt
import r1_15a2_visum_parameters as vp
from r1_15a2_assignment_authority_v239 import audit_assignment_scope, config_rule_for_op20
from r1_15a2_controller_v22 import diagnostic_hash, assert_freeze
from r1_15a2_inplace_transaction_v239 import atomic_json, rollback_and_verify
from r1_15a2_supply import SupplyContractError, number
from r1_15a2_supply_visum import VisumAdapter

HERE = Path(__file__).resolve().parent
ACK_FILENAME = "15U_WORKING_COPY_ACK.txt"
ACK_TEXT = "I_CONFIRM_DISPOSABLE_WORKING_COPY"
WORKING_COPY_TOKEN = "15U_WORKING_COPY"


def load_cfg():
    d = json.loads((HERE / "R1_15A2_CONFIG_V2_3_9.json").read_text(encoding="utf-8"))
    d["apply"] = False
    d["supply"]["assignment_operations"] = [config_rule_for_op20()]
    return d


def version_path(visum):
    p = Path(str(visum.IO.CurrentVersionFile))
    if not p.is_file():
        raise RuntimeError("CURRENT_VERSION_FILE_NOT_FOUND")
    return p


def require_working_copy_ack(ver):
    ver = Path(ver)
    if WORKING_COPY_TOKEN not in ver.stem.upper():
        raise SupplyContractError("15U_WORKING_COPY_FILENAME_TOKEN_REQUIRED:" + WORKING_COPY_TOKEN)
    ack = ver.parent / ACK_FILENAME
    if not ack.is_file():
        raise SupplyContractError("15U_WORKING_COPY_ACK_MISSING:" + str(ack))
    text = ack.read_text(encoding="utf-8-sig").strip()
    if text != ACK_TEXT:
        raise SupplyContractError("15U_WORKING_COPY_ACK_CONTENT_INVALID")
    return {"path": str(ack), "expected_text": ACK_TEXT,
            "working_copy_filename": ver.name, "passes": True}


def require_15t_authority(ver):
    ver = Path(ver)
    root = ver.parent / "R1_15A2_15T_SAFETY_GATE"
    latest_file = root / "LATEST_RUN.txt"
    if not latest_file.is_file():
        raise SupplyContractError("15U_REQUIRES_15T_PASS_LATEST_RUN")
    latest = Path(latest_file.read_text(encoding="utf-8-sig").strip()).resolve()
    root_resolved = root.resolve()
    try:
        latest.relative_to(root_resolved)
    except Exception as exc:
        raise SupplyContractError("15T_LATEST_RUN_ESCAPES_GATE_ROOT") from exc
    authority_file = latest / "15T_SAFETY_GATE_RESULT.json"
    if not authority_file.is_file():
        raise SupplyContractError("15T_SAFETY_GATE_RESULT_MISSING")
    authority = json.loads(authority_file.read_text(encoding="utf-8"))
    if authority.get("status") != "PASS_ASSIGNMENT_SCOPE_AND_FULL_GEOMETRY_IDENTITY":
        raise SupplyContractError("15T_SAFETY_GATE_NOT_PASS")
    if not authority.get("assignment_scope", {}).get("passes"):
        raise SupplyContractError("15T_ASSIGNMENT_SCOPE_NOT_PASS")
    if authority.get("assignment_scope", {}).get("selected_trial_assignment_operations") != [20]:
        raise SupplyContractError("15T_ASSIGNMENT_SCOPE_NOT_OP20_ONLY")
    if not authority.get("full_geometry", {}).get("full_geometry_identity_proven"):
        raise SupplyContractError("15T_FULL_GEOMETRY_NOT_PROVEN")
    live_sha = rt.sha256_file(ver)
    if authority.get("version_sha256") != live_sha:
        raise SupplyContractError("15T_VERSION_SHA256_MISMATCH_WORKING_COPY")
    state_hash = authority.get("model_state_hash_after") or authority.get("model_state_hash_before")
    if not state_hash or authority.get("model_state_unchanged") is not True:
        raise SupplyContractError("15T_MODEL_STATE_AUTHORITY_INCOMPLETE")
    return {"authority_file": str(authority_file), "authority_version_file": authority.get("loaded_version_file"),
            "version_sha256": live_sha, "model_state_hash": state_hash, "passes": True}


def choose_supply_smoke(adapter, baseline_diag):
    observed = set()
    for row in baseline_diag["d12"]["rows"]:
        for key in row.get("edge_keys", []) or []:
            try:
                observed.add(tuple(int(x) for x in key))
            except Exception:
                pass
        if all(k in row for k in ("link_no", "from_node_no", "to_node_no")):
            try:
                observed.add((int(row["link_no"]), int(row["from_node_no"]), int(row["to_node_no"])))
            except Exception:
                pass
    links = adapter.read_links()
    candidates = [(k,v) for k,v in links.items() if v.get("eligible") and k not in observed]
    if not candidates:
        candidates = [(k,v) for k,v in links.items() if v.get("eligible")]
    if not candidates:
        raise SupplyContractError("NO_ELIGIBLE_LINK_FOR_SUPPLY_ROLLBACK_SMOKE")
    key,row = sorted(candidates, key=lambda kv:(kv[1].get("length",0),kv[0]))[0]
    old = number(row["addval1"])
    new = old + 0.001
    return {"changes": [{"key": list(key), "expected_old": old, "new": new, "delta": new-old}],
            "smoke_only": True, "delta_seconds": 0.01}


def choose_generation_smoke(adapter, before):
    attr = "ADD_PROD_W"
    vals = before["generation_values"][attr]
    eligible = set(adapter.actuatable_zones or adapter.zones)
    for z in adapter.zones:
        old = number(vals[str(z)])
        if z in eligible and old > 0:
            new = old * (1.0 + 1e-4)
            return [{"zone_no": z, "attr": attr, "current": old, "proposed": new,
                     "smoke_only": True}]
    raise SupplyContractError("NO_GENERATION_SMOKE_ZONE")


def choose_td_smoke(before):
    for old in before["td_values"]:
        if old.get("component") == "WORK_E_C":
            b = number(old["current_b"]); c = number(old["current_c"])
            return [{"component": old["component"], "candidate_b": b + 1e-4,
                     "candidate_c": c, "smoke_only": True}]
    old = before["td_values"][0]
    return [{"component": old["component"], "candidate_b": number(old["current_b"]) + 1e-4,
             "candidate_c": number(old["current_c"]), "smoke_only": True}]


def run_one(adapter, block, baseline_snapshot, baseline_diag, run_dir):
    out = Path(run_dir) / block
    out.mkdir(parents=True, exist_ok=True)
    baseline_hash = diagnostic_hash(baseline_diag)
    candidate = None
    rows = []
    mutated = False
    primary_error = None
    primary_traceback = None
    candidate_hash = None
    rollback_result = None
    rolled_diag = None
    try:
        if block == "SUPPLY_ADDVAL1":
            candidate = choose_supply_smoke(adapter, baseline_diag)
            atomic_json(out / "RECOVERY_AUTHORITY.json", {"block": block, "before_state_hash": baseline_snapshot["state_hash"],
                        "candidate": candidate, "policy": "TEMPORARY_WORKING_COPY_MUTATION_NO_LOADVERSION"})
            change = candidate["changes"][0]
            links = adapter.read_links(); key = tuple(change["key"]); obj = links[key]["object"]
            attr = adapter.cfg["supply"].get("link_attributes", {}).get("addval1", "ADDVAL1")
            mutated = True
            obj.SetAttValue(attr, change["new"])
            got = number(obj.AttValue(attr), "smoke ADDVAL1")
            if abs(got-change["new"]) > 1e-10:
                raise SupplyContractError("SMOKE_SUPPLY_READBACK_FAILED")
            adapter.assign(out / "CANDIDATE_RECOMPUTE", supply_only=True)
            after = adapter.snapshot()
            assert_freeze(baseline_snapshot, after, block, candidate=candidate, cfg=adapter.cfg)
        elif block == "GENERATION":
            rows = choose_generation_smoke(adapter, baseline_snapshot)
            atomic_json(out / "RECOVERY_AUTHORITY.json", {"block": block, "before_state_hash": baseline_snapshot["state_hash"],
                        "candidate_rows": rows, "policy": "TEMPORARY_WORKING_COPY_MUTATION_NO_LOADVERSION"})
            attr = rows[0]["attr"]
            values = [number(baseline_snapshot["generation_values"][attr][str(z)]) for z in adapter.zones]
            idx = adapter.zones.index(rows[0]["zone_no"]); values[idx] = rows[0]["proposed"]
            mutated = True
            rt.write_zone_attr(adapter.visum, attr, adapter.zones, values)
            adapter.assign(out / "CANDIDATE_RECOMPUTE", supply_only=False)
            after = adapter.snapshot()
            assert_freeze(baseline_snapshot, after, block, rows=rows, cfg=adapter.cfg)
        else:
            rows = choose_td_smoke(baseline_snapshot)
            atomic_json(out / "RECOVERY_AUTHORITY.json", {"block": block, "before_state_hash": baseline_snapshot["state_hash"],
                        "candidate_rows": rows, "policy": "TEMPORARY_WORKING_COPY_MUTATION_NO_LOADVERSION"})
            mutated = True
            audit = vp.apply_td_candidates(adapter.visum, rows)
            if not audit or any(x.get("status") != "OK" for x in audit):
                raise SupplyContractError("SMOKE_TD_READBACK_FAILED")
            adapter.assign(out / "CANDIDATE_RECOMPUTE", supply_only=False)
            after = adapter.snapshot()
            assert_freeze(baseline_snapshot, after, block, rows=rows, cfg=adapter.cfg)
        candidate_diag = adapter.diagnostics(out / "CANDIDATE_DIAGNOSTICS", "CANDIDATE")
        candidate_hash = diagnostic_hash(candidate_diag)
    except Exception as exc:
        primary_error = exc
        primary_traceback = traceback.format_exc()
    finally:
        if mutated:
            try:
                rollback_result, rolled_diag = rollback_and_verify(
                    adapter, block, baseline_snapshot, baseline_hash, diagnostic_hash,
                    out / "ROLLBACK", candidate_rows=rows, candidate=candidate)
            except Exception as exc:
                atomic_json(out / "15U_BLOCK_RESULT.json", {
                    "block": block, "passes": False,
                    "primary_error": None if primary_error is None else str(primary_error),
                    "primary_traceback": primary_traceback,
                    "rollback_error": str(exc), "rollback_traceback": traceback.format_exc(),
                    "manual_reopen_required": True, "load_version_called": False,
                })
                raise SupplyContractError("15U_ROLLBACK_FAILED_MANUAL_REOPEN_REQUIRED:" + block) from exc
    if primary_error is not None:
        atomic_json(out / "15U_BLOCK_RESULT.json", {
            "block": block, "passes": False, "primary_error": str(primary_error),
            "primary_traceback": primary_traceback, "rollback_verified": bool(rollback_result and rollback_result.get("passes")),
            "manual_reopen_required": False, "load_version_called": False,
        })
        raise primary_error
    rollback_result["candidate_diagnostic_hash"] = candidate_hash
    rollback_result["baseline_diagnostic_hash"] = baseline_hash
    atomic_json(out / "15U_BLOCK_RESULT.json", rollback_result)
    return rollback_result, rolled_diag


def main(visum):
    ver = version_path(visum)
    root = ver.parent / "R1_15A2_15U_ROLLBACK_SMOKE"
    root.mkdir(parents=True, exist_ok=True)
    run = root / ("RUN_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run.mkdir(); (root / "LATEST_RUN.txt").write_text(str(run), encoding="utf-8")
    result = {"schema": "R1_15A2_15U_NO_LOADVERSION_ROLLBACK_SMOKE_V239",
              "status": "STARTED", "loaded_version_file": str(ver),
              "temporary_mutations": True, "working_copy_required": True,
              "load_version_called": False, "save_version_called": False,
              "direct_od_matrix_writes": False, "blocks": []}
    cfg = load_cfg()
    baseline_snapshot = None
    baseline_diag = None
    try:
        ack = require_working_copy_ack(ver)
        atomic_json(run / "15U_WORKING_COPY_ACK.json", ack)
        geometry_authority = require_15t_authority(ver)
        atomic_json(run / "15U_15T_AUTHORITY.json", geometry_authority)
    except Exception as exc:
        result.update(status="BLOCKED_WORKING_COPY_ACK_REQUIRED", error=str(exc), traceback=traceback.format_exc())
        atomic_json(run / "15U_ROLLBACK_SMOKE_RESULT.json", result)
        (run / "00_FINAL_STATUS.txt").write_text(result["status"] + "\n", encoding="utf-8")
        return result
    adapter = VisumAdapter(visum, cfg)
    baseline_diag = None
    try:
        initial_state = adapter.snapshot()
        if initial_state["state_hash"] != geometry_authority["model_state_hash"]:
            raise SupplyContractError("15U_INITIAL_MODEL_STATE_DIFFERS_FROM_15T")
        atomic_json(run / "15U_INITIAL_STATE_MATCH.json", {
            "passes": True, "state_hash": initial_state["state_hash"],
            "15t_state_hash": geometry_authority["model_state_hash"]})
        scope = audit_assignment_scope(visum)
        atomic_json(run / "15U_ASSIGNMENT_SCOPE.json", scope)
        if not scope["passes"]:
            raise SupplyContractError("15U_ASSIGNMENT_SCOPE_FAILED")
        preflight = adapter.preflight(run / "PREFLIGHT")
        if not preflight.get("apply_preflight_passes"):
            raise SupplyContractError("15U_PREFLIGHT_NOT_APPLY_READY")
        # Establish a fresh, deterministic baseline using the model's full active Procedure Sequence.
        adapter.assign(run / "BASELINE_FULL_RECOMPUTE", supply_only=False)
        baseline_snapshot = adapter.snapshot()
        baseline_diag = adapter.diagnostics(run / "BASELINE_DIAGNOSTICS", "BASELINE")
        atomic_json(run / "BASELINE_AUTHORITY.json", {"state_hash": baseline_snapshot["state_hash"],
                    "diagnostic_hash": diagnostic_hash(baseline_diag)})
        for block in ("SUPPLY_ADDVAL1", "GENERATION", "TD_COMPONENT_WORK"):
            if adapter.snapshot() != baseline_snapshot:
                raise SupplyContractError("15U_NOT_AT_BASELINE_BEFORE_BLOCK:" + block)
            block_result, rolled_diag = run_one(adapter, block, baseline_snapshot, baseline_diag, run)
            result["blocks"].append(block_result)
            if not block_result["passes"]:
                raise SupplyContractError("15U_BLOCK_ROLLBACK_FAILED:" + block)
            baseline_diag = rolled_diag
        result["status"] = "PASS_NO_LOADVERSION_ROLLBACK_SUPPLY_GENERATION_TD"
    except Exception as exc:
        result.update(status="FAILED_PENDING_FINAL_RECOVERY_CHECK", error=str(exc), traceback=traceback.format_exc())
    finally:
        try:
            if baseline_snapshot is not None and adapter.snapshot() == baseline_snapshot:
                result["final_baseline_snapshot_restored"] = True
                if result.get("status") == "FAILED_PENDING_FINAL_RECOVERY_CHECK":
                    result["status"] = "FAILED_BUT_BASELINE_SNAPSHOT_RESTORED"
            elif baseline_snapshot is not None:
                result["final_baseline_snapshot_restored"] = False
                if result.get("status") != "PASS_NO_LOADVERSION_ROLLBACK_SUPPLY_GENERATION_TD":
                    result["status"] = "MANUAL_REOPEN_REQUIRED_BASELINE_NOT_RESTORED"
        except Exception as exc:
            result["final_baseline_snapshot_restored"] = None
            result["final_snapshot_error"] = str(exc)
            if baseline_snapshot is not None:
                result["status"] = "MANUAL_REOPEN_REQUIRED_FINAL_STATE_UNVERIFIED"
        atomic_json(run / "15U_ROLLBACK_SMOKE_RESULT.json", result)
        (run / "00_FINAL_STATUS.txt").write_text(result["status"] + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    main(Visum)
