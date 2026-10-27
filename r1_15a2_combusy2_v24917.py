# -*- coding: utf-8 -*-
"""COMBUSY2 (V24917): survive Visum "call rejected" (RPC_E_CALL_REJECTED) episodes.

Live run RUN_20261025_181651, cycle 3 (19:2x): the 11D helper of the adopted
Generation step got ``com_error(-2147418111, 'Volaný odmítl volání.')`` five times
within ~1.5 s (the inherited retry budget), and the rollback that followed failed
on the very first COM attribute access (``visum.Net.Zones``, outside any retry)
-> FAILED_MANUAL_REOPEN_LATEST_ACCEPTED_REQUIRED.  Visum rejects calls while its
UI thread is busy/modal (a dialog, interaction with the window, a long redraw).

Three layers, all limited to the two transient HRESULTs (call rejected / retry later):
1. Retry budget floor for every ``com_call_with_retry`` user (helpers, DIAGFAST,
   zone writes, path export): at least ``cb_max_wait_seconds`` (default 900 s) of
   waiting with back-off up to 2 s, instead of ~1.5 s.
2. A COM message filter (IMessageFilter.RetryRejectedCall) so that also calls that
   are NOT wrapped (attribute traversal such as ``visum.Net.Zones``) are retried
   by COM itself for the same time.  Fail-open: if pywin32 cannot register it,
   layers 1 and 3 still apply.
3. Stage retry: a rollback that fails transiently is repeated (it is idempotent:
   parent parameters + full recompute + verification); a Generation or TD block
   that fails transiently is repeated from the identical accepted parent after a
   wait (the live snapshot must equal the parent, otherwise the error propagates).
"""
from __future__ import annotations

import functools
import time
from typing import Any, Dict

RELEASE = "R1_15A2_V24917_COMBUSY2_20261025"
_STATE: Dict[str, Any] = {"installed": False, "message_filter": None, "budget_floor": None,
                          "rollback_retries": 0, "block_retries": 0, "events": []}


def options() -> Dict[str, Any]:
    try:
        import r1_15a2_demand_policy_v1 as dp
        o = dp.load_options()
    except Exception:
        o = {}
    return {"max_wait": float(o.get("cb_max_wait_seconds", 900.0)),
            "block_retries": int(o.get("cb_block_retries", 3))}


def _event(kind, **kw):
    _STATE["events"].append(dict(kind=kind, t=time.time(), **kw))
    del _STATE["events"][:-100]


def _pump_sleep(seconds: float) -> None:
    end = time.monotonic() + max(0.0, seconds)
    while True:
        try:
            import pythoncom  # type: ignore
            pythoncom.PumpWaitingMessages()
        except Exception:
            pass
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.5, left))


# ---------------------------------------------------------------- layer 1
def install_budget_floor(com, max_wait: float) -> None:
    if getattr(com._retry_budget, "__r1_combusy2__", False):
        return
    orig = com._retry_budget

    @functools.wraps(orig)
    def _retry_budget(policy):
        attempts, initial, factor, maximum, elapsed = orig(policy)
        if not (dict(policy or {}).get("enabled") is True):
            return attempts, initial, factor, maximum, elapsed
        maximum = max(maximum, 2.0)
        initial = max(initial, 0.05)
        factor = max(factor, 1.5)
        attempts = max(attempts, int(max_wait / 1.0) + 50)
        elapsed = max_wait if elapsed is None else max(elapsed, max_wait)
        return attempts, initial, factor, maximum, elapsed
    _retry_budget.__r1_combusy2__ = True
    com._retry_budget = _retry_budget
    _STATE["budget_floor"] = {"max_elapsed_seconds": max_wait, "max_delay_seconds": 2.0}


# ---------------------------------------------------------------- layer 2
def install_message_filter(max_wait: float) -> Dict[str, Any]:
    try:
        import pythoncom  # type: ignore
        from win32com.server.util import wrap  # type: ignore
    except Exception as exc:
        return {"registered": False, "reason": "PYWIN32_UNAVAILABLE:%s" % type(exc).__name__}
    limit_ms = int(max_wait * 1000)
    if not hasattr(pythoncom, "IID_IMessageFilter") or not hasattr(pythoncom, "CoRegisterMessageFilter"):
        # Visum's pywin32 build has no IMessageFilter gateway: layers 1 and 3 still apply.
        return {"registered": False, "reason": "PYWIN32_WITHOUT_IMESSAGEFILTER"}
    try:
        return _register(pythoncom, wrap, limit_ms, max_wait)
    except Exception as exc:
        return {"registered": False, "reason": "%s:%s" % (type(exc).__name__, exc)}


def _register(pythoncom, wrap, limit_ms, max_wait):
    class _RetryFilter:
        _com_interfaces_ = [pythoncom.IID_IMessageFilter]
        _public_methods_ = ["HandleInComingCall", "RetryRejectedCall", "MessagePending"]

        def HandleInComingCall(self, dwCallType, htaskCaller, dwTickCount, lpInterfaceInfo):
            return 0                       # SERVERCALL_ISHANDLED

        def RetryRejectedCall(self, htaskCallee, dwTickCount, dwRejectType):
            if dwRejectType in (1, 2) and dwTickCount < limit_ms:   # REJECTED / RETRYLATER
                return 250 if dwTickCount < 10000 else 1000
            return -1                      # give up -> caller sees the HRESULT

        def MessagePending(self, htaskCallee, dwTickCount, dwPendingType):
            return 2                       # PENDINGMSG_WAITDEFPROCESS
    try:
        previous = pythoncom.CoRegisterMessageFilter(wrap(_RetryFilter()))
        _STATE["previous_filter"] = previous
        return {"registered": True, "limit_seconds": max_wait}
    except Exception as exc:
        return {"registered": False, "reason": "%s:%s" % (type(exc).__name__, exc)}


# ---------------------------------------------------------------- layer 3
def _wrap_rollback(orig, com, max_wait):
    @functools.wraps(orig)
    def _rollback_candidate(*args, **kwargs):
        started = time.monotonic()
        delay = 5.0
        while True:
            try:
                return orig(*args, **kwargs)
            except Exception as exc:
                if not com.is_retryable_com_error(exc) or time.monotonic() - started > max_wait:
                    raise
                _STATE["rollback_retries"] += 1
                _event("ROLLBACK_RETRY", error=str(exc)[:300], wait=delay)
                print("R1 V24917 COMBUSY2: Visum rejected a call during rollback; retry in %.0f s" % delay)
                _pump_sleep(delay)
                delay = min(60.0, delay * 2.0)
    _rollback_candidate.__r1_combusy2__ = True
    return _rollback_candidate


def _parent_unchanged(adapter, state) -> bool:
    for _ in range(20):
        try:
            return adapter.snapshot() == state
        except Exception as exc:
            import r1_15a2_com_compat as com
            if not com.is_retryable_com_error(exc):
                return False
            _pump_sleep(15.0)
    return False


def _wrap_block(orig, com, label, state_pos, retries):
    @functools.wraps(orig)
    def block(adapter, cfg, folder, *args, **kwargs):
        attempt = 0
        while True:
            try:
                return orig(adapter, cfg, folder, *args, **kwargs)
            except Exception as exc:
                state = args[state_pos] if len(args) > state_pos else kwargs.get("state")
                if (attempt >= retries or not com.is_retryable_com_error(exc) or state is None
                        or not _parent_unchanged(adapter, state)):
                    raise
                attempt += 1
                wait = 30.0 * attempt
                _STATE["block_retries"] += 1
                _event("BLOCK_RETRY", block=label, attempt=attempt, error=str(exc)[:300])
                print("R1 V24917 COMBUSY2: %s failed on a rejected Visum call, parent state intact; "
                      "repeating the block in %.0f s (attempt %d/%d)" % (label, wait, attempt, retries))
                _pump_sleep(wait)
                folder = type(folder)(str(folder) + "_RETRY%d" % attempt) if folder is not None else folder
    block.__r1_combusy2__ = True
    return block


def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return status()
    import r1_15a2_com_compat as com
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    o = options()
    install_budget_floor(com, o["max_wait"])
    try:
        _STATE["message_filter"] = install_message_filter(o["max_wait"])
    except Exception as exc:          # never block the run on the optional COM filter
        _STATE["message_filter"] = {"registered": False, "reason": "%s:%s" % (type(exc).__name__, exc)}
    if not getattr(base._rollback_candidate, "__r1_combusy2__", False):
        base._rollback_candidate = _wrap_rollback(base._rollback_candidate, com, o["max_wait"])
    # _generation_update_once_impl(adapter, cfg, folder, control, state, ...): state = args[1]
    if not getattr(ctrl._generation_update_once_impl, "__r1_combusy2__", False):
        ctrl._generation_update_once_impl = _wrap_block(
            ctrl._generation_update_once_impl, com, "GENERATION", 1, o["block_retries"])
    # _finecdf_td_once(adapter, cfg, folder, control, state, diag, package_root, ...): state = args[1]
    if not getattr(ctrl._finecdf_td_once, "__r1_combusy2__", False):
        ctrl._finecdf_td_once = _wrap_block(ctrl._finecdf_td_once, com, "TD", 1, o["block_retries"])
    _STATE["installed"] = True
    print_fn("V24917 COMBUSY2: rejected Visum calls retried up to %.0f s (message filter: %s), "
             "rollback and blocks repeated from the intact parent"
             % (o["max_wait"], "ON" if _STATE["message_filter"].get("registered") else
                "OFF " + str(_STATE["message_filter"].get("reason"))))
    return status()


def status() -> Dict[str, Any]:
    return {"release": RELEASE, "installed": _STATE["installed"],
            "message_filter": _STATE["message_filter"], "budget_floor": _STATE["budget_floor"],
            "rollback_retries": _STATE["rollback_retries"], "block_retries": _STATE["block_retries"],
            "events": list(_STATE["events"][-20:])}


__all__ = ["RELEASE", "install", "status", "install_budget_floor", "install_message_filter"]
