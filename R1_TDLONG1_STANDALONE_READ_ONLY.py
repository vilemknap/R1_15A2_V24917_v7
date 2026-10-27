# -*- coding: utf-8 -*-
"""Samostatna cteci sonda LONG trip distribution pro PTV Visum.

Spustit v otevrenem modelu pres Scripts -> Run script file. Nepotrebuje zadny
dalsi soubor z projektu. Pouze cte COM; nespousti vypocet ani neuklada .ver.
Vysledek ulozi vedle skriptu, na plochu a do docasne slozky, pokud jsou
prislusna umisteni zapisovatelna. Ulozene cesty zobrazi v okne.
"""
from __future__ import annotations

from datetime import datetime
import builtins
import inspect
import json
import os
from pathlib import Path
import re
import tempfile
import traceback


RELEASE = "R1_TDLONG1_STANDALONE_READ_ONLY_V2_20261027"
LONG_CODES = (
    "3_LONG_E_C", "3_LONG_E_noC", "3_LONG_noE_C",
    "3_LONG_noE_noC", "3_LONG_stud",
)


def _is_visum(candidate):
    if candidate is None:
        return False
    try:
        return getattr(candidate, "Procedures", None) is not None and \
            getattr(candidate, "Net", None) is not None
    except Exception:
        return False


def _visum_object():
    # Visum scripts may receive either Visum or COM, including via builtins.
    for source, candidate in (
        ("injected_Visum", globals().get("Visum")),
        ("injected_COM", globals().get("COM")),
        ("builtins_Visum", getattr(builtins, "Visum", None)),
        ("builtins_COM", getattr(builtins, "COM", None)),
    ):
        if _is_visum(candidate):
            return candidate, source

    # Attach only to an existing instance. Dispatch/LoadVersion are never used.
    import win32com.client  # type: ignore
    errors = []
    for progid in ("Visum.Visum.260", "Visum.Visum.250", "Visum.Visum"):
        try:
            candidate = win32com.client.GetActiveObject(progid)
            if _is_visum(candidate):
                return candidate, "GetActiveObject(" + progid + ")"
            errors.append(progid + ":NOT_VISUM_OBJECT")
        except Exception as exc:
            errors.append(progid + ":" + type(exc).__name__)
    raise RuntimeError("NO_RUNNING_VISUM_COM_INSTANCE:" + ",".join(errors))


def _member(value):
    # A COM Dispatch property can itself be callable: do not invoke it.
    if getattr(value, "_oleobj_", None) is not None:
        return value
    if inspect.ismethod(value) or inspect.isfunction(value) or inspect.isbuiltin(value):
        return value()
    return value


def _attribute(obj, name):
    try:
        return obj.AttValue(name)
    except Exception:
        return _member(getattr(obj, name))


def _optional_attribute(obj, name):
    try:
        value = _attribute(obj, name)
        return "" if value is None else str(value)
    except Exception:
        return ""


def _active(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        word = value.strip().lower()
        if word in ("true", "yes", "active"):
            return True
        if word in ("false", "no", "inactive"):
            return False
    number = float(value)
    if number not in (-1.0, 0.0, 1.0):
        raise ValueError("UNKNOWN_ACTIVE_FLAG:" + str(value))
    return number != 0.0


def _codes(raw):
    return {token.strip("'\"").upper() for token in re.split(r"[,;{}\s]+", raw)
            if token.strip("'\"")}


def _operation_row(op, position):
    parameters, parameter_source = None, None
    for name in ("TripDistributionParameters", "TripDistributionParameter"):
        try:
            candidate = _member(getattr(op, name))
            if candidate is not None:
                parameters, parameter_source = candidate, name
                break
        except Exception:
            continue

    raw, dstrat_source = "", None
    if parameters is not None:
        for name in ("DSTRATSET", "DStratSet", "DEMANDSTRATUMSET"):
            try:
                value = _attribute(parameters, name)
                if value is not None and str(value).strip():
                    raw, dstrat_source = str(value), name
                    break
            except Exception:
                continue

    codes = _codes(raw)
    expected = {code.upper() for code in LONG_CODES}
    return {
        "position": position,
        "active": _active(_attribute(op, "ACTIVE")),
        "name": _optional_attribute(op, "NAME"),
        "comment": _optional_attribute(op, "COMMENT"),
        "parameter_source": parameter_source,
        "parameter_status": "READABLE" if parameters is not None else "UNREADABLE",
        "dstratset_source": dstrat_source,
        "dstratset_raw": raw,
        "dstratset_codes": sorted(codes),
        "long_components_present": sorted(codes & expected),
        "long_components_missing": sorted(expected - codes),
    }


def inspect_read_only(visum, source):
    operations = list(_member(getattr(visum.Procedures.Operations, "GetAll")))
    if not operations:
        raise RuntimeError("EMPTY_OPERATION_LIST")
    rows = []
    for position, op in enumerate(operations, 1):
        kind = int(_attribute(op, "OPERATIONTYPE"))
        if kind == 46:
            rows.append(_operation_row(op, position))
    active = [row for row in rows if row["active"]]
    return {
        "release": RELEASE,
        "status": "UNVERIFIED_NATIVE_FILTER",
        "binding_source": source,
        "operation_type": 46,
        "operation_count": len(operations),
        "active_td_operation_count": len(active),
        "operations": rows,
        "known_long_dstrat_codes": list(LONG_CODES),
        "native_pair_filter_api": "UNVERIFIED_NOT_PROBED_BY_GUESS",
        "dstratset_is_pair_filter_evidence": False,
        "native_filter_verified": False,
        "long_generation_permitted": False,
        "read_only": True,
        "mutating_calls_made": [],
    }


def _notice(message):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "TDLONG1 read-only sonda", 0x40000)
    except Exception:
        pass


def _output_directories():
    explicit = globals().get("R1_TDLONG1_OUTPUT_DIR")
    if explicit:
        return [Path(explicit)]
    candidates = []
    script_file = globals().get("__file__")
    if script_file:
        candidates.append(Path(script_file).resolve().parent)
    for base in (os.environ.get("OneDrive"), os.environ.get("USERPROFILE")):
        if base:
            candidates.append(Path(base) / "Desktop")
    candidates.append(Path.home() / "Desktop")
    candidates.append(Path(tempfile.gettempdir()))
    seen = set()
    result = []
    for candidate in candidates:
        try:
            key = os.path.normcase(str(candidate.resolve()))
        except Exception:
            key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def _run():
    try:
        visum, source = _visum_object()
        report = inspect_read_only(visum, source)
    except Exception as exc:
        report = {
            "release": RELEASE,
            "status": "PROBE_ERROR",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "native_filter_verified": False,
            "long_generation_permitted": False,
            "read_only": True,
            "mutating_calls_made": [],
        }
    report["timestamp_local"] = datetime.now().astimezone().isoformat()
    filename = "R1_TDLONG1_READ_ONLY_%s_%s.json" % (
        datetime.now().strftime("%Y%m%d_%H%M%S_%f"), os.getpid())
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    saved, errors = [], []
    try:
        directories = _output_directories()
    except Exception as exc:
        directories = []
        errors.append("OUTPUT_LOCATIONS:" + repr(exc))
    for directory in directories:
        try:
            if directory.exists() and directory.is_dir():
                path = directory / filename
                path.write_text(payload, encoding="utf-8")
                saved.append(str(path))
            else:
                errors.append(str(directory) + ":NOT_A_DIRECTORY")
        except Exception as exc:
            errors.append(str(directory) + ":" + repr(exc))
    if saved:
        message = "Stav: %s\nJSON ulozen do:\n%s" % (report["status"], "\n".join(saved))
        print(message)
        _notice(message)
        return saved[0]
    message = "TDLONG1: JSON se nepodarilo ulozit.\n" + "\n".join(errors)
    print(message)
    _notice(message)
    return None


# Visum may execute the file with a nonstandard __name__; run unconditionally.
R1_TDLONG1_PROBE_OUTPUT = _run()
