# -*- coding: utf-8 -*-
"""Counterfactual PERF1/PERF2 control-flow parity on the inherited TD replay."""
from __future__ import annotations

from pathlib import Path

import r1_15a2_overnight_controller_coupled_v24915p1 as p1
import r1_15a2_overnight_controller_coupled_v24915p2 as p2
from r1_15a2_supply import canonical_hash
from test_v2490_td_soft_reference import (
    Control,
    SoftAdapter,
    _parent,
    _restore,
    _soft_cfg,
)


def _run(module, root: Path, monkeypatch):
    adapter = SoftAdapter(always_reject=True)
    before = _parent(adapter)
    baseline = adapter.diagnostics(root / "base", "BASE")
    monkeypatch.setattr(module, "restore_td_parameters", _restore)
    monkeypatch.setattr(module, "diagnostic_hash", lambda d: canonical_hash(d))
    rows, after, diag, gap, evidence = module._realize_finecdf_td(
        adapter,
        _soft_cfg((1.0, 0.5, 0.25)),
        root / "realization",
        Control(),
        before,
        baseline,
        [{"component": "WORK_E_C", "candidate_b": 0.0, "candidate_c": -0.1}],
    )
    return {
        "rows": rows,
        "after": after,
        "diag": diag,
        "gap": gap,
        "evidence": evidence,
        "assign_calls": list(adapter.assign_calls),
    }


def test_perf2_preserves_perf1_candidate_order_and_plateau_result(tmp_path, monkeypatch):
    a = _run(p1, tmp_path / "p1", monkeypatch)
    b = _run(p2, tmp_path / "p2", monkeypatch)
    assert b["rows"] == a["rows"]
    assert b["after"] == a["after"]
    assert b["diag"] == a["diag"]
    assert b["gap"] == a["gap"]
    assert b["assign_calls"] == a["assign_calls"]
    assert [x["status"] for x in b["evidence"]["attempts"]] == \
        [x["status"] for x in a["evidence"]["attempts"]]
    assert b["evidence"]["status"] == a["evidence"]["status"] == "SOFT_REFERENCE_PLATEAU"
    assert b["after"]["state_hash"] == a["after"]["state_hash"]
