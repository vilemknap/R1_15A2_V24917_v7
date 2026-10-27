# -*- coding: utf-8 -*-
"""V2.4.9.4 regressions for the live V2493 path-export failure and restart semantics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import r1_15a2_com_compat as com
import r1_15a2_overnight_controller_v240 as overnight
import r1_15a2_restart_v2494 as restart
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError
from r1_15a2_two_mode_v238 import (
    DEFAULT_SETTINGS, GEOMETRY_COLUMNS, bounded_rows,
)

HEADERS = [
    "OrigZoneNo", "DestZoneNo", "PathIndex", "Index",
    "LinkNo", "FromNodeNo", "ToNodeNo",
]


class RetryableCallRejected(Exception):
    def __init__(self, message="Volany odmitl volani."):
        super().__init__(com.RPC_E_CALL_REJECTED, message)
        self.hresult = com.RPC_E_CALL_REJECTED


class _TypeInfo:
    def GetTypeAttr(self):
        return SimpleNamespace(cFuncs=1)

    def GetFuncDesc(self, index):
        assert index == 0
        return SimpleNamespace(memid=17, invkind=1)

    def GetNames(self, memid):
        assert memid == 17
        return ("SaveToArray", "FirstObject", "LastObject")


class _OLE:
    def __init__(self, rows, *, transient_failures=0, oversize_above=None):
        self.rows = list(rows)
        self.transient_failures = int(transient_failures)
        self.oversize_above = oversize_above
        self.calls = []
        self._typeinfo = _TypeInfo()

    def GetTypeInfo(self):
        return self._typeinfo

    def Invoke(self, memid, lcid, kind, as_method, first, last):
        assert (memid, lcid, kind, as_method) == (17, 0, 1, True)
        self.calls.append((int(first), int(last)))
        if self.transient_failures > 0:
            self.transient_failures -= 1
            raise RetryableCallRejected()
        if self.oversize_above is not None and last - first + 1 > self.oversize_above:
            raise RuntimeError("SIMULATED_COM_PAGE_TOO_LARGE")
        return self.rows[first - 1:last]


class _BoundedList:
    def __init__(self, rows, **kwargs):
        self._oleobj_ = _OLE(rows, **kwargs)

    @property
    def SaveToArray(self):
        raise AssertionError("unbounded SaveToArray is forbidden")


class _Control:
    def __init__(self):
        self.events = []

    def checkpoint(self, phase=None, force=False, **kwargs):
        self.events.append(dict(phase=phase, force=force, **kwargs))


def _row(i):
    return [1, 2, 1, i, 100 + i, 200 + i, 300 + i]


def _retry_policy(attempts=5):
    return {
        "enabled": True,
        "max_attempts": attempts,
        "initial_delay_seconds": 0.0,
        "backoff_factor": 2.0,
        "max_delay_seconds": 0.0,
    }


def test_runtime_path_export_retries_exact_same_page_then_continues():
    obj = _BoundedList([_row(i) for i in range(1, 6)], transient_failures=2)
    retry_events = []
    got = list(rt.iter_prt_pathlink_bounded(
        obj, HEADERS, page_size=3, require_verified=True,
        retry_policy=_retry_policy(3), retry_progress=retry_events.append,
    ))
    assert got == [_row(i) for i in range(1, 6)]
    assert obj._oleobj_.calls == [(1, 3), (1, 3), (1, 3), (4, 6)]
    assert [(x["first"], x["last"]) for x in retry_events] == [(1, 3), (1, 3)]
    assert all(x["page_size"] == 3 for x in retry_events)


def test_transient_retry_exhaustion_never_becomes_page_size_fallback():
    obj = _BoundedList([_row(1)], transient_failures=10)
    with pytest.raises(RetryableCallRejected):
        list(rt.iter_prt_pathlink_bounded(
            obj, HEADERS, page_size=256, require_verified=True,
            retry_policy=_retry_policy(2),
        ))
    assert obj._oleobj_.calls == [(1, 256), (1, 256)]
    assert not any(last - first + 1 == 80 for first, last in obj._oleobj_.calls)


def test_nontransient_page_size_error_can_use_proven_bounded_80():
    rows = [_row(i) for i in range(1, 176)]
    obj = _BoundedList(rows, oversize_above=80)
    got = list(rt.iter_prt_pathlink_bounded(
        obj, HEADERS, page_size=256, require_verified=True,
        retry_policy=_retry_policy(3),
    ))
    assert got == rows
    assert obj._oleobj_.calls == [(1, 256), (1, 80), (81, 160), (161, 240)]


def test_two_mode_export_uses_same_range_retry_and_audits_it():
    rows = [_row(i) for i in range(1, 4)]
    obj = _BoundedList(rows, transient_failures=1)
    control = _Control()
    settings = dict(DEFAULT_SETTINGS)
    settings.update(
        page_size=2,
        page_size_fallbacks=[80],
        com_retry_policy=_retry_policy(2),
        max_geometry_rows_per_mode=100,
    )
    got = list(bounded_rows(
        obj, GEOMETRY_COLUMNS, settings, control,
        "REPRESENTATIVE_GEOMETRY", mode="C", dseg_code="NATIVE_CW",
    ))
    assert got == rows
    assert obj._oleobj_.calls == [(1, 2), (1, 2), (3, 4)]
    retry = [x for x in control.events if "com_retry_event" in x]
    assert len(retry) == 1
    assert (retry[0]["bounded_range_first"], retry[0]["bounded_range_last"]) == (1, 2)


def _snapshot(seed="a"):
    return {
        name: hashlib.sha256((seed + ":" + name).encode("ascii")).hexdigest()
        for name in restart.SEMANTIC_FIELDS
    } | {"state_hash": hashlib.sha256((seed + ":state").encode("ascii")).hexdigest()}


def test_raw_ver_sha_difference_is_ignored_when_semantics_match():
    snap = _snapshot()
    first = restart.build_authority(snap, version_path="A.ver", raw_ver_sha256="1" * 64)
    second = restart.build_authority(snap, version_path="B.ver", raw_ver_sha256="2" * 64)
    result = restart.require_authority_match(first, second)
    assert result["passes"] is True
    assert result["raw_ver_sha_compared"] is False
    assert first["raw_ver_sha_used_for_restart_acceptance"] is False


def test_semantic_field_difference_fails_restart_even_with_same_raw_sha():
    a = _snapshot("a")
    b = dict(a)
    b["matrix_hash"] = hashlib.sha256(b"different").hexdigest()
    first = restart.build_authority(a, raw_ver_sha256="3" * 64)
    second = restart.build_authority(b, raw_ver_sha256="3" * 64)
    with pytest.raises(SupplyContractError, match="matrix_hash"):
        restart.require_authority_match(first, second)


def test_optional_sidecar_accepts_manual_resave_with_different_raw_sha(tmp_path):
    ver = tmp_path / "ACCEPTED_B_0000.ver"
    ver.write_bytes(b"reserialized bytes")
    expected = restart.build_authority(
        _snapshot(), version_path=ver, raw_ver_sha256="4" * 64)
    restart.sidecar_path(ver).write_text(json.dumps(expected), encoding="utf-8")
    loaded = restart.load_optional_sidecar(ver)
    actual = restart.build_authority(
        _snapshot(), version_path=ver,
        raw_ver_sha256=hashlib.sha256(ver.read_bytes()).hexdigest())
    assert restart.require_authority_match(loaded, actual)["passes"] is True


def test_sidecar_self_inconsistency_fails_closed(tmp_path):
    ver = tmp_path / "A.ver"
    ver.write_bytes(b"x")
    value = restart.build_authority(_snapshot(), raw_ver_sha256="5" * 64)
    value["semantic_state_hash"] = "6" * 64
    restart.sidecar_path(ver).write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(SupplyContractError, match="SELF_INCONSISTENT"):
        restart.load_optional_sidecar(ver)


def test_checkpoint_publishes_semantic_sidecar_when_v2494_contract_enabled(tmp_path):
    snap = _snapshot()

    class Adapter:
        cfg = {"restart_authority": {"checkpoint_semantic_sidecar": True}}

        def save(self, path):
            path = Path(path)
            path.write_bytes(b"checkpoint")
            return {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }

        def snapshot(self):
            return dict(snap)

    cp = overnight._save_rotating_checkpoint(Adapter(), tmp_path / "run", 0)
    latest = json.loads((tmp_path / "run/LATEST_ACCEPTED_CHECKPOINT.json").read_text())
    sidecar = restart.sidecar_path(Path(cp["path"]))
    assert sidecar.is_file()
    assert latest["semantic_restart_authority"]["path"] == str(sidecar)
    assert latest["semantic_restart_authority"]["raw_ver_sha_used_for_restart_acceptance"] is False
    assert restart.load_optional_sidecar(Path(cp["path"]))["semantic_hashes"] == restart.semantic_hashes(snap)
