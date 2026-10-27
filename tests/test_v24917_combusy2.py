# -*- coding: utf-8 -*-
"""COMBUSY2: rejected Visum calls (RPC_E_CALL_REJECTED) no longer end the run."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r1_15a2_com_compat as com  # noqa: E402
import r1_15a2_combusy2_v24917 as cb  # noqa: E402


class Rejected(Exception):
    def __init__(self):
        super().__init__(-2147418111, "Volaný odmítl volání.", None, None)
        self.hresult = -2147418111


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    monkeypatch.setattr(cb, "_pump_sleep", lambda s: None)


def test_rejected_error_is_recognised():
    assert com.is_retryable_com_error(Rejected())


def test_budget_floor_extends_inherited_policy(monkeypatch):
    monkeypatch.setattr(com, "_retry_budget", com._retry_budget)
    live = {"enabled": True, "max_attempts": 5, "initial_delay_seconds": 0.05,
            "backoff_factor": 2.0, "max_delay_seconds": 0.8}
    assert com._retry_budget(live)[0] == 5
    cb.install_budget_floor(com, 900.0)
    attempts, initial, factor, maximum, elapsed = com._retry_budget(live)
    assert attempts >= 900 and maximum >= 2.0 and elapsed == 900.0
    assert com._retry_budget({"enabled": False})[0] == 1        # disabled stays disabled
    # a call rejected 30 times (live: ~1.5 s budget) now succeeds
    n = {"k": 0}

    def call():
        n["k"] += 1
        if n["k"] <= 30:
            raise Rejected()
        return "OK"
    assert com.com_call_with_retry(call, retry_policy=live, sleep_fn=lambda s: None) == "OK"


def test_message_filter_fail_open_without_pywin32():
    rep = cb.install_message_filter(10.0)
    assert set(rep) >= {"registered"}
    if sys.platform != "win32":
        assert rep["registered"] is False


def test_rollback_retried_on_rejection():
    calls = []

    def rollback(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise Rejected()
        return ("rb", "diag")
    w = cb._wrap_rollback(rollback, com, 900.0)
    assert w() == ("rb", "diag") and len(calls) == 3


def test_rollback_other_errors_propagate():
    w = cb._wrap_rollback(lambda *a: (_ for _ in ()).throw(ValueError("x")), com, 900.0)
    with pytest.raises(ValueError):
        w()


def _adapter(state, same=True):
    return SimpleNamespace(snapshot=lambda: state if same else {"other": 1})


def test_block_repeated_from_intact_parent():
    state = {"h": 1}
    calls = []

    def block(adapter, cfg, folder, control, st, *rest):
        calls.append(folder)
        if len(calls) == 1:
            from r1_15a2_supply import SupplyContractError
            try:
                raise Rejected()
            except Rejected as e:
                raise SupplyContractError("V245_GENERATION_TRIAL_ERROR_NOT_A_PLATEAU") from e
        return "DONE"
    w = cb._wrap_block(block, com, "GENERATION", 1, 3)
    assert w(_adapter(state), {}, Path("G"), "ctl", state, "diag") == "DONE"
    assert [str(c) for c in calls] == ["G", "G_RETRY1"]


def test_block_not_repeated_if_parent_changed_or_error_not_transient():
    state = {"h": 1}

    def block(*a, **k):
        raise Rejected()
    w = cb._wrap_block(block, com, "TD", 1, 3)
    with pytest.raises(Rejected):
        w(_adapter(state, same=False), {}, Path("T"), "ctl", state)
    w2 = cb._wrap_block(lambda *a, **k: (_ for _ in ()).throw(KeyError("x")), com, "TD", 1, 3)
    with pytest.raises(KeyError):
        w2(_adapter(state), {}, Path("T"), "ctl", state)


def test_block_retry_limit():
    state = {"h": 1}
    n = {"k": 0}

    def block(*a, **k):
        n["k"] += 1
        raise Rejected()
    w = cb._wrap_block(block, com, "GENERATION", 1, 2)
    with pytest.raises(Rejected):
        w(_adapter(state), {}, Path("G"), "ctl", state)
    assert n["k"] == 3


def test_install_live_modules(monkeypatch):
    import importlib
    com = importlib.import_module("r1_15a2_com_compat")          # current sys.modules object
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    for mod, name in ((com, "_retry_budget"), (base, "_rollback_candidate"),
                      (ctrl, "_generation_update_once_impl"), (ctrl, "_finecdf_td_once")):
        monkeypatch.setattr(mod, name, getattr(mod, name))
    monkeypatch.setitem(cb._STATE, "installed", False)
    st = cb.install(print_fn=lambda *a: None)
    assert st["installed"] and getattr(com._retry_budget, "__r1_combusy2__")
    assert getattr(base._rollback_candidate, "__r1_combusy2__")
    import inspect
    # state is the 5th positional parameter of both blocks (args[1] after adapter, cfg, folder)
    for fn in (ctrl._generation_update_once_impl, ctrl._finecdf_td_once):
        inner = inspect.unwrap(fn)
        assert list(inspect.signature(inner).parameters)[4] == "state"
    monkeypatch.setitem(cb._STATE, "installed", False)


@pytest.mark.parametrize("variant", ["no_iid", "register_raises", "no_server_util"])
def test_message_filter_fail_open_on_visum_pywin32(monkeypatch, variant):
    """Live 25.10. 20:51: Visum's pywin32 has no pythoncom.IID_IMessageFilter -> must not abort the run."""
    import types
    pc = types.ModuleType("pythoncom")
    pc.PumpWaitingMessages = lambda: None
    if variant == "register_raises":
        pc.IID_IMessageFilter = "{00000016-0000-0000-C000-000000000046}"

        def boom(f):
            raise RuntimeError("no gateway")
        pc.CoRegisterMessageFilter = boom
    elif variant == "no_iid":
        pc.CoRegisterMessageFilter = lambda f: None
    win32com = types.ModuleType("win32com")
    server = types.ModuleType("win32com.server")
    util = types.ModuleType("win32com.server.util")
    util.wrap = lambda o: o
    monkeypatch.setitem(sys.modules, "pythoncom", pc)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.server", server)
    if variant != "no_server_util":
        monkeypatch.setitem(sys.modules, "win32com.server.util", util)
    else:
        monkeypatch.setitem(sys.modules, "win32com.server.util", None)
    rep = cb.install_message_filter(900.0)
    assert rep["registered"] is False and rep["reason"]


def test_install_survives_broken_message_filter(monkeypatch):
    import importlib
    com = importlib.import_module("r1_15a2_com_compat")
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    for mod, name in ((com, "_retry_budget"), (base, "_rollback_candidate"),
                      (ctrl, "_generation_update_once_impl"), (ctrl, "_finecdf_td_once")):
        monkeypatch.setattr(mod, name, getattr(mod, name))
    monkeypatch.setitem(cb._STATE, "installed", False)
    monkeypatch.setattr(cb, "install_message_filter",
                        lambda w: (_ for _ in ()).throw(AttributeError("module 'pythoncom' has no attribute "
                                                                      "'IID_IMessageFilter'")))
    lines = []
    st = cb.install(print_fn=lines.append)
    assert st["installed"] and st["message_filter"]["registered"] is False
    assert "message filter: OFF" in lines[0]
    monkeypatch.setitem(cb._STATE, "installed", False)
