# -*- coding: utf-8 -*-
"""Runtime-only Windows-safe publication overlay for PROFILE488 recovery.

IOFIX3 closes two distinct Windows failure modes without changing calibration
math, acceptance, assignment, or restart semantics:

* transient sharing/access locks are retried and critical state stays fail-closed;
* deep recovery paths never construct a temporary sibling by appending a long
  suffix to the full destination filename.  Short opaque sibling names are used
  and Python file operations opt into the Win32 extended-length path namespace.

Performance telemetry remains handled by its separate fail-open overlay.
"""
from __future__ import annotations

from pathlib import Path
import builtins
import csv
import errno
import hashlib
import json
import ntpath
import os as _os
import shutil as _shutil
import sys
import threading
import time

_REAL_REPLACE = _os.replace
_OPEN = builtins.open
_TRANSIENT_WINERRORS = {5, 32, 33}
_TRANSIENT_ERRNOS = {errno.EACCES, errno.EPERM, errno.EBUSY}
_MAX_PATH_DIAGNOSTIC_LIMIT = 260
_SAFE_LOGICAL_PATH_BUDGET = 240


def _transient(exc):
    return (
        isinstance(exc, PermissionError)
        or getattr(exc, "winerror", None) in _TRANSIENT_WINERRORS
        or getattr(exc, "errno", None) in _TRANSIENT_ERRNOS
    )


def _native_path(path, os_name=None):
    """Return a path accepted by Win32 even when the logical path exceeds 260.

    The public/evidence path remains the ordinary human-readable path.  The
    ``\\?\\`` form is used only at the Python filesystem boundary.
    """
    name = _os.name if os_name is None else str(os_name)
    raw = _os.fspath(path)
    if name != "nt":
        return _os.path.abspath(raw)
    absolute = ntpath.normpath(ntpath.abspath(raw))
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _short_temp_path(path, tag="j"):
    """Create a unique short sibling name without repeating destination.name."""
    path = Path(path)
    seed = "%s|%s|%s|%s|%s" % (
        path.name,
        _os.getpid(),
        threading.get_ident(),
        time.monotonic_ns(),
        tag,
    )
    token = hashlib.blake2s(seed.encode("utf-8"), digest_size=8).hexdigest()
    return path.parent / (".r1%s_%s.tmp" % (str(tag)[:2], token))


def _ensure_parent(path):
    parent = Path(path).parent
    _os.makedirs(_native_path(parent), exist_ok=True)
    return parent


def _exists(path):
    return _os.path.exists(_native_path(path))


def _is_file(path):
    return _os.path.isfile(_native_path(path))


def _size(path):
    return int(_os.path.getsize(_native_path(path)))


def _unlink(path, *, missing_ok=True):
    try:
        _os.unlink(_native_path(path))
    except FileNotFoundError:
        if not missing_ok:
            raise


def _open_text(path, mode, *, encoding="utf-8"):
    return _OPEN(_native_path(path), mode, encoding=encoding)


def replace_with_retry(src, dst, attempts=16):
    """Atomic replacement with bounded Windows lock retry and long-path support."""
    _ensure_parent(dst)
    delay = 0.025
    last = None
    attempts = max(1, int(attempts))
    for i in range(attempts):
        try:
            _REAL_REPLACE(_native_path(src), _native_path(dst))
            return
        except OSError as exc:
            last = exc
            if not _transient(exc) or i == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 1.8, 0.5)
    raise last


def safe_copy2(source, destination):
    _ensure_parent(destination)
    return _shutil.copy2(_native_path(source), _native_path(destination))


def safe_sha256_file(path, chunk_size=1024 * 1024):
    h = hashlib.sha256()
    with _OPEN(_native_path(path), "rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def critical_atomic_json(path, value):
    import r1_15a2_controller_v22 as ctrl

    path = Path(path)
    _ensure_parent(path)
    tmp = _short_temp_path(path, "j")
    try:
        with _open_text(tmp, "w", encoding="utf-8") as h:
            json.dump(
                ctrl.report_safe(value),
                h,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            h.flush()
            _os.fsync(h.fileno())
        replace_with_retry(tmp, path)
        if not _is_file(path) or _size(path) <= 0:
            raise OSError("IOFIX3_ATOMIC_JSON_READBACK_MISSING:" + str(path))
    finally:
        try:
            if _exists(tmp):
                _unlink(tmp)
        except OSError:
            pass


def critical_atomic_text(path, value, encoding="utf-8"):
    path = Path(path)
    _ensure_parent(path)
    tmp = _short_temp_path(path, "t")
    try:
        with _open_text(tmp, "w", encoding=encoding) as h:
            h.write(value)
            h.flush()
            _os.fsync(h.fileno())
        replace_with_retry(tmp, path)
        if not _is_file(path):
            raise OSError("IOFIX3_ATOMIC_TEXT_READBACK_MISSING:" + str(path))
    finally:
        try:
            if _exists(tmp):
                _unlink(tmp)
        except OSError:
            pass


def critical_copy_if_file(source, destination):
    """Long-path-safe atomic evidence copy used by runtime helper mirrors."""
    source = Path(source)
    destination = Path(destination)
    if not _is_file(source):
        return None
    _ensure_parent(destination)
    tmp = _short_temp_path(destination, "c")
    try:
        if _exists(tmp):
            _unlink(tmp)
        safe_copy2(source, tmp)
        if safe_sha256_file(source) != safe_sha256_file(tmp):
            raise OSError("IOFIX3_ATOMIC_COPY_HASH_MISMATCH:" + str(destination))
        replace_with_retry(tmp, destination)
        if not _is_file(destination) or _size(destination) != _size(source):
            raise OSError("IOFIX3_ATOMIC_COPY_READBACK_MISMATCH:" + str(destination))
    finally:
        try:
            if _exists(tmp):
                _unlink(tmp)
        except OSError:
            pass
    return destination



def critical_runtime_read_json(path):
    with _OPEN(_native_path(path), "r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def critical_runtime_write_json(path, value):
    """Preserve runtime_v1 JSON semantics with atomic long-path-safe I/O."""
    path = Path(path)
    _ensure_parent(path)
    tmp = _short_temp_path(path, "rj")
    try:
        with _OPEN(_native_path(tmp), "w", encoding="utf-8") as stream:
            json.dump(
                value,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            )
            stream.flush()
            _os.fsync(stream.fileno())
        replace_with_retry(tmp, path)
        if not _is_file(path) or _size(path) <= 0:
            raise OSError("IOFIX3_RUNTIME_JSON_READBACK_MISSING:" + str(path))
    finally:
        try:
            if _exists(tmp):
                _unlink(tmp)
        except OSError:
            pass


def critical_runtime_write_csv(path, rows, fields=None):
    """Preserve runtime_v1 CSV schema while avoiding deep-path failures."""
    path = Path(path)
    _ensure_parent(path)
    rows = list(rows or [])
    if fields is None:
        fields = []
        seen = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    fields.append(key)
                    seen.add(key)
        if not fields:
            fields = ["empty"]
    tmp = _short_temp_path(path, "rc")
    try:
        with _OPEN(
            _native_path(tmp), "w", newline="", encoding="utf-8-sig"
        ) as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=list(fields),
                delimiter=";",
                extrasaction="ignore",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fields})
            stream.flush()
            _os.fsync(stream.fileno())
        replace_with_retry(tmp, path)
        if not _is_file(path) or _size(path) <= 0:
            raise OSError("IOFIX3_RUNTIME_CSV_READBACK_MISSING:" + str(path))
    finally:
        try:
            if _exists(tmp):
                _unlink(tmp)
        except OSError:
            pass


def critical_runtime_read_csv_auto(path):
    for delimiter in (";", ","):
        try:
            with _OPEN(
                _native_path(path), "r", encoding="utf-8-sig", newline=""
            ) as stream:
                rows = [dict(row) for row in csv.DictReader(stream, delimiter=delimiter)]
            if rows and len(rows[0]) > 1:
                return rows
        except Exception:
            pass
    return []


def _patch_finecdf_reference_module(ref):
    """Patch the hash-locked v1.7 module in memory, never on disk.

    The scientific source hash and all numerical methods remain unchanged.  Only
    its generic evidence publication helpers are redirected to the same bounded,
    atomic, long-path-safe implementation as the outer controller.
    """
    if getattr(ref, "_R1_IOFIX3_PATHFIX3_ACTIVE", False):
        return ref

    def ref_write_json(path, data):
        path = Path(path)
        _ensure_parent(path)
        tmp = _short_temp_path(path, "fj")
        try:
            with _OPEN(_native_path(tmp), "w", encoding="utf-8") as stream:
                json.dump(
                    ref.plain(data),
                    stream,
                    ensure_ascii=True,
                    indent=2,
                    allow_nan=False,
                )
                stream.flush()
                _os.fsync(stream.fileno())
            replace_with_retry(tmp, path)
            if not _is_file(path) or _size(path) <= 0:
                raise OSError("IOFIX3_FINECDF_JSON_READBACK_MISSING:" + str(path))
        finally:
            try:
                if _exists(tmp):
                    _unlink(tmp)
            except OSError:
                pass

    def ref_write_csv(path, rows):
        rows = [ref.plain(row) for row in rows]
        fields = list(dict.fromkeys(key for row in rows for key in row)) or ["empty"]
        path = Path(path)
        _ensure_parent(path)
        tmp = _short_temp_path(path, "fc")
        try:
            with _OPEN(
                _native_path(tmp), "w", newline="", encoding="utf-8-sig"
            ) as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=fields,
                    delimiter=";",
                    extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(rows)
                stream.flush()
                _os.fsync(stream.fileno())
            replace_with_retry(tmp, path)
            if not _is_file(path) or _size(path) <= 0:
                raise OSError("IOFIX3_FINECDF_CSV_READBACK_MISSING:" + str(path))
        finally:
            try:
                if _exists(tmp):
                    _unlink(tmp)
            except OSError:
                pass

    def ref_dump_arrays(path, arrays):
        path = Path(path)
        _ensure_parent(path)
        tmp = _short_temp_path(path, "fa")
        try:
            with _OPEN(_native_path(tmp), "wb") as stream:
                ref.np.savez_compressed(
                    stream,
                    **{"M%d" % number: array for number, array in arrays.items()},
                )
                stream.flush()
                _os.fsync(stream.fileno())
            replace_with_retry(tmp, path)
            if not _is_file(path) or _size(path) <= 0:
                raise OSError("IOFIX3_FINECDF_ARRAY_READBACK_MISSING:" + str(path))
        finally:
            try:
                if _exists(tmp):
                    _unlink(tmp)
            except OSError:
                pass

    def ref_preflight_output_storage(root):
        root = Path(root)
        _ensure_parent(root / "x")
        final = root / "00_STORAGE_PREFLIGHT.txt"
        critical_atomic_text(final, "R1_BC_LOCAL_OUTPUT_READWRITE_OK\n", encoding="ascii")
        with _OPEN(_native_path(final), "r", encoding="ascii") as stream:
            value = stream.read().strip()
        ref.require(
            value == "R1_BC_LOCAL_OUTPUT_READWRITE_OK",
            "Cannot verify write/read round-trip in output folder",
        )
        _unlink(final, missing_ok=False)

    ref.replace_with_retry = replace_with_retry
    ref.write_json = ref_write_json
    ref.write_csv = ref_write_csv
    ref.dump_arrays = ref_dump_arrays
    ref.preflight_output_storage = ref_preflight_output_storage
    ref.sha_file = safe_sha256_file
    ref._R1_IOFIX3_PATHFIX3_ACTIVE = True
    return ref


def _patch_finecdf_loader(bridge):
    current = bridge.load_reference
    if getattr(current, "_R1_IOFIX3_PATHFIX3_WRAPPED", False):
        return

    def load_reference_with_iofix3(*args, **kwargs):
        result = current(*args, **kwargs)
        if not isinstance(result, tuple) or len(result) < 1:
            raise RuntimeError("IOFIX3_FINECDF_REFERENCE_LOADER_CONTRACT_CHANGED")
        _patch_finecdf_reference_module(result[0])
        return result

    load_reference_with_iofix3._R1_IOFIX3_PATHFIX3_WRAPPED = True
    load_reference_with_iofix3._R1_IOFIX3_ORIGINAL = current
    bridge.load_reference = load_reference_with_iofix3

def audit_run_path_budget(run_folder):
    """Audit representative deepest paths before any model-side mutation.

    Extended-length I/O protects Python evidence files, while Visum SaveVersion
    still benefits from a conservative ordinary path budget.  The short run-root
    launcher is expected to keep all representative logical paths below 240.
    """
    run = Path(run_folder)
    samples = {
        "run_directory": run,
        "working_profile488_start": run / "WORKING_PROFILE488_START.ver",
        "accepted_checkpoint": (
            run
            / "CALIBRATION"
            / "CHECKPOINTS"
            / "ACCEPTED_B_0100_0123456789ab.ver"
        ),
        "deep_td_rollback_json": (
            run
            / "CALIBRATION"
            / "DEMAND_CYCLE_100_TD_FINECDF"
            / "REALIZATION"
            / "TRY_16_SCALE_0p000030517578125"
            / "RESTORE_PARENT_BC"
            / "ROLLBACK_PARAMETER_READBACK.json"
        ),
        "deep_td_freeze_audit": (
            run
            / "CALIBRATION"
            / "DEMAND_CYCLE_100_TD_FINECDF"
            / "ROLLBACK_AFTER_TD_FAILURE"
            / "TD_PARENT_AFTER_DIAGNOSTICS_FREEZE_AUDIT.json"
        ),
        "deep_downstream_execution_plan": (
            run
            / "CALIBRATION"
            / "DEMAND_CYCLE_100_TD_FINECDF"
            / "REALIZATION"
            / "TRY_16_SCALE_0p000030517578125"
            / "FULL_DOWNSTREAM_RECOMPUTE"
            / "PROCEDURE_EXECUTION_PLAN_ACTIVE.json"
        ),
        "deep_finecdf_final_cdf": (
            run
            / "CALIBRATION"
            / "DEMAND_CYCLE_100_TD_FINECDF"
            / "REALIZATION"
            / "TRY_16_SCALE_0p000030517578125"
            / "FINECDF_INNER"
            / "FINAL_FINECDF"
            / "COMPONENT_FINE_CDF.csv"
        ),
        "best_semantic_sidecar": (
            run
            / "CALIBRATION"
            / "CHECKPOINTS"
            / "BEST_SO_FAR_0100_0123456789ab.ver.semantic.json"
        ),
        "v24916_generation_evidence_manifest": (
            run
            / "CALIBRATION"
            / "DEMAND_CYCLE_100_GENERATION"
            / "TRY_05"
            / "V24916_ACTIVE_TARGETING"
            / "EVIDENCE"
            / "14_DEMAND_EVIDENCE_MANIFEST.json"
        ),
        "v24916_td_evidence_manifest": (
            run
            / "CALIBRATION"
            / "DEMAND_CYCLE_100_TD_FINECDF"
            / "TARGETING"
            / "EVIDENCE"
            / "14_DEMAND_EVIDENCE_MANIFEST.json"
        ),
        "v24916_td_fresh_epoch_progress": (
            run
            / "CALIBRATION"
            / "DEMAND_CYCLE_100_TD_FINECDF"
            / "TARGETING"
            / "RECOVERY_TD_FRESH_PATH_EPOCH"
            / "PATHLINK_EXPORT_PROGRESS.json"
        ),
    }
    rows = []
    for label, path in samples.items():
        temp = _short_temp_path(path, "j")
        rows.append(
            {
                "label": label,
                "path": str(path),
                "logical_length": len(str(path)),
                "short_temp_path": str(temp),
                "short_temp_logical_length": len(str(temp)),
            }
        )
    maximum = max(max(r["logical_length"], r["short_temp_logical_length"]) for r in rows)
    return {
        "schema": "R1_15A2_PROFILE488_IOFIX3_PATH_BUDGET_V1",
        "passes": maximum < _SAFE_LOGICAL_PATH_BUDGET,
        "run_directory": str(run),
        "run_directory_length": len(str(run)),
        "safe_logical_path_budget": _SAFE_LOGICAL_PATH_BUDGET,
        "historical_max_path_limit": _MAX_PATH_DIAGNOSTIC_LIMIT,
        "max_projected_logical_length": maximum,
        "windows_extended_path_io_active": _os.name == "nt",
        "short_temp_name_policy": "OPAQUE_FIXED_LENGTH_SIBLING_NOT_DESTINATION_NAME_PLUS_SUFFIX",
        "samples": rows,
    }


class _OSProxy:
    def __getattr__(self, name):
        return getattr(_os, name)

    @staticmethod
    def replace(src, dst):
        return replace_with_retry(src, dst)


class _ShutilProxy:
    def __getattr__(self, name):
        return getattr(_shutil, name)

    @staticmethod
    def copy2(src, dst, *args, **kwargs):
        _ensure_parent(dst)
        return _shutil.copy2(_native_path(src), _native_path(dst), *args, **kwargs)

    @staticmethod
    def copyfile(src, dst, *args, **kwargs):
        _ensure_parent(dst)
        return _shutil.copyfile(_native_path(src), _native_path(dst), *args, **kwargs)


def activate():
    import r1_15a2_controller_v22 as ctrl
    import r1_15a2_inplace_transaction_v24915p2 as txn
    import r1_15a2_two_mode_v238 as two
    import r1_15a2_trial_adapter_v240 as trial
    import r1_15a2_overnight_controller_v24915p2 as ov
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as force
    import r1_15a2_persistent_path_cache_v248 as pc
    import r1_15a2_runtime_v1 as rt
    import r1_15a2_acceleration_v24915p1 as perf1
    import r1_15a2_finecdf_bridge_v242 as fine_bridge
    import r1_15a2_full_geometry_gate_v239 as geometry

    old = {
        ctrl.atomic_json,
        txn.atomic_json,
        two.atomic_json,
        ov.atomic_json,
        force.atomic_json,
        trial.atomic_json,
    }
    ctrl.atomic_json = critical_atomic_json
    txn.atomic_json = critical_atomic_json
    two.atomic_json = critical_atomic_json
    trial.atomic_json = critical_atomic_json
    ov.atomic_json = critical_atomic_json
    force.atomic_json = critical_atomic_json
    pc.atomic_json = critical_atomic_json
    pc.atomic_text = critical_atomic_text

    # Protect direct os.replace publications and Python copies in helper mirrors,
    # cache promotion, and BEST_SO_FAR checkpoint publication.
    os_proxy = _OSProxy()
    shutil_proxy = _ShutilProxy()
    rt.os = os_proxy
    pc.os = os_proxy
    force.os = os_proxy
    rt.shutil = shutil_proxy
    pc.shutil = shutil_proxy
    force.shutil = shutil_proxy
    rt._copy_if_file = critical_copy_if_file
    rt.read_json = critical_runtime_read_json
    rt.write_json = critical_runtime_write_json
    rt.write_csv = critical_runtime_write_csv
    rt.read_csv_auto = critical_runtime_read_csv_auto
    rt.sha256_file = safe_sha256_file
    perf1._atomic_json = critical_atomic_json
    geometry.atomic_json = critical_atomic_json
    _patch_finecdf_loader(fine_bridge)
    force._sha256_file = safe_sha256_file

    # Optional V24916 modules use their own evidence helpers.  Patch them only
    # when present so the same IOFIX3 module remains compatible with V24915.
    try:
        import r1_15a2_overnight_controller_v24916 as ov16
        ov16.atomic_json = critical_atomic_json
        ov16.os = os_proxy
        ov16.shutil = shutil_proxy
        ov16._sha256_file = safe_sha256_file
    except ImportError:
        pass
    try:
        import r1_15a2_coefficient_ledger_v24916 as ledger16
        ledger16._atomic_json = critical_atomic_json
        ledger16._write_csv = critical_runtime_write_csv
    except ImportError:
        pass
    try:
        import r1_15a2_demand_evidence_v24916 as evidence16
        evidence16._write_json = critical_atomic_json
        evidence16._write_csv = critical_runtime_write_csv
        evidence16._sha256_file = safe_sha256_file
    except ImportError:
        pass
    try:
        import r1_15a2_fresh_baseline_live_preflight_v24916p2c as preflight16
        preflight16.write_live_authority = critical_atomic_json
    except ImportError:
        pass

    # Patch already-loaded local imports of the old writer.
    for mod in list(sys.modules.values()):
        try:
            if getattr(mod, "atomic_json", None) in old:
                setattr(mod, "atomic_json", critical_atomic_json)
        except Exception:
            pass
    return {
        "status": "ACTIVE",
        "policy": "CRITICAL_IO_RETRY_LONG_PATH_SAFE_THEN_FAIL_CLOSED__TELEMETRY_SEPARATE_FAIL_OPEN",
        "replace_retry_attempts": 16,
        "unique_short_temp_names": True,
        "windows_extended_length_path_io": True,
        "atomic_copy_hash_readback": True,
        "patched_scopes": [
            "controller_json",
            "rollback_json",
            "two_mode_json",
            "path_cache_json_text",
            "helper_os_replace",
            "helper_atomic_copy",
            "runtime_json_csv_read_write",
            "perf1_rollback_proof_json",
            "full_geometry_progress_json",
            "finecdf_v17_dynamic_evidence_writers",
            "path_cache_dir_publish",
            "best_so_far_ver_publish",
            "v24916_demand_evidence_json_csv",
            "v24916_coefficient_ledger_json_csv",
            "v24916_live_authority",
            "v24916_short_runs_root",
        ],
        "sealed_parent_files_modified_on_disk": False,
    }


__all__ = [
    "activate",
    "audit_run_path_budget",
    "critical_atomic_json",
    "critical_atomic_text",
    "critical_copy_if_file",
    "critical_runtime_read_json",
    "critical_runtime_write_json",
    "critical_runtime_write_csv",
    "critical_runtime_read_csv_auto",
    "replace_with_retry",
    "safe_copy2",
    "safe_sha256_file",
    "_native_path",
    "_short_temp_path",
]
