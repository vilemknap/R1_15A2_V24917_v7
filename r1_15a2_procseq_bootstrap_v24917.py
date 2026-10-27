# -*- coding: utf-8 -*-
"""V24917 PROCSEQFIX1: repair precisely approved operation 20 in a working copy.

Executed after source->WORKING_START semantic equality has been proved, before
live COM API preflight.  Never writes to the source .ver.  A failed repair
restores ACTIVE=0 and fails closed.  The only accepted model-semantic delta is
operations_hash, attributable to changing ACTIVE of approved PrT operation 20.
"""
from __future__ import annotations

import copy
from pathlib import Path

import r1_15a2_com_compat as com
import r1_15a2_core as core
import r1_15a2_restart_v2494 as restart
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError

SCHEMA = "R1_15A2_V24917_PROCSEQ_BOOTSTRAPFIX1"
APPROVED_OPERATION = 20
APPROVED_TYPE = com.ASSIGNMENT_PRT


def _check(condition, message):
    if not condition:
        raise SupplyContractError("PROCSEQFIX1_" + message)


def _inventory(visum):
    rows = com.operation_rows(visum)
    _check(len(rows) >= APPROVED_OPERATION, "INCOMPLETE_OPERATION_INVENTORY")
    nos = [int(row["no"]) for row in rows]
    _check(len(nos) == len(set(nos)), "DUPLICATE_OPERATION_POSITION")
    return rows


def _states(rows):
    return [(int(r["no"]), int(r["type"]), int(r["active"])) for r in rows]


def _approved_scope(row, cfg):
    approved = list((cfg.get("supply") or {}).get("assignment_operations") or [])
    _check(len(approved) == 1, "APPROVED_ASSIGNMENT_AUTHORITY_NOT_SINGLE")
    rule = approved[0]
    _check(int(rule["no"]) == APPROVED_OPERATION and
           int(rule["operation_type"]) == APPROVED_TYPE,
           "APPROVED_ASSIGNMENT_POSITION_OR_TYPE_CHANGED")
    obj = row["object"]
    for name in rule.get("dseg_object_path", ["PrTAssignmentParameters"]):
        _check(isinstance(name, str) and name.isidentifier() and not name.startswith("_"),
               "UNSAFE_COM_SCOPE_PROPERTY")
        obj = com.object_property(obj, name)
    attr = rule.get("dseg_attribute", "DSEGSET")
    scope = obj.AttValue(attr)
    _check(isinstance(scope, str), "DSEGSET_NOT_STRING")
    live = {core.norm_code(x) for x in com.code_set(scope, attr)}
    expected = {core.norm_code(x) for x in rule.get("expected_dsegs", [])}
    required = {core.norm_code(x) for x in (cfg.get("supply") or {}).get("passenger_dsegs", [])}
    required |= {core.norm_code(x) for x in (cfg.get("supply") or {}).get("freight_dsegs", [])}
    _check(bool(expected) and expected == live and required == live,
           "APPROVED_OPERATION_DSEGSET_MISMATCH")
    label = str(row.get("comment", "") or "") + " " + str(row.get("name", "") or "")
    _check("15A2" not in label.upper(), "RECURSIVE_MASTER_ASSIGNMENT")
    return {"operation": APPROVED_OPERATION, "type": APPROVED_TYPE,
            "dsegset": sorted(live), "verified_dseg_count": len(live)}


def _write(path, payload):
    rt.write_json(path, payload)


def _semantic_only_operation_change(before, after):
    _check(before.get("schema") == restart.SCHEMA and
           after.get("schema") == restart.SCHEMA, "SEMANTIC_SCHEMA_MISMATCH")
    other = [field for field in restart.SEMANTIC_FIELDS if field != "operations_hash"]
    altered = [key for key in other if before["semantic_hashes"][key] != after["semantic_hashes"][key]]
    _check(not altered, "UNEXPECTED_SEMANTIC_CHANGE:" + ",".join(altered))
    _check(before["semantic_hashes"]["operations_hash"] !=
           after["semantic_hashes"]["operations_hash"], "OPERATION_HASH_UNCHANGED")


def prepare_working_procseq(visum, adapter, cfg, folder, working_semantic,
                            source_semantic, *, save_version=None):
    """Prepare an already isolated, semantically verified working model.

    Returns a dictionary containing both a JSON-safe report and the semantic
    authority of the actual operational baseline for zero-acceptance final QA.
    """
    root = Path(folder)
    _check((root / "WORKING_START.ver").is_file(), "WORKING_START_NOT_SAVED")
    _check((root / "WORKING_COPY_SEMANTIC_IDENTITY.json").is_file(),
           "WORKING_COPY_IDENTITY_NOT_PUBLISHED")
    restart.require_authority_match(source_semantic, working_semantic,
                                    label="PROCSEQFIX1_SOURCE_WORKING_IDENTITY")
    source_path = Path(str(source_semantic.get("version_path_provenance") or ""))
    source_sha = source_semantic.get("raw_ver_sha256_provenance")
    if source_sha:
        _check(source_path.is_file(), "SOURCE_VER_FILE_MISSING")
        _check(rt.sha256_file(source_path) == source_sha, "SOURCE_VER_CHANGED_BEFORE_REPAIR")
    before_snap = adapter.snapshot()
    before_sem = restart.build_authority(before_snap, origin="PROCSEQFIX1_BEFORE")
    restart.require_authority_match(working_semantic, before_sem,
                                    label="PROCSEQFIX1_PRE_REPAIR_STATE")
    rows = _inventory(visum)
    by_pos = {int(r["no"]): r for r in rows}
    # No blind procedure modifications; require the known TG->TD->group->PrT layout.
    _check(int(by_pos.get(5, {}).get("type", -1)) == com.TG and
           int(by_pos[5]["active"]) == 1, "TG_OPERATION_UNEXPECTED")
    _check(int(by_pos.get(6, {}).get("type", -1)) == com.TD and
           int(by_pos[6]["active"]) == 1, "TD_OPERATION_UNEXPECTED")
    _check(int(by_pos.get(16, {}).get("type", -1)) == com.GROUP and
           int(by_pos[16]["active"]) == 1, "ASSIGNMENT_GROUP_UNEXPECTED")
    row = by_pos[APPROVED_OPERATION]
    _check(int(row["type"]) == APPROVED_TYPE, "OP20_TYPE_MISMATCH")
    scope = _approved_scope(row, cfg)
    old_states = _states(rows)
    original_active = int(row["active"])
    proc_before = rt.audit_procseq(visum, root / "PROCSEQ_BOOTSTRAP_BEFORE", cfg)

    if original_active:
        _check(proc_before["passes"], "ALREADY_ACTIVE_BUT_PROCSEQ_INVALID:" +
               ",".join(proc_before.get("reasons", [])))
        report = {"schema": SCHEMA, "status": "ALREADY_VALID", "changed": False,
                  "source_semantic_state_hash": source_semantic["semantic_state_hash"],
                  "operational_semantic_state_hash": before_sem["semantic_state_hash"],
                  "operation": scope, "original_operations": old_states,
                  "procseq_before": proc_before, "procseq_after": proc_before,
                  "save_version_called": False}
        _write(root / "PROCSEQ_BOOTSTRAPFIX1.json", report)
        return {"report": report, "operational_semantic": working_semantic}

    _check(proc_before["reasons"] == ["NO_ACTIVE_ASSIGNMENT"],
           "UNSAFE_SOURCE_PROCSEQ:" + ",".join(proc_before.get("reasons", [])))
    _check(not any(int(r["active"]) and int(r["type"]) == APPROVED_TYPE
                   for r in rows), "OTHER_ACTIVE_ASSIGNMENT_NOT_REVIEWED")
    _check(int(by_pos[17]["type"]) == APPROVED_TYPE and
           int(by_pos[18]["type"]) == APPROVED_TYPE and
           int(by_pos[19]["type"]) == APPROVED_TYPE,
           "PARTIAL_ASSIGNMENT_SEQUENCE_NOT_REVIEWED")
    for pos in (17, 18, 19):
        _check(int(by_pos[pos]["active"]) == 0, "PARTIAL_ASSIGNMENT_IS_ACTIVE")

    repaired_file = root / "WORKING_PROCSEQ_READY.ver"
    write_started = False
    success = False
    try:
        # The row is registered for restore BEFORE COM SetAttValue: a write may
        # succeed even if a subsequent readback fails.
        write_started = True
        row["object"].SetAttValue("ACTIVE", 1)
        _check(int(com.active_bool(row["object"].AttValue("ACTIVE"))) == 1,
               "OP20_ACTIVE_READBACK_FAILED")
        ready_rows = _inventory(visum)
        ready_states = _states(ready_rows)
        expected_states = [
            (pos, typ, 1 if pos == APPROVED_OPERATION else active)
            for pos, typ, active in old_states]
        _check(ready_states == expected_states, "UNEXPECTED_OPERATION_FLAGS_CHANGED")
        after_proc = rt.audit_procseq(visum, root / "PROCSEQ_BOOTSTRAP_AFTER", cfg)
        _check(after_proc["passes"] and after_proc["assignment_indices"] == [APPROVED_OPERATION],
               "PROCSEQ_STILL_INVALID:" + ",".join(after_proc.get("reasons", [])))
        after_snap = adapter.snapshot()
        after_sem = restart.build_authority(after_snap, origin="PROCSEQFIX1_WORKING_READY")
        _semantic_only_operation_change(before_sem, after_sem)
        writer = save_version if save_version is not None else rt.save_version
        saved = writer(visum, repaired_file)
        _check(repaired_file.is_file(), "PREPARED_CHECKPOINT_NOT_WRITTEN")
        verified_snap = adapter.snapshot()
        verified_sem = restart.build_authority(
            verified_snap, version_path=repaired_file,
            raw_ver_sha256=saved.get("sha256"), origin="PROCSEQFIX1_SAVED_READY")
        restart.require_authority_match(after_sem, verified_sem,
                                        label="PROCSEQFIX1_SAVE_SEMANTIC_IDENTITY")
        _check(_states(_inventory(visum)) == ready_states,
               "SAVEVERSION_CHANGED_OPERATION_FLAGS")
        if source_sha:
            _check(rt.sha256_file(source_path) == source_sha,
                   "SOURCE_VER_CHANGED_DURING_PREPARED_SAVE")
        _write(restart.sidecar_path(repaired_file), verified_sem)
        report = {"schema": SCHEMA, "status": "REPAIRED_WORKING_COPY", "changed": True,
                  "source_semantic_state_hash": source_semantic["semantic_state_hash"],
                  "working_copy_semantic_state_hash": working_semantic["semantic_state_hash"],
                  "operational_semantic_state_hash": verified_sem["semantic_state_hash"],
                  "operation": scope, "original_operations": old_states,
                  "prepared_operations": ready_states, "procseq_before": proc_before,
                  "procseq_after": after_proc, "prepared_checkpoint": saved,
                  "prepared_checkpoint_path": str(repaired_file),
                  "save_version_called": True,
                  "allowed_semantic_delta": ["operations_hash"],
                  "source_ver_file_modified": False}
        _write(root / "PROCSEQ_BOOTSTRAPFIX1.json", report)
        success = True
        return {"report": report, "operational_semantic": verified_sem}
    finally:
        if write_started and not success:
            errors = []
            try:
                row["object"].SetAttValue("ACTIVE", original_active)
                if _states(_inventory(visum)) != old_states:
                    errors.append("OPERATION_FLAGS_NOT_RESTORED")
                restored_sem = restart.build_authority(
                    adapter.snapshot(), origin="PROCSEQFIX1_FAILURE_RESTORE")
                restart.require_authority_match(before_sem, restored_sem,
                                                label="PROCSEQFIX1_FAILURE_RESTORE")
            except BaseException as exc:
                errors.append(str(exc))
            try:
                if repaired_file.is_file():
                    repaired_file.unlink()
                sidecar = restart.sidecar_path(repaired_file)
                if sidecar.is_file():
                    sidecar.unlink()
                _write(root / "PROCSEQ_BOOTSTRAPFIX1_FAILED.json", {
                    "schema": SCHEMA, "status": "REPAIR_FAILED",
                    "rollback_errors": errors,
                    "source_semantic_state_hash": source_semantic["semantic_state_hash"],
                })
            finally:
                if errors:
                    raise SupplyContractError("PROCSEQFIX1_ROLLBACK_NOT_VERIFIED:" + ";".join(errors))
