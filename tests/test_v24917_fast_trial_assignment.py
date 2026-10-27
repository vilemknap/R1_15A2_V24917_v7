# -*- coding: utf-8 -*-
"""FASTASSIGN1: warm-start Generation trials, cold (full AMDY) rollback and adoption."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r1_15a2_acceleration_v24915p1 as perf1  # noqa: E402
import r1_15a2_fast_trial_assignment_v24917 as fa  # noqa: E402
from r1_15a2_supply import SupplyContractError  # noqa: E402

CFG = json.loads((ROOT / "tests" / "data" / "EFFECTIVE_CONFIG_RUN_20261025_175302.json")
                 .read_text(encoding="utf-8"))

# live Procedure Sequence (09_PROCEDURE_OPERATIONS.csv, run 2026-10-25): (type, active)
LIVE_OPS = [(9, 1), (75, 1), (65, 0), (75, 1), (45, 1), (46, 1), (75, 1), (65, 1), (75, 1),
            (65, 1), (65, 1), (91, 1), (75, 1), (65, 1), (9, 1), (75, 1), (101, 1), (101, 1),
            (101, 1), (101, 1), (65, 1), (75, 1)] + [(103, 0)] * 8 + [(103, 1)] * 6 + \
           [(9, 0), (101, 0), (101, 0), (75, 0), (1, 0), (101, 0), (65, 0)]
COMMENTS = {21: "GEH (EXOG_EE_CF, NATIVE_CW)"}


class Op:
    def __init__(self, typ, active, comment=""):
        self.v = {"OPERATIONTYPE": typ, "ACTIVE": active, "COMMENT": comment, "NAME": ""}

    def AttValue(self, a):
        return self.v[a]

    def SetAttValue(self, a, x):
        self.v[a] = int(x)


def make_visum():
    ops = [Op(t, a, COMMENTS.get(i, "")) for i, (t, a) in enumerate(LIVE_OPS, 1)]
    return SimpleNamespace(Procedures=SimpleNamespace(Operations=SimpleNamespace(GetAll=ops)))


@pytest.fixture(autouse=True)
def opts(monkeypatch):
    monkeypatch.setattr(fa, "options", lambda: {"enabled": True, "skip_positions": [1, 15, 17, 18, 19],
                                                "blocks": ["GENERATION"]})


def active(visum):
    return [i for i, op in enumerate(visum.Procedures.Operations.GetAll, 1) if int(op.v["ACTIVE"])]


def test_live_generation_plan_falls_back_full_and_fast_plan_skips_resets_and_preloads():
    v = make_visum()
    base = perf1.phase_recompute_plan(v, CFG, "GENERATION")
    # active skims 31-36 after op 20 are not reviewed post-assignment ops -> full sequence
    assert base["mode"] == "FULL_SEQUENCE_FALLBACK"
    plan = fa.fast_plan(base, "GENERATION", fa.options())
    info = plan["v24917_fast_trial"]
    assert info["applied"] is True and info["joint_assignment"] == 20
    sel = plan["selected_operation_positions"]
    for p in (1, 15, 17, 18, 19):
        assert p not in sel
    for p in (5, 6, 11, 12, 14, 20, 21, 31, 36):
        assert p in sel
    # flags are switched for one execution only and restored exactly
    before = active(v)
    with perf1.activate_operation_plan(v, plan):
        assert active(v) == sel
    assert active(v) == before


@pytest.mark.parametrize("pos,typ", [(17, 65), (15, 101), (20, 9)])
def test_fast_plan_fail_closed_on_unexpected_sequence(pos, typ):
    v = make_visum()
    v.Procedures.Operations.GetAll[pos - 1].v["OPERATIONTYPE"] = typ
    base = perf1.phase_recompute_plan(v, CFG, "GENERATION")
    plan = fa.fast_plan(base, "GENERATION", fa.options())
    assert plan["v24917_fast_trial"]["applied"] is False
    assert plan["selected_operation_positions"] == base["selected_operation_positions"]


def test_fast_plan_refuses_skipping_the_joint_assignment():
    v = make_visum()
    base = perf1.phase_recompute_plan(v, CFG, "GENERATION")
    plan = fa.fast_plan(base, "GENERATION", {"skip_positions": [1, 15, 17, 18, 19, 20]})
    assert plan["v24917_fast_trial"]["applied"] is False


# ------------------------------------------------------------------ flow
class FlowHarness:
    """Mirrors v24915p2 _evaluate_candidate / rollback / _adopt_candidate call structure."""

    def __init__(self, adopt_rejects=0):
        self.visum = make_visum()
        self.plans = []
        self.adopt_rejects = adopt_rejects
        self.adopt_cfgs = []

    def assign_for_block(self, folder, block):          # adapter
        plan = perf1.phase_recompute_plan(self.visum, CFG, block)
        self.plans.append((folder, plan.get("mode")))
        return 0.001

    # module-level functions of the controller
    def make(self):
        h = self

        def _assign_candidate(adapter, folder, block):
            return adapter.assign_for_block(folder, block)

        def _evaluate_candidate(adapter, cfg, policy, block, candidate, folder):
            base_ctrl._assign_candidate(adapter, str(folder) + "/TRIAL", block)
            adapter.assign_for_block(str(folder) + "/ROLLBACK", block)       # rollback recompute
            return {"eligible": True, "candidate": candidate}, "diag", None

        def _adopt_candidate(adapter, cfg, policy, block, best, folder):
            h.adopt_cfgs.append(cfg["trial_calibration"].get("require_reproducible_reapply"))
            base_ctrl._assign_candidate(adapter, str(folder) + "/ADOPT", block)
            if h.adopt_rejects > 0:
                h.adopt_rejects -= 1
                adapter.assign_for_block(str(folder) + "/ADOPT_ROLLBACK", block)
                raise SupplyContractError("ADOPTION_REJECTED:NEW_SEVERE_GEH_PROFILE")
            return "adopted"

        def _generation_update_once_impl(adapter, cfg, folder):
            ev, _d, _e = ctrl._evaluate_candidate(adapter, cfg, None, "GENERATION", {"scale": 1.0}, folder)
            out = ctrl._adopt_candidate(adapter, cfg, None, "GENERATION", ev, folder)
            return True, "state", "diag", 0.0, {"status": out}

        base_ctrl = SimpleNamespace(_assign_candidate=_assign_candidate)
        ctrl = SimpleNamespace(_evaluate_candidate=_evaluate_candidate, _adopt_candidate=_adopt_candidate,
                               _generation_update_once_impl=_generation_update_once_impl)
        base_ctrl._assign_candidate = fa._wrap_assign(base_ctrl._assign_candidate)
        ctrl._evaluate_candidate = fa._wrap_evaluate(ctrl._evaluate_candidate)
        ctrl._adopt_candidate = fa._wrap_adopt(ctrl._adopt_candidate, SupplyContractError)
        ctrl._generation_update_once_impl = fa._wrap_generation_impl(ctrl._generation_update_once_impl)
        return ctrl


@pytest.fixture
def wrapped_plan(monkeypatch):
    monkeypatch.setattr(perf1, "phase_recompute_plan", fa._wrap_plan(perf1.phase_recompute_plan))


def test_flow_trial_warm_rollback_and_adoption_cold(wrapped_plan):
    h = FlowHarness()
    ctrl = h.make()
    cfg = {"trial_calibration": {"require_reproducible_reapply": True}}
    res = ctrl._generation_update_once_impl(h, cfg, "F")
    modes = dict(h.plans)
    assert modes["F/TRIAL"] == "V24917_FAST_WARM_TRIAL"
    assert modes["F/ROLLBACK"] == "FULL_SEQUENCE_FALLBACK"
    assert modes["F/ADOPT"] == "FULL_SEQUENCE_FALLBACK"
    assert h.adopt_cfgs == [False]                    # cold adoption re-decides, no warm/cold hash check
    assert cfg["trial_calibration"]["require_reproducible_reapply"] is True   # caller cfg untouched
    assert res[4]["status"] == "adopted"


def test_flow_cold_adoption_rejection_repeats_block_with_cold_trials(wrapped_plan):
    h = FlowHarness(adopt_rejects=1)
    ctrl = h.make()
    cfg = {"trial_calibration": {"require_reproducible_reapply": True}}
    res = ctrl._generation_update_once_impl(h, cfg, "F")
    modes = dict(h.plans)
    assert modes["F/TRIAL"] == "V24917_FAST_WARM_TRIAL"
    assert modes["F/COLD_RETRY/TRIAL"] == "FULL_SEQUENCE_FALLBACK"
    assert h.adopt_cfgs == [False, True]              # retry: classic reproducibility check again
    assert res[4]["status"] == "adopted" and "v24917_fast_trial_cold_retry" in res[4]


def test_flow_disabled_runs_everything_cold(wrapped_plan, monkeypatch):
    monkeypatch.setattr(fa, "options", lambda: {"enabled": False, "skip_positions": [1, 15, 17, 18, 19],
                                                "blocks": ["GENERATION"]})
    h = FlowHarness()
    ctrl = h.make()
    ctrl._generation_update_once_impl(h, {"trial_calibration": {}}, "F")
    assert all(m == "FULL_SEQUENCE_FALLBACK" for _f, m in h.plans)
    assert h.adopt_cfgs == [None]                     # cfg passed through unchanged (no override)


def test_td_block_never_warm(wrapped_plan):
    h = FlowHarness()
    base = SimpleNamespace(_assign_candidate=fa._wrap_assign(lambda a, f, b: a.assign_for_block(f, b)))
    fa._LOCAL.eval_scope = True
    try:
        base._assign_candidate(h, "TD", "TD_FINECDF")
    finally:
        fa._LOCAL.eval_scope = False
    assert dict(h.plans)["TD"] != "V24917_FAST_WARM_TRIAL"


def test_options_validation_and_defaults(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options(root=tmp_path, environ={})
    assert o["fa_enabled"] is True and o["fa_skip_positions"] == [1, 15, 17, 18, 19]
    assert o["fa_blocks"] == ["GENERATION"]
    o = dp.load_options(root=tmp_path, environ={"R1_FA_ENABLED": "0", "R1_FA_SKIP_POSITIONS": "17;18"})
    assert o["fa_enabled"] is False and o["fa_skip_positions"] == [17, 18]
    with pytest.raises(RuntimeError):
        dp.load_options(root=tmp_path, environ={"R1_FA_BLOCKS": "TD_FINECDF"})
    live = dp.load_options(root=ROOT, environ={})
    assert live["fa_enabled"] is True


def test_install_wraps_live_controller(monkeypatch):
    import importlib
    perf1 = importlib.import_module("r1_15a2_acceleration_v24915p1")   # current sys.modules object
    import r1_15a2_trial_adapter_v24915p2 as ad2
    assert ad2.perf1 is perf1          # adapters resolve the plan through this module attribute
    import r1_15a2_overnight_controller_v24915p2 as base_ctrl
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    for mod, name in ((perf1, "phase_recompute_plan"), (base_ctrl, "_assign_candidate"),
                      (ctrl, "_evaluate_candidate"), (ctrl, "_adopt_candidate"),
                      (ctrl, "_generation_update_once_impl")):
        monkeypatch.setattr(mod, name, getattr(mod, name))
    monkeypatch.setitem(fa._STATE, "installed", False)
    st = fa.install(print_fn=lambda *a: None)
    assert st["installed"]
    assert getattr(perf1.phase_recompute_plan, "__r1_fastassign__")
    assert getattr(base_ctrl._assign_candidate, "__r1_fastassign__")
    assert getattr(ctrl._adopt_candidate, "__r1_fastassign__")
    assert getattr(ctrl._generation_update_once_impl, "__r1_fastassign__")
    json.dumps(fa.status())
    # _evaluate_candidate in v24915p2 resolves _assign_candidate through the module global
    import inspect
    src = inspect.getsource(base_ctrl._evaluate_candidate.__wrapped__
                            if hasattr(base_ctrl._evaluate_candidate, "__wrapped__")
                            else base_ctrl._evaluate_candidate)
    assert "_assign_candidate(adapter" in src
    # force100 generation loop calls the module-global names
    src = inspect.getsource(ctrl._generation_update_once_impl.__wrapped__)
    assert "_evaluate_candidate(" in src and "_adopt_candidate(" in src
    src = inspect.getsource(ctrl._generation_update_once)
    assert "_generation_update_once_impl(" in src
    monkeypatch.setitem(fa._STATE, "installed", False)
