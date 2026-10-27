# -*- coding: utf-8 -*-
"""PERF3 (V24917): low-risk orchestration savings + per-stage timing.

* Deferred helper-evidence ZIP: inside ``deferred_archives()`` (STEP1 trial
  diagnostics) the 12D/11D helper workspace is renamed next to itself instead of
  being zipped.  After the decision: accepted -> zipped to the original path;
  rejected -> deleted, a small SKIPPED marker is written instead.  An error inside
  the block keeps (zips) the evidence.
* Checkpoints: SHA-256 of a file is memoised by (path, size, mtime_ns); the
  best-so-far copy of an accepted checkpoint is a hard link when the volume allows
  it (identical bytes, no 0.6 GB copy, no second hash), copy fallback otherwise.
* M9002 (IZPEN1) snapshot read cached between penalty/base writes (the cache is
  re-verified against Visum every ``VERIFY_EVERY`` snapshots).
* Timing: inclusive wall time per calibrator stage (procedure sequence, 12D, 11D,
  snapshot, design, TD stage, rollback, save, checkpoint, path export, archives),
  written per block to ``V24917_TIMING.json`` and summarised on the console.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

RELEASE = "R1_15A2_V24917_PERF3_20261025"
VERIFY_EVERY = 25
_LOCAL = threading.local()
_STATE: Dict[str, Any] = {"installed": False, "timing": {}, "sha_cache": {}, "sha_hits": 0,
                          "deferred_kept": 0, "deferred_skipped": 0, "hardlinks": 0, "copies": 0,
                          "iz_cache_hits": 0, "iz_cache_verifies": 0}


# ------------------------------------------------------------------ timing
def _add(name: str, seconds: float) -> None:
    t = _STATE["timing"].setdefault(name, {"calls": 0, "seconds": 0.0, "max": 0.0})
    t["calls"] += 1
    t["seconds"] += seconds
    t["max"] = max(t["max"], seconds)


def timed(name: str, fn):
    if getattr(fn, "__r1_perf3_timed__", None) == name:
        return fn

    @functools.wraps(fn)
    def run(*args, **kwargs):
        start = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            _add(name, time.perf_counter() - start)
    run.__r1_perf3_timed__ = name
    return run


def timing_snapshot() -> Dict[str, Dict[str, float]]:
    return json.loads(json.dumps(_STATE["timing"]))


def timing_delta(before: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    out = {}
    for k, v in _STATE["timing"].items():
        b = before.get(k, {"calls": 0, "seconds": 0.0})
        calls = v["calls"] - b.get("calls", 0)
        if calls:
            out[k] = {"calls": calls, "seconds": round(v["seconds"] - b.get("seconds", 0.0), 3)}
    return out


def write_timing(folder, label: str, before, print_fn=print) -> Dict[str, Any]:
    delta = timing_delta(before)
    rec = {"schema": "R1_15A2_V24917_TIMING_V1", "label": label,
           "note": "inclusive wall seconds; nested stages (e.g. assignment inside rollback) overlap",
           "block": delta, "cumulative": timing_snapshot(),
           "savings": {k: _STATE[k] for k in ("sha_hits", "deferred_kept", "deferred_skipped", "hardlinks",
                                              "copies", "iz_cache_hits", "iz_cache_verifies")}}
    try:
        p = Path(folder) / "V24917_TIMING.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    except Exception as exc:
        rec["write_error"] = repr(exc)
    top = sorted(delta.items(), key=lambda kv: -kv[1]["seconds"])[:7]
    try:
        print_fn("R1 V24917 TIMING %s: %s" % (label, ", ".join(
            "%s %.0fs/%d" % (k, v["seconds"], v["calls"]) for k, v in top)))
    except Exception:
        pass
    return rec


# ---------------------------------------------------------- deferred zips
class _Deferred:
    def __init__(self):
        self.keep = True            # default: keep evidence (errors keep forensic ZIPs)
        self.pending: List[tuple] = []


@contextlib.contextmanager
def deferred_archives():
    prev = getattr(_LOCAL, "deferred", None)
    d = _Deferred()
    _LOCAL.deferred = d
    failed = False
    try:
        yield d
    except BaseException:
        failed = True
        raise
    finally:
        _LOCAL.deferred = prev
        _finalize(d, keep=d.keep or failed)


def _finalize(d: _Deferred, keep: bool) -> None:
    """Delete evidence only after a complete, CRC-verified archive is published.

    Never mask the primary COM/stop exception with an archive failure.  Retained
    source paths are recorded in memory and, when possible, in a sidecar.
    """
    import zipfile
    for hold, zip_path, archive_fn in d.pending:
        hold, zip_path = Path(hold), Path(zip_path)
        temporary = zip_path.with_name(zip_path.stem + ".partial-" + uuid.uuid4().hex[:8] + ".zip")
        delete_source = False
        try:
            if keep:
                expected = {p.relative_to(hold).as_posix(): p.stat().st_size
                            for p in hold.rglob("*") if p.is_file()}
                archive_fn(hold, temporary)
                with zipfile.ZipFile(temporary) as archive:
                    infos = [i for i in archive.infolist() if not i.is_dir()]
                    actual = {i.filename.replace("\\", "/"): i.file_size for i in infos}
                    if len(actual) != len(infos) or actual != expected or archive.testzip() is not None:
                        raise RuntimeError("GENFIX2_EVIDENCE_ARCHIVE_INCOMPLETE_OR_CORRUPT")
                zip_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temporary, zip_path)
                _STATE["deferred_kept"] += 1
                delete_source = True
            else:
                zip_path.parent.mkdir(parents=True, exist_ok=True)
                (zip_path.parent / (zip_path.stem + "_ZIP_SKIPPED_REJECTED_TRIAL.json")).write_text(
                    json.dumps({"release": RELEASE, "reason": "REJECTED_TRIAL_EVIDENCE_NOT_ARCHIVED",
                                "compact_mirror_kept": True}), encoding="utf-8")
                _STATE["deferred_skipped"] += 1
                delete_source = True
        except Exception as exc:
            record = {"source_retained": str(hold), "requested_archive": str(zip_path),
                      "temporary_archive": str(temporary), "error": repr(exc), "status": "RETAINED_NOT_ARCHIVED"}
            _STATE.setdefault("archive_failures", []).append(record)
            try:
                zip_path.with_suffix(".ARCHIVE_FAILED.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            except Exception:
                pass
            print("R1 GENFIX2: archive failed; evidence retained at %s: %r" % (hold, exc))
        finally:
            if delete_source:
                shutil.rmtree(str(hold), ignore_errors=True)


def _wrap_archive(orig):
    @functools.wraps(orig)
    def _archive_helper_workspace(workspace, zip_path):
        d = getattr(_LOCAL, "deferred", None)
        ws = Path(workspace)
        if d is None or not ws.exists() or str(zip_path).endswith("_FAILED.zip"):
            return orig(workspace, zip_path)
        hold = ws.parent / (ws.name + "_HOLD_" + uuid.uuid4().hex[:6])
        try:
            os.replace(str(ws), str(hold))
        except OSError:
            return orig(workspace, zip_path)
        d.pending.append((hold, Path(zip_path), orig))
        return Path(zip_path)
    _archive_helper_workspace.__r1_perf3__ = True
    return _archive_helper_workspace


# ---------------------------------------------------------- checkpoints
def sha256_cached(path, orig=None) -> str:
    p = Path(path).resolve()
    st = p.stat()
    # inode identity: a hard link of a hashed checkpoint is a cache hit (same bytes by construction)
    key = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) if st.st_ino else (str(p), st.st_size, st.st_mtime_ns)
    hit = _STATE["sha_cache"].get(key)
    if hit:
        _STATE["sha_hits"] += 1
        return hit
    if orig is not None:
        value = orig(p)
    else:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                h.update(chunk)
        value = h.hexdigest()
    cache = _STATE["sha_cache"]
    cache[key] = value
    while len(cache) > 32:
        cache.pop(next(iter(cache)))
    return value


def _link_or_copy(source, target):
    """Hard link (same bytes, no copy); copy2 fallback (other volume, FS without links)."""
    try:
        os.link(str(source), str(target))
        _STATE["hardlinks"] += 1
        return "HARDLINK"
    except OSError:
        shutil.copy2(str(source), str(target))
        _STATE["copies"] += 1
        return "COPY"


class _ShutilProxy:
    """shutil seen by _publish_best_so_far_checkpoint: copy2 -> hard link when possible."""

    def __getattr__(self, name):
        return getattr(shutil, name)

    @staticmethod
    def copy2(src, dst, *args, **kwargs):
        _link_or_copy(src, dst)
        return dst


# ---------------------------------------------------------- 9002 cache
def _install_iz_cache(izpen):
    if getattr(izpen.extend_snapshot, "__r1_perf3__", False):
        return
    orig_extend, orig_write, orig_set_base = izpen.extend_snapshot, izpen.write_penalty, izpen.set_base
    cache: Dict[str, Any] = {"pen": None, "base_sha": None, "count": 0}

    def invalidate():
        cache["pen"] = None
        cache["base_sha"] = None

    @functools.wraps(orig_extend)
    def extend_snapshot(snapshot, visum):
        if not izpen.active() or not isinstance(snapshot, dict):
            return orig_extend(snapshot, visum)
        cache["count"] += 1
        if cache["pen"] is None or cache["count"] % VERIFY_EVERY == 0:
            out = orig_extend(snapshot, visum)            # full read + structural checks
            if cache["pen"] is not None and out.get(izpen.SNAPSHOT_KEY) != cache["pen"]:
                invalidate()
                _STATE["iz_cache_verifies"] += 1
                return out
            cache["pen"] = out.get(izpen.SNAPSHOT_KEY)
            cache["base_sha"] = out.get(izpen.BASE_KEY)
            _STATE["iz_cache_verifies"] += 1
            return out
        _STATE["iz_cache_hits"] += 1
        out = dict(snapshot)
        out[izpen.SNAPSHOT_KEY] = dict(cache["pen"])
        out[izpen.BASE_KEY] = cache["base_sha"]
        return out
    extend_snapshot.__r1_perf3__ = True

    @functools.wraps(orig_write)
    def write_penalty(*args, **kwargs):
        invalidate()
        try:
            return orig_write(*args, **kwargs)
        finally:
            invalidate()

    @functools.wraps(orig_set_base)
    def set_base(*args, **kwargs):
        invalidate()
        try:
            return orig_set_base(*args, **kwargs)
        finally:
            invalidate()
    izpen.extend_snapshot = extend_snapshot
    izpen.write_penalty = write_penalty
    izpen.set_base = set_base
    izpen._perf3_invalidate = invalidate


# ---------------------------------------------------------- install
def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return status()
    import r1_15a2_runtime_v1 as rt
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_intrazonal_penalty_v24917 as izpen
    import r1_15a2_trial_adapter_v24917 as ad
    # deferred archives (outermost wrapper, keeps DIAGFAST archive telemetry inside)
    if not getattr(rt._archive_helper_workspace, "__r1_perf3__", False):
        rt._archive_helper_workspace = timed("evidence_zip", _wrap_archive(rt._archive_helper_workspace))
        rt._archive_helper_workspace.__r1_perf3__ = True
    # checkpoints
    orig_sha_rt = rt.sha256_file
    if not getattr(orig_sha_rt, "__r1_perf3__", False):
        def rt_sha(path, _o=orig_sha_rt):
            return sha256_cached(path, _o)
        rt_sha.__r1_perf3__ = True
        rt.sha256_file = rt_sha
    if not getattr(ctrl._sha256_file, "__r1_perf3__", False):
        def ctrl_sha(path):
            return sha256_cached(path)
        ctrl_sha.__r1_perf3__ = True
        ctrl._sha256_file = ctrl_sha
    if not isinstance(getattr(ctrl, "shutil", None), _ShutilProxy):
        ctrl.shutil = _ShutilProxy()
    # M9002 snapshot cache (LoadVersion replaces every matrix -> invalidate)
    _install_iz_cache(izpen)
    if not getattr(rt.load_version, "__r1_perf3__", False):
        orig_load = rt.load_version

        @functools.wraps(orig_load)
        def load_version(*args, **kwargs):
            try:
                return orig_load(*args, **kwargs)
            finally:
                getattr(izpen, "_perf3_invalidate", lambda: None)()
        load_version.__r1_perf3__ = True
        rt.load_version = load_version
    # timing
    for mod, name, label in ((rt, "execute_procseq", "procedure_sequence"),
                             (rt, "run_12d", "diag_12d"), (rt, "run_11d", "diag_11d"),
                             (rt, "save_version", "save_version"),
                             (rt, "export_actual_paths_and_build_incidence", "path_export"),
                             (base, "_rollback_candidate", "rollback"),
                             (ctrl, "_save_rotating_checkpoint", "checkpoint_accepted"),
                             (ctrl, "_publish_best_so_far_checkpoint", "checkpoint_best_so_far"),
                             (ctrl, "_finecdf_td_once", "td_stage")):
        if hasattr(mod, name):
            setattr(mod, name, timed(label, getattr(mod, name)))
    for meth, label in (("snapshot", "snapshot"), ("generation_design", "generation_design"),
                        ("diagnostics", "diagnostics_total")):
        fn = getattr(ad.VisumAdapter, meth)
        if getattr(fn, "__r1_perf3_timed__", None) != label:
            setattr(ad.VisumAdapter, meth, timed(label, fn))
    # per-block timing file for TD (Generation writes it in STEP1 / below)
    orig_gen = ctrl._generation_update_once_impl
    if not getattr(orig_gen, "__r1_perf3_block__", False):
        @functools.wraps(orig_gen)
        def _generation_update_once_impl(adapter, cfg, folder, *args, **kwargs):
            before = timing_snapshot()
            try:
                return orig_gen(adapter, cfg, folder, *args, **kwargs)
            finally:
                write_timing(folder, "GENERATION", before, print_fn)
        _generation_update_once_impl.__r1_perf3_block__ = True
        ctrl._generation_update_once_impl = timed("generation_block", _generation_update_once_impl)
        ctrl._generation_update_once_impl.__r1_perf3_block__ = True
    orig_td = ctrl._finecdf_td_once
    if not getattr(orig_td, "__r1_perf3_block__", False):
        @functools.wraps(orig_td)
        def _finecdf_td_once(adapter, cfg, folder, *args, **kwargs):
            before = timing_snapshot()
            try:
                return orig_td(adapter, cfg, folder, *args, **kwargs)
            finally:
                write_timing(folder, "TD", before, print_fn)
        _finecdf_td_once.__r1_perf3_block__ = True
        ctrl._finecdf_td_once = _finecdf_td_once
    _STATE["installed"] = True
    print_fn("V24917 PERF3: deferred trial ZIPs, checkpoint hash cache + hard-link best-so-far, "
             "M9002 snapshot cache, stage timing -> V24917_TIMING.json")
    return status()


def status() -> Dict[str, Any]:
    return {"release": RELEASE, "installed": _STATE["installed"],
            **{k: _STATE[k] for k in ("sha_hits", "deferred_kept", "deferred_skipped", "hardlinks", "copies",
                                      "iz_cache_hits", "iz_cache_verifies")}}


__all__ = ["RELEASE", "install", "status", "deferred_archives", "timed", "write_timing",
           "timing_snapshot", "sha256_cached"]
