# -*- coding: utf-8 -*-
"""Executable reproductions of 2026-10-27 NO_ACTIVE_ASSIGNMENT preflight failure."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

import r1_15a2_procseq_bootstrap_v24917 as fix
import r1_15a2_restart_v2494 as restart
from r1_15a2_supply import SupplyContractError


class Op:
    def __init__(self, type, active=0, params=None, comment=""):
        self.type = type
        self.active = int(active)
        self.comment = comment
        if params is not None:
            self.PrTAssignmentParameters = params
        self.fail_readback = False
        self.fail_write = False

    def AttValue(self, key):
        if key == "OPERATIONTYPE": return self.type
        if key == "ACTIVE": return 0 if self.fail_readback else self.active
        if key == "COMMENT": return self.comment
        if key == "NAME": return ""
        raise KeyError(key)

    def SetAttValue(self, key, value):
        assert key == "ACTIVE"
        if self.fail_write: raise RuntimeError("simulated COM write failure")
        self.active = int(value)


class Params:
    def __init__(self, names):
        self.names = ",".join(names)
    def AttValue(self, attr):
        assert attr == "DSEGSET"
        return self.names


class OpCollection:
    def __init__(self, objs):
        self.objs = objs
        self.Count = len(objs)
    def GetAll(self): return self.objs


DS = ["LNV", "NV", "NATIVE_CW", "NATIVE_CW_noT", "NATIVE_CS", "NATIVE_CS_noT",
      "NATIVE_CL", "NATIVE_CF", "EXOG_EE_CW", "EXOG_EE_CW_noT", "EXOG_EE_CS",
      "EXOG_EE_CS_noT", "EXOG_EE_CL", "EXOG_EE_CF"]


def fixture(tmp_path, active=False, *, wrong_type=False, extra_assignment=False):
    ops = [Op(75) for _ in range(43)]
    ops[4] = Op(45, 1)
    ops[5] = Op(46, 1)
    ops[15] = Op(75, 1)
    for i in (16,17,18): ops[i] = Op(101)
    ops[19] = Op(75 if wrong_type else 101, int(active), Params(DS), "joint freight + native passenger")
    if extra_assignment: ops[18].active = 1
    visum = SimpleNamespace(Procedures=SimpleNamespace(Operations=OpCollection(ops)))
    cfg = {"require_active_tg_td": True, "require_active_assignment": True,
           "supply": {"assignment_operations": [
               {"no": 20, "operation_type": 101,
                "dseg_object_path": ["PrTAssignmentParameters"],
                "dseg_attribute": "DSEGSET", "expected_dsegs": DS}],
               "passenger_dsegs": DS[2:], "freight_dsegs": DS[:2]}}
    class Adapter:
        invalid_altered_field = False
        def snapshot(self):
            flags = ",".join(str(op.active) for op in ops)
            digest = hashlib.sha256(flags.encode()).hexdigest()
            result = dict.fromkeys(restart.SEMANTIC_FIELDS, "a"*64)
            result["operations_hash"] = digest
            if self.invalid_altered_field and ops[19].active:
                result["matrix_hash"] = "b"*64
            result["state_hash"] = digest
            return result
    adapter = Adapter()
    source = restart.build_authority(adapter.snapshot(), origin="TEST_SOURCE")
    (tmp_path / "WORKING_START.ver").write_bytes(b"PRISTINE SOURCE WORKING COPY")
    (tmp_path / "WORKING_COPY_SEMANTIC_IDENTITY.json").write_text("{}")
    saved = []
    def save_version(_visum, file):
        f = Path(file)
        f.write_bytes(b"DERIVED PREPARED WORKING VERSION" + str(ops[19].active).encode())
        saved.append(f)
        return {"sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "size": f.stat().st_size, "path":str(f)}
    return visum, adapter, cfg, source, save_version, ops, saved


def prepare(bag, tmp_path):
    v, adapter, cfg, source, saver, _, _ = bag
    return fix.prepare_working_procseq(v, adapter, cfg, tmp_path, source, source, save_version=saver)


def test_real_20261027_profile_sequence_repaired_only_op20(tmp_path):
    bag = fixture(tmp_path)
    before = bag[1].snapshot()
    result = prepare(bag, tmp_path)
    assert result["report"]["status"] == "REPAIRED_WORKING_COPY"
    assert result["report"]["operation"]["verified_dseg_count"] == 14
    assert result["report"]["procseq_before"]["reasons"] == ["NO_ACTIVE_ASSIGNMENT"]
    assert result["report"]["procseq_after"]["passes"] is True
    assert result["report"]["procseq_after"]["assignment_indices"] == [20]
    assert [i for i, op in enumerate(bag[5], 1) if op.active and op.type == 101] == [20]
    assert bag[1].snapshot()["matrix_hash"] == before["matrix_hash"]
    assert bag[1].snapshot()["operations_hash"] != before["operations_hash"]
    assert (tmp_path / "WORKING_START.ver").read_bytes() == b"PRISTINE SOURCE WORKING COPY"
    assert (tmp_path / "WORKING_PROCSEQ_READY.ver").is_file()
    assert restart.load_optional_sidecar(tmp_path / "WORKING_PROCSEQ_READY.ver")
    assert result["report"]["allowed_semantic_delta"] == ["operations_hash"]
    assert len(bag[6]) == 1


def test_already_active_does_not_write_or_save(tmp_path):
    bag = fixture(tmp_path, active=True)
    out = prepare(bag, tmp_path)
    assert out["report"]["status"] == "ALREADY_VALID"
    assert not bag[6]


def test_wrong_operation_type_refused_without_model_write(tmp_path):
    bag = fixture(tmp_path, wrong_type=True)
    with pytest.raises(SupplyContractError, match="PROCSEQFIX1_OP20_TYPE_MISMATCH"):
        prepare(bag, tmp_path)
    assert not bag[6]
    assert bag[5][19].active == 0


def test_wrong_dseg_set_refused(tmp_path):
    bag = fixture(tmp_path)
    bag[5][19].PrTAssignmentParameters.names = "LNV,NV"
    with pytest.raises(SupplyContractError, match="PROCSEQFIX1_APPROVED_OPERATION_DSEGSET_MISMATCH"):
        prepare(bag, tmp_path)
    assert not bag[6]


def test_uncertified_extra_active_assignment_refused(tmp_path):
    bag = fixture(tmp_path, extra_assignment=True)
    with pytest.raises(SupplyContractError, match="PROCSEQFIX1_UNSAFE_SOURCE_PROCSEQ|PROCSEQFIX1_OTHER_ACTIVE_ASSIGNMENT"):
        prepare(bag, tmp_path)
    assert bag[5][19].active == 0


def test_unexpected_matrix_mutation_rolls_back(tmp_path):
    bag = fixture(tmp_path)
    bag[1].invalid_altered_field = True
    with pytest.raises(SupplyContractError, match="PROCSEQFIX1_UNEXPECTED_SEMANTIC_CHANGE"):
        prepare(bag, tmp_path)
    assert bag[5][19].active == 0
    assert not bag[6]
    assert (tmp_path / "PROCSEQ_BOOTSTRAPFIX1_FAILED.json").is_file()


def test_save_version_error_rolls_back(tmp_path):
    bag = fixture(tmp_path)
    def fail(_visum, _path): raise RuntimeError("simulated disk full")
    with pytest.raises(RuntimeError, match="simulated disk full"):
        fix.prepare_working_procseq(bag[0], bag[1], bag[2], tmp_path, bag[3], bag[3], save_version=fail)
    assert bag[5][19].active == 0
    assert not (tmp_path / "WORKING_PROCSEQ_READY.ver").exists()


def test_com_write_failure_rolls_back(tmp_path):
    bag = fixture(tmp_path)
    bag[5][19].fail_write = True
    with pytest.raises(SupplyContractError, match="PROCSEQFIX1_ROLLBACK_NOT_VERIFIED"):
        prepare(bag, tmp_path)
    assert bag[5][19].active == 0


def test_working_identity_missing_disallows_writes(tmp_path):
    bag = fixture(tmp_path)
    (tmp_path / "WORKING_COPY_SEMANTIC_IDENTITY.json").unlink()
    with pytest.raises(SupplyContractError, match="PROCSEQFIX1_WORKING_COPY_IDENTITY_NOT_PUBLISHED"):
        prepare(bag, tmp_path)
    assert bag[5][19].active == 0


def test_sealed_main_integration_contains_preflight_repair_and_zero_accept_baseline():
    name = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_FRESH100_TGTD100_ONLY_SEMFIX1_NO_WALLCLOCK.py"
    code = (Path(__file__).parents[1] / name).read_text(encoding="utf-8")
    assert code.index("WORKING_COPY_SEMANTIC_IDENTITY") < code.index("prepare_working_procseq(")
    assert code.index("prepare_working_procseq(") < code.index("api_audit.collect_live_api(")
    assert 'operational_semantic if result.get("accepted_count", 0) == 0' in code
