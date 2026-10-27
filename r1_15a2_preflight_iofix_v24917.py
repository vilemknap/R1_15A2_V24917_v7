# -*- coding: utf-8 -*-
"""V24917 PREFLIGHTIOFIX1: Windows file-lock tolerant COM API preflight evidence.

Live failure 2026-10-26 (RUN_20261026_023849_254377): every check of
r1_15a2_live_api_audit.collect_live_api() republishes COM_API_PREFLIGHT.json by
os.replace(tmp, json).  A transient Windows lock on the JSON (antivirus /
indexer / OneDrive / an open viewer) raised WinError 5 inside check(); the
ALREADY PASSED check ZONE_ATTRIBUTE:FP_2_SERVICE_stud was then appended a
second time as FAIL and became a "required failure" -> LIVE_API_PREFLIGHT_FAILED.
The model attribute itself was read correctly (681 zones, numeric, sum 58168).

Fix (no change of any check, any model read or any acceptance rule): the
module's ``os`` is replaced by a proxy whose ``replace`` retries transient lock
errors (IOFIX3 replace_with_retry, longer budget), then falls back to a direct
rewrite of the target, and if the evidence file still cannot be published it
keeps the .tmp copy and records the event instead of raising.  An evidence
write therefore can no longer turn a passed model check into a blocker.
The live_api_audit source file itself is unchanged (hash-pinned by V24916).
"""
from __future__ import annotations

import os as _os
import time

RELEASE = "R1_15A2_V24917_PREFLIGHTIOFIX1_20261026"
EVENTS = []
_STATE = {"active": False}
ATTEMPTS = 80          # ~35 s total with 0.025 s .. 0.5 s backoff


class _PreflightOSProxy:
    def __getattr__(self, name):
        return getattr(_os, name)

    @staticmethod
    def replace(src, dst):
        import r1_15a2_runtime_io_hotfix_profile488 as io
        try:
            return io.replace_with_retry(src, dst, attempts=ATTEMPTS)
        except OSError as exc:
            if not io._transient(exc):
                raise
            first = exc
        # Fallback 1: rewrite the destination in place (non-atomic, same content).
        for _ in range(20):
            try:
                with open(src, "rb") as f:
                    data = f.read()
                with open(dst, "wb") as f:
                    f.write(data)
                try:
                    _os.remove(src)
                except OSError:
                    pass
                EVENTS.append({"event": "PREFLIGHT_EVIDENCE_DIRECT_REWRITE", "target": str(dst),
                               "replace_error": repr(first)})
                return None
            except OSError:
                time.sleep(0.5)
        # Fallback 2: keep the complete .tmp evidence, never fail the model check.
        EVENTS.append({"event": "PREFLIGHT_EVIDENCE_PUBLISH_DEFERRED_TMP_KEPT", "target": str(dst),
                       "tmp": str(src), "replace_error": repr(first)})
        return None


def activate():
    import r1_15a2_live_api_audit as api_audit
    if not isinstance(api_audit.os, _PreflightOSProxy):
        api_audit.os = _PreflightOSProxy()
    _STATE["active"] = True
    return status()


def status():
    return {"release": RELEASE, "active": _STATE["active"], "replace_attempts": ATTEMPTS,
            "scope": "r1_15a2_live_api_audit.collect_live_api evidence publication only",
            "checks_changed": False, "model_reads_changed": False, "acceptance_changed": False,
            "events": list(EVENTS)}
