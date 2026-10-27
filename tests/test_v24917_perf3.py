# -*- coding: utf-8 -*-
"""PERF3: deferred trial ZIPs, checkpoint hash cache + hard link, M9002 cache, timing."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r1_15a2_perf_v24917 as perf  # noqa: E402


def _workspace(tmp_path, name="scratch"):
    ws = tmp_path / name
    (ws / "sub").mkdir(parents=True)
    (ws / "09_SUMMARY.json").write_text("{}", encoding="utf-8")
    (ws / "sub" / "detail.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    return ws


def _zip(ws, zp):
    import zipfile
    with zipfile.ZipFile(zp, "w") as z:
        for p in Path(ws).rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(ws))
    return zp


def test_archive_outside_deferral_is_immediate(tmp_path):
    ws = _workspace(tmp_path)
    wrapped = perf._wrap_archive(_zip)
    wrapped(ws, tmp_path / "E.zip")
    assert (tmp_path / "E.zip").is_file()


@pytest.mark.parametrize("keep", [True, False])
def test_deferred_archive_kept_or_skipped(tmp_path, keep):
    wrapped = perf._wrap_archive(_zip)
    ws = _workspace(tmp_path)
    zp = tmp_path / "mirror" / "D12.zip"
    zp.parent.mkdir()
    with perf.deferred_archives() as d:
        wrapped(ws, zp)
        assert not ws.exists() and not zp.exists()          # moved aside, not zipped yet
        d.keep = keep
    assert zp.is_file() is keep
    assert (zp.parent / "D12_ZIP_SKIPPED_REJECTED_TRIAL.json").is_file() is (not keep)
    assert not any(p.name.startswith("scratch_HOLD_") for p in tmp_path.iterdir())


def test_deferred_archive_error_keeps_forensic_zip(tmp_path):
    wrapped = perf._wrap_archive(_zip)
    ws = _workspace(tmp_path)
    zp = tmp_path / "D11.zip"
    with pytest.raises(RuntimeError):
        with perf.deferred_archives() as d:
            wrapped(ws, zp)
            d.keep = False
            raise RuntimeError("gate crashed")
    assert zp.is_file()


def test_failed_zip_never_deferred(tmp_path):
    wrapped = perf._wrap_archive(_zip)
    ws = _workspace(tmp_path)
    with perf.deferred_archives():
        wrapped(ws, tmp_path / "X_FAILED.zip")
        assert (tmp_path / "X_FAILED.zip").is_file()


def test_sha_cache_and_hardlink_hit(tmp_path, monkeypatch):
    monkeypatch.setitem(perf._STATE, "sha_cache", {})
    f = tmp_path / "A.ver"
    f.write_bytes(os.urandom(4096))
    h1 = perf.sha256_cached(f)
    hits = perf._STATE["sha_hits"]
    assert perf.sha256_cached(f) == h1 and perf._STATE["sha_hits"] == hits + 1
    link = tmp_path / "B.ver"
    mode = perf._link_or_copy(f, link)
    assert link.read_bytes() == f.read_bytes()
    if mode == "HARDLINK":
        assert perf.sha256_cached(link) == h1 and perf._STATE["sha_hits"] == hits + 2
    f.unlink()                                   # rotation deletes the accepted slot file
    assert link.is_file()


def test_best_so_far_publish_uses_link(tmp_path, monkeypatch):
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    monkeypatch.setattr(ctrl, "shutil", perf._ShutilProxy())
    monkeypatch.setattr(ctrl, "_sha256_file", lambda p: perf.sha256_cached(p))
    src = tmp_path / "CHECKPOINTS" / "ACCEPTED_A_0001_x.ver"
    src.parent.mkdir()
    src.write_bytes(os.urandom(8192))
    sha = perf.sha256_cached(src)
    adapter = SimpleNamespace(cfg={})
    rec = ctrl._publish_best_so_far_checkpoint(adapter, tmp_path, {"path": str(src), "sha256": sha},
                                               {"state_hash": "ab" * 32}, {"total": 1.0}, 1)
    target = Path(rec["checkpoint"]["path"])
    assert target.read_bytes() == src.read_bytes() and rec["checkpoint"]["sha256"] == sha
    assert ctrl.shutil.rmtree is __import__("shutil").rmtree          # other shutil functions untouched


def test_iz_snapshot_cache(monkeypatch):
    calls = {"read": 0}

    class Iz:
        SNAPSHOT_KEY, BASE_KEY = "v24917_iz_penalty", "v24917_ic_base_sha"
        pen = {"611": 0.0}

        def active(self):
            return True

        def extend_snapshot(self, snap, visum):
            calls["read"] += 1
            out = dict(snap)
            out[self.SNAPSHOT_KEY] = dict(self.pen)
            out[self.BASE_KEY] = "B"
            return out

        def write_penalty(self, visum, pen, adapter=None):
            self.pen = {"611": float(pen[0])}

        def set_base(self, visum, B, adapter=None):
            return "B2"
    iz = Iz()
    mod = SimpleNamespace(active=iz.active, extend_snapshot=iz.extend_snapshot,
                          write_penalty=iz.write_penalty, set_base=iz.set_base,
                          SNAPSHOT_KEY=iz.SNAPSHOT_KEY, BASE_KEY=iz.BASE_KEY)
    perf._install_iz_cache(mod)
    s1 = mod.extend_snapshot({"a": 1}, None)
    s2 = mod.extend_snapshot({"a": 1}, None)
    assert s1 == s2 and calls["read"] == 1                       # cached
    mod.write_penalty(None, np.array([3.0]))
    s3 = mod.extend_snapshot({"a": 1}, None)
    assert s3["v24917_iz_penalty"] == {"611": 3.0} and calls["read"] == 2
    for _ in range(perf.VERIFY_EVERY):
        mod.extend_snapshot({"a": 1}, None)
    assert calls["read"] == 3                                    # periodic verification read


def test_timing_wrapper_and_report(tmp_path):
    before = perf.timing_snapshot()
    f = perf.timed("unit_stage", lambda x: x * 2)
    assert f(3) == 6 and perf.timed("unit_stage", f) is f
    lines = []
    rec = perf.write_timing(tmp_path, "UNIT", before, print_fn=lines.append)
    assert rec["block"]["unit_stage"]["calls"] == 1
    assert json.loads((tmp_path / "V24917_TIMING.json").read_text())["label"] == "UNIT"
    assert lines and "unit_stage" in lines[0]


def test_install_on_live_modules(monkeypatch):
    import r1_15a2_runtime_v1 as rt
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_intrazonal_penalty_v24917 as izpen
    import r1_15a2_trial_adapter_v24917 as ad
    for mod, names in ((rt, ("_archive_helper_workspace", "sha256_file", "execute_procseq", "run_12d", "run_11d",
                             "save_version", "export_actual_paths_and_build_incidence", "load_version")),
                       (base, ("_rollback_candidate",)),
                       (ctrl, ("_sha256_file", "shutil", "_save_rotating_checkpoint",
                               "_publish_best_so_far_checkpoint", "_finecdf_td_once",
                               "_generation_update_once_impl")),
                       (izpen, ("extend_snapshot", "write_penalty", "set_base"))):
        for n in names:
            monkeypatch.setattr(mod, n, getattr(mod, n))
    for meth in ("snapshot", "generation_design", "diagnostics"):
        monkeypatch.setattr(ad.VisumAdapter, meth, getattr(ad.VisumAdapter, meth))
    monkeypatch.setitem(perf._STATE, "installed", False)
    st = perf.install(print_fn=lambda *a: None)
    assert st["installed"]
    assert getattr(rt._archive_helper_workspace, "__r1_perf3__")
    assert rt.run_12d.__r1_perf3_timed__ == "diag_12d"
    assert isinstance(ctrl.shutil, perf._ShutilProxy)
    assert getattr(izpen.extend_snapshot, "__r1_perf3__")
    assert getattr(rt.load_version, "__r1_perf3__")
    assert ad.VisumAdapter.snapshot.__r1_perf3_timed__ == "snapshot"
    assert getattr(ctrl._generation_update_once_impl, "__r1_perf3_block__")
    # run_diagnostics resolves run_12d through the module global (wrapped)
    import inspect
    assert "run_12d(visum" in inspect.getsource(rt.run_diagnostics)
    json.dumps(perf.status())
    monkeypatch.setitem(perf._STATE, "installed", False)
