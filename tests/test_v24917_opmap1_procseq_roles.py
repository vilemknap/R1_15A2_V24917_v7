"""OPMAP1: procedure-sequence roles resolved on the legacy 43-op and the 2026-11 53-op layout."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import r1_15a2_procseq_roles_v24917 as roles  # noqa: E402
import r1_15a2_fast_trial_assignment_v24917 as fa  # noqa: E402
import r1_15a2_supply_mix_v24917 as sm  # noqa: E402
from r1_15a2_assignment_authority_v239 import audit_assignment_scope  # noqa: E402

FINAL = ("EXOG_EE_CF,EXOG_EE_CL,EXOG_EE_CS,EXOG_EE_CS_noT,EXOG_EE_CW,EXOG_EE_CW_noT,LNV,"
         "NATIVE_CF,NATIVE_CL,NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT,NV")
CSCW = "NATIVE_CS,NATIVE_CS_noT,NATIVE_CW,NATIVE_CW_noT"


@pytest.fixture(autouse=True)
def _fresh_role_cache():
    roles._RESOLVED.clear()
    yield
    roles._RESOLVED.clear()


class Params:
    def __init__(self, dseg):
        self.dseg = dseg

    def AttValue(self, name):
        assert name == "DSEGSET"
        return self.dseg


class Op:
    def __init__(self, typ, active=1, comment="", dseg=None):
        self.typ, self.active, self.comment = typ, active, comment
        self.PrTAssignmentParameters = Params(dseg) if dseg is not None else None

    def AttValue(self, name):
        return {"OPERATIONTYPE": self.typ, "ACTIVE": self.active, "COMMENT": self.comment,
                "NAME": ""}[name]


def new_layout():
    """2026-11-11 procedure_sequence_aktualni.xml (53 operations)."""
    ops = [Op(9, comment="reset before TG"), Op(75), Op(65, comment="14A COUTRY_ADD Preset"), Op(75),
           Op(75), Op(45), Op(75), Op(65, comment="OSRM times"), Op(75), Op(46), Op(75),
           Op(65, comment="Foreign Matrix Post Processing"), Op(75), Op(75), Op(65, comment="kappa audit"),
           Op(65, comment="kappa-band"), Op(75, comment="R1 20D"), Op(65), Op(75), Op(91), Op(75),
           Op(65, comment="Matrix Symmetrization"), Op(9, comment="reset after demand"), Op(75),
           Op(101, dseg="LNV,NV"), Op(101, dseg="NATIVE_CF,NATIVE_CL"), Op(101, dseg=CSCW),
           Op(101, dseg=FINAL), Op(65, comment="GEH (EXOG_EE_CF, ...)"), Op(75)]
    ops += [Op(103, active=0) for _ in range(8)] + [Op(103) for _ in range(6)]
    ops += [Op(9, active=0), Op(101, active=0, dseg="LNV,NV"), Op(101, active=0, dseg=FINAL + ",R1_OA"),
            Op(75, active=0), Op(1, active=0), Op(101, active=0, dseg=FINAL), Op(65, active=0),
            Op(75, active=0), Op(107, active=0)]
    assert len(ops) == 53
    return ops


def legacy_layout():
    ops = [Op(9), Op(75), Op(65, active=0), Op(75), Op(45), Op(46), Op(75), Op(65), Op(75), Op(65),
           Op(65), Op(91), Op(75), Op(65), Op(9), Op(75), Op(101, dseg="LNV,NV"),
           Op(101, dseg="NATIVE_CF,NATIVE_CL"), Op(101, dseg=CSCW), Op(101, dseg=FINAL),
           Op(65, comment="GEH"), Op(75, active=0)]
    ops += [Op(103) for _ in range(14)] + [Op(9, active=0), Op(101, active=0), Op(101, active=0),
                                           Op(75, active=0), Op(1, active=0), Op(101, active=0),
                                           Op(65, active=0)]
    assert len(ops) == 43
    return ops


class Coll:
    def __init__(self, ops):
        self.ops = ops

    @property
    def GetAll(self):
        return tuple(self.ops)


class Visum:
    def __init__(self, ops):
        self.Procedures = type("P", (), {})()
        self.Procedures.Operations = Coll(ops)


def test_legacy_layout_is_identity():
    r = roles.resolve(Visum(legacy_layout()))
    assert r["mode"] == "LEGACY_IDENTITY"
    assert r["legacy_to_live"] == {1: 1, 15: 15, 17: 17, 18: 18, 19: 19, 20: 20, 21: 21}


def test_new_layout_resolved_by_signature():
    r = roles.resolve(Visum(new_layout()))
    assert r["mode"] == "RESOLVED_BY_SIGNATURE"
    assert r["legacy_to_live"] == {1: 1, 15: 23, 17: 25, 18: 26, 19: 27, 20: 28, 21: 29}
    assert r["td_position"] == 10 and r["tg_positions"] == [6]
    assert roles.live_position(Visum(new_layout()), 20) == 28
    assert roles.live_position(Visum(new_layout()), 7) == 7      # not a role: unchanged


def test_ambiguous_or_missing_role_fails_closed():
    ops = new_layout()
    ops[45].active = 1                                          # second active LNV,NV assignment
    with pytest.raises(roles.OpmapError, match="ASG_FREIGHT_FOUND_2"):
        roles.resolve(Visum(ops))
    ops = new_layout()
    ops[22].active = 0                                          # no reset after the new demand
    with pytest.raises(roles.OpmapError, match="RESET_POST_FOUND_0"):
        roles.resolve(Visum(ops))


def test_assignment_authority_uses_live_positions():
    audit = roles._wrap_scope(audit_assignment_scope)
    rep = audit(Visum(new_layout()))
    assert rep["passes"], rep["failures"]
    # legacy role numbering (sealed V240 still requires [20]) with the live positions alongside
    assert rep["selected_trial_assignment_operations"] == [20] and rep["gap_operation_live_no"] == 28
    assert [d["no"] for d in rep["verified_operations"]] == [17, 18, 19, 20]
    assert [d["live_no"] for d in rep["verified_operations"]] == [25, 26, 27, 28]
    rep = audit(Visum(legacy_layout()))
    assert rep["passes"] and rep["selected_trial_assignment_operations"] == [20]
    assert "live_no" not in rep["verified_operations"][0]                    # untouched parent path


def test_live_cfg_translates_positions_and_keeps_legacy_cfg():
    cfg = {"supply": {"assignment_operations": [{"no": 20, "operation_type": 101}],
                      "gap_readback": {"operation_no": 20, "source": "PRT_ASS_QUALITY_LIST"}},
           "performance": {"v24915_perf1": {"phase_specific_procseq": {
               "safe_post_assignment_operations": [{"position": 21, "operation_type": 65}]}}}}
    live = roles.live_cfg(Visum(new_layout()), cfg)
    assert live["supply"]["assignment_operations"][0]["no"] == 28
    assert live["supply"]["gap_readback"]["operation_no"] == 28
    assert live["performance"]["v24915_perf1"]["phase_specific_procseq"][
        "safe_post_assignment_operations"][0]["position"] == 29
    assert cfg["supply"]["assignment_operations"][0]["no"] == 20             # original untouched
    assert roles.live_cfg(Visum(legacy_layout()), cfg) is cfg
    assert roles.live_spec(Visum(new_layout()), cfg["supply"]["gap_readback"])["operation_no"] == 28


def test_translator_keeps_reduced_harness_and_rejects_wrong_type():
    rows = [{"no": 20, "position": 20, "type": 101, "active": 1, "comment": ""}]
    assert roles.translator(rows)(20) == 20
    rows = [{"no": 20, "position": 20, "type": 75, "active": 1, "comment": ""}]
    with pytest.raises(roles.OpmapError):
        roles.translator(rows)(20)


def _plan_inventory(ops):
    return [{"no": i, "type": op.typ, "active": op.active, "comment": op.comment}
            for i, op in enumerate(ops, 1)]


def test_fast_trial_skip_positions_follow_the_live_layout():
    inv = _plan_inventory(new_layout())
    selected = [r["no"] for r in inv if r["active"] and r["no"] <= 28]
    base = {"inventory": inv, "selected_operation_positions": selected,
            "approved_assignment_positions": [28], "original_active_operation_positions": selected}
    out = fa.fast_plan(base, "GENERATION", {"skip_positions": [1, 15, 17, 18, 19]})
    assert out["v24917_fast_trial"]["applied"], out["v24917_fast_trial"]
    assert out["v24917_fast_trial"]["skipped_positions"] == [1, 23, 25, 26, 27]
    assert 28 in out["selected_operation_positions"] and 23 not in out["selected_operation_positions"]


def test_supplymix_cold_plan_reset_follows_the_live_layout():
    inv = _plan_inventory(new_layout())
    base = {"inventory": inv, "approved_assignment_positions": [28],
            "selected_operation_positions": [28]}
    out = sm.cold_supply_plan(base, {}, 15)
    info = out["v24917_supplymix_plan"]
    assert info["applied"] and info["reset_position"] == 23
    assert {23, 25, 26, 27, 28} <= set(out["selected_operation_positions"])


def test_isolated_flags_reuse_the_proven_resolution():
    roles._RESOLVED.clear()
    ops = new_layout()
    assert roles.resolve(Visum(ops))["legacy_to_live"][20] == 28
    for i, op in enumerate(ops):                     # FineCDF bridge: only the TD op stays active
        if op.typ != 75:
            op.active = int(i == 9)
    r = roles.resolve(Visum(ops))
    assert r["legacy_to_live"][20] == 28 and "ASG_FREIGHT_FOUND_0" in r["reused_after"]
    cfg = {"supply": {"assignment_operations": [{"no": 20, "operation_type": 101}]}}
    assert roles.live_cfg(Visum(ops), cfg)["supply"]["assignment_operations"][0]["no"] == 28
    roles._RESOLVED.clear()
    with pytest.raises(roles.OpmapError):              # never proven -> still fails closed
        roles.resolve(Visum(ops))
