"""Full same-mode path-link identity gate for R1 15A2 V2.3.9.

This module compares every saved PrT path-link sequence for all 12 passenger
DSegs. It stores only one SHA-256 digest per path for the representative DSeg of
each mode, then streams all other DSegs against that reference. It never runs an
assignment and never writes to the Visum model.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math
import os
import sqlite3
import struct
import time

import r1_15a2_core as core
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError
from r1_15a2_two_mode_v238 import (
    GEOMETRY_COLUMNS, EXPECTED_MODE_DSEGS, create_list, bounded_rows,
    DEFAULT_SETTINGS, _filled, _id,
)

REPRESENTATIVE = {"C": "NATIVE_CW", "C_NOT": "NATIVE_CW_NOT"}


def atomic_json(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_name(p.name + ".tmp")
    with t.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=True, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(t, p)


class GateStop(RuntimeError):
    pass


class GateControl:
    def __init__(self, run_dir, max_seconds=28800.0, progress_interval=2.0, clock=time.monotonic):
        self.run_dir = Path(run_dir)
        self.clock = clock
        self.started = clock()
        self.max_seconds = float(max_seconds)
        self.progress_interval = float(progress_interval)
        self.last_write = -1e99
        self.progress = {
            "schema": "R1_15A2_15T_FULL_GEOMETRY_PROGRESS_V1",
            "status": "RUNNING", "phase": "STARTING", "apply": False,
            "assignment_executed": False, "writes_to_visum": False,
        }
        self.stop_paths = (self.run_dir / "STOP_REQUESTED", self.run_dir.parent / "STOP_REQUESTED")
        self.checkpoint("STARTING", force=True)

    def checkpoint(self, phase=None, force=False, **extra):
        if phase is not None:
            self.progress["phase"] = phase
        self.progress.update(extra)
        now = self.clock()
        reason = None
        if any(p.exists() for p in self.stop_paths):
            reason = "USER_STOP_REQUESTED"
        if now - self.started >= self.max_seconds:
            reason = reason or "SAFETY_GATE_TIME_BUDGET_EXCEEDED"
        if reason:
            self.progress.update(status="STOP_REQUESTED", stop_reason=reason)
            self._write(now)
            raise GateStop(reason)
        if force or now - self.last_write >= self.progress_interval:
            self._write(now)

    def _write(self, now):
        self.progress["elapsed_seconds"] = round(now - self.started, 3)
        atomic_json(self.run_dir / "15T_PROGRESS.json", self.progress)
        self.last_write = now

    def finish(self, status, **extra):
        self.progress.update(status=status, phase="FINISHED", **extra)
        self._write(self.clock())


def _route_digest(edge_records):
    h = hashlib.sha256()
    n = 0
    last_to = None
    expected_index = 1
    for idx, link, fn, tn in edge_records:
        if idx != expected_index:
            raise SupplyContractError("FULL_GEOMETRY_LINK_INDEX_NOT_CONTIGUOUS")
        if last_to is not None and last_to != fn:
            raise SupplyContractError("FULL_GEOMETRY_DISCONNECTED_PATH")
        h.update(struct.pack("<IIII", idx, link, fn, tn))
        n += 1
        expected_index += 1
        last_to = tn
    return h.hexdigest(), n


def route_digests(raw_rows, control=None, phase="FULL_GEOMETRY"):
    """Yield (parent_key, sequence_sha256, edge_count) from hierarchical or flat list rows."""
    parent = None
    edge_records = []
    seen = set()
    raw_count = 0

    def finish():
        if parent is None:
            return None
        if parent in seen:
            raise SupplyContractError("FULL_GEOMETRY_DUPLICATE_PARENT_KEY")
        if not edge_records and parent[0] != parent[1]:
            raise SupplyContractError("FULL_GEOMETRY_EMPTY_INTERZONAL_PATH")
        digest, n = _route_digest(edge_records)
        seen.add(parent)
        return parent, digest, n

    for raw in raw_rows:
        raw_count += 1
        if len(raw) != 7:
            raise SupplyContractError("FULL_GEOMETRY_ROW_SCHEMA_MISMATCH")
        pflags = tuple(_filled(x) for x in raw[:3])
        lflags = tuple(_filled(x) for x in raw[3:])
        if not any(lflags):
            if not all(pflags):
                raise SupplyContractError("FULL_GEOMETRY_INCOMPLETE_PARENT_ROW")
            completed = finish()
            if completed is not None:
                yield completed
            parent = tuple(_id(x) for x in raw[:3])
            edge_records = []
            continue
        if not all(lflags):
            raise SupplyContractError("FULL_GEOMETRY_INCOMPLETE_CHILD_ROW")
        if all(pflags):
            k = tuple(_id(x) for x in raw[:3])
            if parent != k:
                completed = finish()
                if completed is not None:
                    yield completed
                parent = k
                edge_records = []
        elif any(pflags):
            if parent is None or any(flag and _id(raw[j]) != parent[j] for j, flag in enumerate(pflags)):
                raise SupplyContractError("FULL_GEOMETRY_CONFLICTING_PARTIAL_PARENT")
        if parent is None:
            raise SupplyContractError("FULL_GEOMETRY_ORPHAN_CHILD")
        edge_records.append(tuple(_id(x) for x in raw[3:]))
        if control is not None and raw_count % 65536 == 0:
            control.checkpoint(phase, parsed_raw_rows=raw_count, parsed_routes=len(seen))
    completed = finish()
    if completed is not None:
        yield completed


def _open_db(path):
    db = sqlite3.connect(str(path))
    db.executescript('''
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS reference(
            mode TEXT NOT NULL, orig INTEGER NOT NULL, dest INTEGER NOT NULL,
            path_index INTEGER NOT NULL, sequence_sha256 TEXT NOT NULL,
            edge_count INTEGER NOT NULL,
            PRIMARY KEY(mode,orig,dest,path_index)) WITHOUT ROWID;
    ''')
    return db


def _aggregate_reference_hash(db, mode):
    h = hashlib.sha256()
    n = 0
    edges = 0
    for o, d, ix, digest, count in db.execute(
        "SELECT orig,dest,path_index,sequence_sha256,edge_count FROM reference WHERE mode=? ORDER BY orig,dest,path_index",
        (mode,),
    ):
        h.update(struct.pack("<III", int(o), int(d), int(ix)))
        h.update(bytes.fromhex(digest))
        h.update(struct.pack("<I", int(count)))
        n += 1
        edges += int(count)
    return h.hexdigest(), n, edges


def build_reference(visum, db, mode, dseg_code, settings, control):
    obj = create_list(visum, "CreatePrTPathLinkList", dseg_code)
    rows = bounded_rows(obj, GEOMETRY_COLUMNS, settings, control,
                        "FULL_GEOMETRY_REFERENCE", mode=mode, dseg_code=dseg_code)
    batch = []
    routes = 0
    edges = 0
    for key, digest, count in route_digests(rows, control, "FULL_GEOMETRY_REFERENCE_PARSE"):
        batch.append((mode, *key, digest, count))
        routes += 1
        edges += count
        if len(batch) >= 5000:
            db.executemany("INSERT INTO reference VALUES(?,?,?,?,?,?)", batch)
            db.commit()
            batch.clear()
            control.checkpoint("FULL_GEOMETRY_REFERENCE_STORE", mode=mode, dseg_code=dseg_code,
                               reference_routes=routes, reference_edges=edges)
    if batch:
        db.executemany("INSERT INTO reference VALUES(?,?,?,?,?,?)", batch)
        db.commit()
    del rows, obj
    digest, count_routes, count_edges = _aggregate_reference_hash(db, mode)
    if routes != count_routes or edges != count_edges:
        raise SupplyContractError("FULL_GEOMETRY_REFERENCE_COUNT_MISMATCH")
    return {"mode": mode, "dseg_code": dseg_code, "routes": routes, "edge_children": edges,
            "aggregate_sha256": digest, "status": "REFERENCE_COMPLETE"}


def compare_dseg(visum, db, mode, dseg_code, settings, control):
    expected_count = db.execute("SELECT COUNT(*) FROM reference WHERE mode=?", (mode,)).fetchone()[0]
    obj = create_list(visum, "CreatePrTPathLinkList", dseg_code)
    rows = bounded_rows(obj, GEOMETRY_COLUMNS, settings, control,
                        "FULL_GEOMETRY_COMPARE", mode=mode, dseg_code=dseg_code)
    seen = set()
    routes = 0
    edges = 0
    mismatches = []
    for key, digest, count in route_digests(rows, control, "FULL_GEOMETRY_COMPARE_PARSE"):
        if key in seen:
            raise SupplyContractError("FULL_GEOMETRY_COMPARE_DUPLICATE_KEY")
        seen.add(key)
        ref = db.execute(
            "SELECT sequence_sha256,edge_count FROM reference WHERE mode=? AND orig=? AND dest=? AND path_index=?",
            (mode, *key),
        ).fetchone()
        routes += 1
        edges += count
        if ref is None or ref[0] != digest or int(ref[1]) != int(count):
            mismatches.append({"key": list(key), "live_sha256": digest, "live_edge_count": count,
                               "reference_sha256": None if ref is None else ref[0],
                               "reference_edge_count": None if ref is None else int(ref[1])})
            if len(mismatches) >= 8:
                break
        if routes % 10000 == 0:
            control.checkpoint("FULL_GEOMETRY_COMPARE", mode=mode, dseg_code=dseg_code,
                               compared_routes=routes, mismatches=len(mismatches))
    del rows, obj
    passes = not mismatches and routes == expected_count
    return {"mode": mode, "dseg_code": dseg_code, "routes": routes, "edge_children": edges,
            "reference_routes": int(expected_count), "mismatch_count": len(mismatches),
            "first_mismatches": mismatches, "passes": passes,
            "status": "IDENTICAL" if passes else "DIFFERENT_OR_INCOMPLETE"}


def audit_full_geometry(visum, passenger_codes, run_dir, control, max_rows_per_mode=100000000):
    settings = dict(DEFAULT_SETTINGS)
    settings.update(design_only=True, enabled=True, max_runtime_seconds=min(control.max_seconds, 86400.0),
                    max_geometry_rows_per_mode=int(max_rows_per_mode), page_size=256)
    wanted = {core.norm_code(x) for x in passenger_codes}
    expected_all = set().union(*EXPECTED_MODE_DSEGS.values())
    if wanted != expected_all:
        raise SupplyContractError("FULL_GEOMETRY_EXACT_12_DSEG_SCOPE_REQUIRED")
    path_cfg = {"path_export_dsegs": list(passenger_codes)}
    dsrows = rt.selected_passenger_dsegs(visum, path_cfg)
    by_code = {r["norm_code"]: r for r in dsrows}
    if set(by_code) != expected_all:
        raise SupplyContractError("FULL_GEOMETRY_LIVE_DSEG_SCOPE_MISMATCH")
    groups = {mode: sorted(EXPECTED_MODE_DSEGS[mode]) for mode in ("C", "C_NOT")}
    db_path = Path(run_dir) / "15T_GEOMETRY_REFERENCE.sqlite"
    if db_path.exists():
        db_path.unlink()
    db = _open_db(db_path)
    result = {"schema": "R1_15A2_FULL_PATHLINK_IDENTITY_V239", "modes": {},
              "full_geometry_identity_proven": False, "writes_to_visum": False,
              "assignment_executed": False, "database": db_path.name}
    try:
        for mode in ("C", "C_NOT"):
            rep = REPRESENTATIVE[mode]
            if rep not in groups[mode]:
                raise SupplyContractError("FULL_GEOMETRY_REPRESENTATIVE_SCOPE")
            control.checkpoint("FULL_GEOMETRY_MODE_START", force=True, mode=mode, representative=rep)
            ref = build_reference(visum, db, mode, by_code[rep]["code"], settings, control)
            comparisons = []
            for code in groups[mode]:
                if code == rep:
                    comparisons.append({"mode": mode, "dseg_code": code,
                                        "routes": ref["routes"], "edge_children": ref["edge_children"],
                                        "reference_routes": ref["routes"], "mismatch_count": 0,
                                        "first_mismatches": [], "passes": True, "status": "REFERENCE"})
                    continue
                control.checkpoint("FULL_GEOMETRY_DSEG_START", force=True, mode=mode, dseg_code=code)
                cmp = compare_dseg(visum, db, mode, by_code[code]["code"], settings, control)
                comparisons.append(cmp)
                if not cmp["passes"]:
                    result["modes"][mode] = {"reference": ref, "comparisons": comparisons,
                                             "passes": False}
                    result["status"] = "FULL_GEOMETRY_IDENTITY_FAILED"
                    return result
            result["modes"][mode] = {"reference": ref, "comparisons": comparisons, "passes": True}
        result["full_geometry_identity_proven"] = True
        result["status"] = "FULL_GEOMETRY_IDENTITY_PROVEN"
        return result
    finally:
        db.commit()
        db.close()
        atomic_json(Path(run_dir) / "15T_FULL_GEOMETRY_IDENTITY.json", result)
