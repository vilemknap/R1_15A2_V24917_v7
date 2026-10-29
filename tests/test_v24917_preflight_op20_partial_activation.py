"""Live 2026-10-29 V240 preflight: inactive 09C partials, active OP20.

The historical V239 module must remain sealed. Test the active V24917 overlay.
"""
from types import SimpleNamespace as NS

import pytest

from conftest import FakeAttr, FakeOperation, FakeVisum
import r1_15a2_assignment_authority_v239 as v239
import r1_15a2_preflight_explain_v24917 as overlay


PARTIAL = {
    17: "LNV,NV",
    18: "NATIVE_CF,NATIVE_CL",
    19: "NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT",
}
FULL = (
    "EXOG_EE_CF,EXOG_EE_CL,EXOG_EE_CS,EXOG_EE_CS_noT,"
    "EXOG_EE_CW,EXOG_EE_CW_noT,LNV,NATIVE_CF,NATIVE_CL,"
    "NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT,NV"
)


def model(active_partials=(), op20_active=True):
    ops = [
        FakeOperation(NO=no, OPERATIONTYPE=(45 if no == 5 else (46 if no == 6 else 65)),
                      ACTIVE=1, NAME="", COMMENT="")
        for no in range(1, 17)
    ]
    for no in (17, 18, 19, 20):
        ops.append(FakeOperation(
            NO=no, OPERATIONTYPE=101, ACTIVE=int(no == 20 and op20_active or no in active_partials),
            NAME="", COMMENT="R1 09C PrT assignment",
            PrTAssignmentParameters=FakeAttr(DSEGSET=FULL if no == 20 else PARTIAL[no])))
    return FakeVisum(operations=ops)


def audit(visum):
    return overlay._wrap_inactive_partial_scope_audit(v239.audit_assignment_scope)(visum)


def test_exact_live_op20_only_passes_without_modifying_source_or_operations():
    visum = model()
    before = [op.AttValue("ACTIVE") for op in visum.Procedures.Operations.items]
    assert v239.audit_assignment_scope(visum)["failures"] == [
        "OP_17_INACTIVE", "OP_18_INACTIVE", "OP_19_INACTIVE"
    ]
    report = audit(visum)
    assert report["passes"] is True and report["failures"] == []
    assert report["selected_trial_assignment_operations"] == [20]
    assert report["validated_inactive_partial_operations"] == [17, 18, 19]
    assert [x["status"] for x in report["verified_operations"]] == [
        "PASS_INACTIVE_PARTIAL", "PASS_INACTIVE_PARTIAL",
        "PASS_INACTIVE_PARTIAL", "PASS"
    ]
    assert all(x["live_dsegs"] == x["expected_dsegs"]
               for x in report["verified_operations"])
    assert [op.AttValue("ACTIVE") for op in visum.Procedures.Operations.items] == before


@pytest.mark.parametrize("position", [17, 18, 19])
def test_inactive_partial_wrong_dseg_is_hard_failure(position):
    visum = model()
    visum.Procedures.Operations.items[position - 1].PrTAssignmentParameters.SetAttValue(
        "DSEGSET", PARTIAL[position] + ",EXTRA")
    report = audit(visum)
    assert not report["passes"]
    assert report["selected_trial_assignment_operations"] == []
    assert "OP_%d_DSEGSET" % position in report["failures"]
    detail = next(x for x in report["verified_operations"] if x["no"] == position)
    assert "EXTRA" in detail["extra"]


@pytest.mark.parametrize("position", [17, 18, 19])
def test_unreadable_or_duplicate_inactive_scope_is_not_approved(position):
    visum = model()
    visum.Procedures.Operations.items[position - 1].PrTAssignmentParameters.SetAttValue(
        "DSEGSET", "LNV,LNV")
    report = audit(visum)
    assert not report["passes"]
    assert "OP_%d_UNREADABLE" % position in report["failures"]


def test_final_op20_must_be_active():
    result = audit(model(op20_active=False))
    assert not result["passes"] and "OP_20_INACTIVE" in result["failures"]
    assert result["selected_trial_assignment_operations"] == []


def test_op20_fourteen_dseg_drift_cannot_be_bypassed():
    visum = model()
    visum.Procedures.Operations.items[19].PrTAssignmentParameters.SetAttValue(
        "DSEGSET", "NATIVE_CW,LNV,NV")
    result = audit(visum)
    assert not result["passes"]
    assert "OP_20_DSEGSET" in result["failures"]
    assert result["selected_trial_assignment_operations"] == []


def test_inactive_partial_wrong_type_cannot_be_bypassed():
    visum = model()
    visum.Procedures.Operations.items[16].SetAttValue("OPERATIONTYPE", 65)
    result = audit(visum)
    assert not result["passes"]
    assert "OP_17_TYPE" in result["failures"]


def test_mixed_active_partial_and_inactive_partials_are_valid_if_exact():
    result = audit(model(active_partials=(17, 19)))
    assert result["passes"] and result["failures"] == []
    assert result["validated_inactive_partial_operations"] == [18]
    assert result["selected_trial_assignment_operations"] == [20]


def test_v240_preflight_integration_writes_real_audit(tmp_path, monkeypatch):
    import json
    import r1_15a2_trial_adapter_v240 as a240
    import r1_15a2_supply_visum as supply
    monkeypatch.setattr(a240, "audit_assignment_scope",
                        overlay._wrap_inactive_partial_scope_audit(a240.audit_assignment_scope))
    monkeypatch.setattr(supply.VisumAdapter, "preflight",
                        lambda self, folder: {"apply_preflight_passes": True})
    monkeypatch.setattr(a240.VisumAdapter, "snapshot", lambda self: {"identity": "verified"})
    adapter = object.__new__(a240.VisumAdapter)
    adapter.visum = model()
    adapter.control = NS(checkpoint=lambda *args, **kwargs: None)
    result = a240.VisumAdapter.preflight(adapter, tmp_path)
    assert result["apply_preflight_passes"] is True
    report = json.loads((tmp_path / "00_V240_ASSIGNMENT_SCOPE.json").read_text(encoding="utf-8"))
    assert report["passes"] and report["selected_trial_assignment_operations"] == [20]
    assert report["validated_inactive_partial_operations"] == [17, 18, 19]
