"""Low-overhead append-only performance telemetry for R1 15A2 V2.4.6.

The telemetry is evidence only. It never changes acceptance, rollback, or model
state. Each span is written atomically after completion so a crash can only lose
the currently open span, not corrupt earlier records.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import json
import math
import os
import time


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class PerformanceTelemetry:
    def __init__(self, root, clock=time.monotonic):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.started = clock()
        self.events = []
        self.sequence = 0
        self._publish_summary()

    def _clean(self, value):
        if isinstance(value, dict):
            return {str(k): self._clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._clean(v) for v in value]
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, (str, int, bool)) or value is None:
            return value
        return str(value)

    def event(self, name, status="OK", duration_seconds=0.0, **details):
        self.sequence += 1
        row = {
            "sequence": self.sequence,
            "name": str(name),
            "status": str(status),
            "duration_seconds": round(float(duration_seconds), 6),
            "elapsed_seconds": round(float(self.clock() - self.started), 6),
            "timestamp": datetime.now().astimezone().isoformat(),
            "details": self._clean(details),
        }
        self.events.append(row)
        _atomic_json(self.root / ("EVENT_%06d.json" % self.sequence), row)
        self._publish_summary()
        return row

    @contextmanager
    def span(self, name, **details):
        before = self.clock()
        status = "OK"
        error = None
        try:
            yield
        except BaseException as exc:
            status = "ERROR"
            error = "%s: %s" % (type(exc).__name__, exc)
            raise
        finally:
            payload = dict(details)
            if error is not None:
                payload["error"] = error
            self.event(name, status=status, duration_seconds=self.clock() - before, **payload)

    def _publish_summary(self):
        totals = {}
        counts = {}
        failures = 0
        for row in self.events:
            name = row["name"]
            totals[name] = totals.get(name, 0.0) + float(row["duration_seconds"])
            counts[name] = counts.get(name, 0) + 1
            if row["status"] != "OK":
                failures += 1
        summary = {
            "schema": "R1_15A2_V246_PERFORMANCE_TELEMETRY_V1",
            "event_count": len(self.events),
            "error_count": failures,
            "elapsed_seconds": round(float(self.clock() - self.started), 6),
            "by_operation": [
                {"name": name, "calls": counts[name], "duration_seconds": round(totals[name], 6)}
                for name in sorted(totals)
            ],
        }
        _atomic_json(self.root / "SUMMARY.json", summary)
        return summary

    def finish(self):
        return self._publish_summary()


@contextmanager
def optional_span(owner, name, **details):
    telemetry = getattr(owner, "telemetry", None)
    if telemetry is None:
        yield
    else:
        with telemetry.span(name, **details):
            yield
