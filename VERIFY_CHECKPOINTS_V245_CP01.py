# -*- coding: utf-8 -*-
"""Read-only audit of locally accepted R1 15A2 calibration checkpoints.

Run on the Windows/Visum host after stopping calibration:
    python VERIFY_CHECKPOINTS_V245_CP01.py ".../CALIBRATION"

No COM, no model writes, no directory creation, no checkpoint promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_checkpoint_state(run_directory):
    root = Path(run_directory).resolve()
    store = (root / "CHECKPOINTS").resolve()
    issues = []
    rows = []
    canonical = None

    def read_record(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            issues.append("UNREADABLE_RECORD:%s:%s" % (path.name, type(exc).__name__))
            return None

    def check_record(path, rec):
        if not isinstance(rec, dict):
            issues.append("INVALID_POINTER_RECORD:" + path.name)
            return None
        try:
            n = rec["accepted_count"]
            slot = rec["slot"]
            cp = rec["checkpoint"]
            filename = cp["path"]
            expected = cp["sha256"]
            if type(n) is not int or n < 0 or slot not in ("A", "B") or not isinstance(filename, str):
                raise ValueError("invalid accepted count/slot/path")
            if slot != ("A" if n % 2 else "B") or not isinstance(expected, str) or not SHA256.fullmatch(expected):
                raise ValueError("invalid checkpoint identity/hash")
            file = Path(filename).resolve()
            if file.parent != store or not file.name.startswith("ACCEPTED_%s_%04d_" % (slot, n)) or file.suffix.lower() != ".ver":
                raise ValueError("checkpoint path outside expected slot/number namespace")
            if not file.is_file() or file.stat().st_size <= 0:
                raise ValueError("checkpoint missing/empty")
            actual = _sha256(file)
            if actual != expected:
                raise ValueError("checkpoint sha256 mismatch")
            result = {"pointer": path.name, "accepted_count": n, "slot": slot,
                      "file": file.name, "size_bytes": file.stat().st_size, "sha256": actual}
            rows.append(result)
            return result
        except (KeyError, TypeError, ValueError, OSError) as exc:
            issues.append("INVALID_POINTER_OR_PAYLOAD:%s:%s" % (path.name, str(exc)))
            return None

    last_file = root / "LATEST_ACCEPTED_CHECKPOINT.json"
    if not last_file.is_file():
        issues.append("CANONICAL_LATEST_POINTER_MISSING")
    else:
        rec = read_record(last_file)
        if rec is not None:
            canonical = check_record(last_file, rec)
    for slot in ("A", "B"):
        slot_file = store / ("SLOT_%s.json" % slot)
        if slot_file.exists():
            rec = read_record(slot_file)
            if rec is not None:
                check_record(slot_file, rec)
    if canonical is not None:
        matching = [r for r in rows if r["pointer"] == "SLOT_%s.json" % canonical["slot"]]
        if len(matching) != 1 or matching[0]["sha256"] != canonical["sha256"] or matching[0]["accepted_count"] != canonical["accepted_count"]:
            issues.append("CANONICAL_SLOT_POINTER_MISMATCH")
        for rec in rows:
            if rec["accepted_count"] > canonical["accepted_count"]:
                issues.append("SUPPLEMENTARY_SLOT_AHEAD_OF_CANONICAL:" + rec["pointer"])
    referenced = {r["file"] for r in rows}
    orphans = [p.name for p in sorted(store.glob("ACCEPTED_*.ver")) if p.name not in referenced] if store.is_dir() else []
    return {"schema":"R1_15A2_V245_CP01_READONLY_CHECKPOINT_AUDIT",
            "status":"PASS" if not issues else "FAIL", "calibration_directory":str(root),
            "canonical_latest":canonical, "verified_pointer_count":len(rows),
            "issues":issues, "orphan_files_not_deleted":orphans,
            "model_writes":False, "com_calls":False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory",help="Path to the CALIBRATION or SUPPLY_ROUTE_CHOICE directory")
    args=parser.parse_args(argv)
    report=verify_checkpoint_state(args.run_directory)
    print(json.dumps(report,indent=2,ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
