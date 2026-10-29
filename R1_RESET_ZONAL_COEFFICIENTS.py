# -*- coding: utf-8 -*-
"""Run inside the OPEN Visum model: Scripts -> Run script file.

Reset the 13 zonal calibration coefficients to their agreed references,
preserving every existing zero. Save a model copy before running this script.
No Excel, NumPy, project imports, new Visum instance or native calculation needed.
The model is not saved. Start a NEW calibration run after the reset.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

EXPECTED_ZONES = 681
SHOW_MESSAGE_BOX = True
REFERENCES = {
    "ADD_PROD_W": 1.0, "ADD_ATT_W": 1.0,
    "ADD_PROD_S": 1.0, "ADD_ATT_S": 1.0,
    "ADD_PROD_SCH": 1.0, "ADD_ATT_SCH": 1.0,
    "ADD_PROD_L": 0.3, "ADD_ATT_L": 1.0, "ADD_SALARY": 1.0,
    "ZAHR_PROD_WORK": 1.0, "ZAHR_ATR_WORK": 1.0,
    "ZAHR_PROD_SERV": 1.0, "ZAHR_ATR_SERV": 1.0,
}


class ResetError(RuntimeError):
    pass


def _integer(value):
    if isinstance(value, bool):
        raise ResetError("INVALID_ZONE_OR_COM_INDEX")
    number = float(value)
    if not math.isfinite(number) or number < 1 or not number.is_integer():
        raise ResetError("INVALID_ZONE_OR_COM_INDEX")
    return int(number)


def _number(value):
    if isinstance(value, bool) or value is None:
        raise ResetError("INVALID_COEFFICIENT")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ResetError("INVALID_COEFFICIENT")
    return number


def _binding(zones):
    pairs = [(_integer(i), _integer(no)) for i, no in zones.GetMultiAttValues("NO", False)]
    if (len(pairs) != EXPECTED_ZONES or len({i for i, _ in pairs}) != EXPECTED_ZONES
            or len({no for _, no in pairs}) != EXPECTED_ZONES):
        raise ResetError("EXPECTED_681_UNIQUE_ZONES_AND_COM_INDICES")
    return tuple(sorted(pairs))


def _require_binding(zones, binding):
    if _binding(zones) != binding:
        raise ResetError("ZONE_BINDING_CHANGED")


def _snapshot(zones, binding):
    _require_binding(zones, binding)
    by_index = dict(binding)
    values = {}
    for attr in REFERENCES:
        result = {}
        for i, value in zones.GetMultiAttValues(attr, False):
            index = _integer(i)
            if index not in by_index or by_index[index] in result:
                raise ResetError("COEFFICIENT_INDEX_MISMATCH:" + attr)
            result[by_index[index]] = _number(value)
        if len(result) != len(binding):
            raise ResetError("COEFFICIENT_ROWS_MISSING:" + attr)
        values[attr] = result
    _require_binding(zones, binding)
    return values


def _write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def _backup(folder, binding, before, after):
    data = {"schema": "R1_ZONAL_COEFFICIENT_RESET_BACKUP_V1", "references": REFERENCES,
            "zones": [no for _, no in binding], "before": before}
    _write_json(folder / "BEFORE.json", data)
    with (folder / "OBNOVA_KOEFICIENTU.att").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("$VISION\n$ZONE:NO;" + ";".join(REFERENCES) + "\n")
        for _, no in binding:
            stream.write(str(no) + ";" + ";".join(repr(before[a][no]) for a in REFERENCES) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    with (folder / "CHANGES.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["NO", "ATTRIBUTE", "BEFORE", "AFTER"])
        for attr in REFERENCES:
            for _, no in binding:
                if before[attr][no] != after[attr][no]:
                    writer.writerow([no, attr, repr(before[attr][no]), repr(after[attr][no])])
        stream.flush()
        os.fsync(stream.fileno())


def _restore(zones, before, touched):
    errors = []
    for attr in reversed(touched):
        try:
            binding = _binding(zones)
            if {no for _, no in binding} != set(before[attr]):
                raise ResetError("ROLLBACK_ZONE_SET_CHANGED")
            zones.SetMultiAttValues(attr, [(i, before[attr][no]) for i, no in binding])
        except BaseException as error:
            errors.append(attr + ":" + type(error).__name__ + ":" + str(error))
    try:
        observed = _snapshot(zones, _binding(zones))
        verified = observed == before
        if not verified:
            errors.append("ROLLBACK_READBACK_MISMATCH")
    except BaseException as error:
        verified = False
        errors.append("ROLLBACK_READBACK:" + type(error).__name__ + ":" + str(error))
    return verified, errors


def reset_coefficients(visum, output_base=None):
    """Write only the 13 coefficient attributes; verified rollback on any failure."""
    zones = visum.Net.Zones
    binding = _binding(zones)
    before = _snapshot(zones, binding)  # ALL attributes must be readable before any write.
    after = {attr: {no: (0.0 if value == 0 else REFERENCES[attr])
                    for no, value in entries.items()} for attr, entries in before.items()}
    counts = {attr: sum(before[attr][no] != after[attr][no] for _, no in binding)
              for attr in REFERENCES}
    base = Path(output_base) if output_base is not None else Path(
        os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "R1DF" / "ZONAL_RESET"
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_")
    folder = Path(tempfile.mkdtemp(prefix=stamp, dir=str(base)))
    _backup(folder, binding, before, after)  # Failure here cannot leave a partial model write.
    report = {"status": "PREPARED", "backup_directory": str(folder), "zone_count": len(binding),
              "references": REFERENCES, "changed_by_attribute": counts,
              "changed_cells": sum(counts.values()),
              "preserved_zeros": {a: sum(v == 0 for v in before[a].values()) for a in REFERENCES},
              "before_sha256": hashlib.sha256((folder / "BEFORE.json").read_bytes()).hexdigest(),
              "model_saved": False, "native_recomputed": False}
    report_path = folder / "REPORT.json"
    _write_json(report_path, report)
    # The durable backup must still describe the exact live parent.
    if _snapshot(zones, binding) != before:
        report["status"] = "ABORTED_PARENT_CHANGED_BEFORE_WRITE"
        _write_json(report_path, report)
        raise ResetError("PARENT_CHANGED_BEFORE_WRITE; backup=" + str(folder))
    touched = []
    try:
        for attr in REFERENCES:
            if not counts[attr]:
                continue
            _require_binding(zones, binding)
            touched.append(attr)  # A throwing bulk COM setter can already have changed rows.
            zones.SetMultiAttValues(attr, [(i, after[attr][no]) for i, no in binding])
        if _snapshot(zones, binding) != after:
            raise ResetError("RESET_READBACK_MISMATCH")
        report["status"] = "RESET_VERIFIED_NATIVE_RECOMPUTE_REQUIRED"
        _write_json(report_path, report)  # An unrecorded reset is rolled back as well.
    except BaseException as error:
        verified, restore_errors = _restore(zones, before, touched)
        report.update(status="ROLLBACK_VERIFIED" if verified else "ROLLBACK_UNVERIFIED_REOPEN_SAVED_MODEL",
                      error=type(error).__name__ + ":" + str(error), rollback_errors=restore_errors)
        try:
            _write_json(report_path, report)
        except BaseException as log_error:
            restore_errors.append("REPORT_WRITE_FAILED:" + str(log_error))
        raise ResetError(report["status"] + "; backup=" + str(folder)
                         + "; cause=" + str(error) + "; rollback_errors=" + repr(restore_errors)) from error
    return report


def _run_in_visum():
    visum = globals().get("Visum")
    if visum is None:
        import __main__
        visum = getattr(__main__, "Visum", None)
    if visum is None:
        raise ResetError("Spustte tento soubor uvnitr otevreneho Visumu: Scripts -> Run script file.")
    try:
        result = reset_coefficients(visum)
        message = ("Reset koeficientu overen. Zmeneno bunek: %d.\nZaloha a protokol: %s\n"
                   "Model neni ulozen. Spustte NOVOU kalibraci; dosavadni vysledky vyzaduji prepocet."
                   % (result["changed_cells"], result["backup_directory"]))
    except BaseException as error:
        message = "Reset nebyl dokoncen: " + str(error)
        _notify(message)
        raise
    _notify(message)
    return result


def _notify(message):
    print(message)
    if SHOW_MESSAGE_BOX and os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "R1 reset zonalnich koeficientu", 0)
        except Exception:
            pass  # Reporting UI cannot invalidate a completed transaction.


if __name__ == "__main__" or globals().get("Visum") is not None:
    _run_in_visum()
