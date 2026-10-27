# -*- coding: utf-8 -*-
"""PREFLIGHT2: no stale assignment results required; failing preflight explains itself."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r1_15a2_preflight_explain_v24917 as p2  # noqa: E402
from r1_15a2_supply import SupplyContractError  # noqa: E402


def test_gap_unavailable_alone_is_deferred():
    plan = {"passes": False, "reasons": ["ASSIGNMENT_GAP_READBACK_UNAVAILABLE:PRT_ASS_QUALITY_LIST empty"]}
    w = p2._wrap_plan(lambda v, c: dict(plan))
    out = w(None, {})
    assert out["passes"] is True and out["reasons"] == []
    assert out["gap_readback_status"] == "DEFERRED_TO_BASELINE_FULL_RECOMPUTE"


def test_other_reasons_still_block():
    plan = {"passes": False, "reasons": ["ASSIGNMENT_GAP_READBACK_UNAVAILABLE:x",
                                         "APPROVED_ASSIGNMENT_OPERATION_MISMATCH:20"]}
    out = p2._wrap_plan(lambda v, c: dict(plan))(None, {})
    assert out["passes"] is False and len(out["reasons"]) == 2
    ok = {"passes": True, "reasons": []}
    assert p2._wrap_plan(lambda v, c: dict(ok))(None, {}) == ok


def test_failed_preflight_raises_with_reasons(tmp_path):
    (tmp_path / "00_PREFLIGHT.json").write_text(json.dumps({
        "tg": {"passes": True}, "procseq": {"passes": True},
        "supply_assignment": {"passes": True, "reasons": []},
        "unsafe_minimum_cost_keys": [[9800632, 9900317, 9900316]]}))

    def orig(self, folder):
        raise SupplyContractError("V240_LIVE_RECOMPUTE_PREFLIGHT_FAILED")
    w = p2._wrap_preflight(orig, SupplyContractError)
    with pytest.raises(SupplyContractError, match=r"LINKS_T0_PLUS_ADDVAL_NOT_POSITIVE\(1\).*9800632"):
        w(None, tmp_path)
    info = json.loads((tmp_path / "00_PREFLIGHT_FAILURE_EXPLAINED.json").read_text())
    assert info["links_outside_positive_cost_domain_count"] == 1


def test_other_errors_untouched(tmp_path):
    def orig(self, folder):
        raise SupplyContractError("V240_OP20_SCOPE_AUTHORITY_FAILED")
    with pytest.raises(SupplyContractError, match="^V240_OP20_SCOPE_AUTHORITY_FAILED$"):
        p2._wrap_preflight(orig, SupplyContractError)(None, tmp_path)


def test_install_live(monkeypatch):
    import r1_15a2_supply_visum as sv
    import r1_15a2_trial_adapter_v240 as a240
    monkeypatch.setattr(sv, "assignment_plan", sv.assignment_plan)
    monkeypatch.setattr(a240.VisumAdapter, "preflight", a240.VisumAdapter.preflight)
    monkeypatch.setattr(sv.VisumAdapter, "read_links", sv.VisumAdapter.read_links)
    monkeypatch.setitem(p2._STATE, "installed", False)
    p2.install()
    assert getattr(sv.assignment_plan, "__r1_preflight2__")
    assert getattr(a240.VisumAdapter.preflight, "__r1_preflight2__")
    assert getattr(sv.VisumAdapter.read_links, "__r1_preflight2__")
    import inspect
    assert "assignment_plan(self.visum, self.cfg)" in inspect.getsource(sv.VisumAdapter.preflight)
    monkeypatch.setitem(p2._STATE, "installed", False)


def test_zero_cost_links_excluded_not_blocking(monkeypatch):
    """Live 25.10. 21:04: 4 links (3 new after a network edit) with t0_C + 10*ADDVAL1 < 0.001 s."""
    monkeypatch.setitem(p2._STATE, "zero_cost_links", [])
    rows = {(8001203, 9000273, 9000289): {"t0_c_seconds": 0.0, "addval1": 0.0, "eligible": True, "length": 0.0},
            (9800570, 9000289, 9900299): {"t0_c_seconds": 0.0, "addval1": 0.0, "eligible": True, "length": 0.0},
            (1, 2, 3): {"t0_c_seconds": 12.0, "addval1": 0.0, "eligible": True, "length": 0.2},
            (4, 5, 6): {"t0_c_seconds": 0.0, "addval1": 0.0, "eligible": False, "length": 0.0}}
    lines = []
    w = p2._wrap_read_links(lambda self: {k: dict(v) for k, v in rows.items()}, lines.append)
    adapter = SimpleNamespace(policy=SimpleNamespace(minimum_cost_seconds=0.001))
    out = w(adapter)
    assert out[(8001203, 9000273, 9000289)]["eligible"] is False
    assert out[(9800570, 9000289, 9900299)]["eligible"] is False
    assert out[(1, 2, 3)]["eligible"] is True
    assert set(out[(1, 2, 3)]) == set(rows[(1, 2, 3)])          # no new keys (fixed-link hash unchanged)
    assert len(p2._STATE["zero_cost_links"]) == 2 and "9800570" in lines[0]
    w(adapter)                                                    # second read: no duplicate warning
    assert len(lines) == 1 and len(p2._STATE["zero_cost_links"]) == 2
    # the inherited preflight check now finds nothing unsafe among eligible links
    unsafe = [k for k, r in out.items() if r["eligible"] and r["t0_c_seconds"] + 10 * r["addval1"] < 0.001]
    assert unsafe == []
