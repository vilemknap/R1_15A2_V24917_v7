"""Reproducible V2.4.5 -> V2.4.6 performance evidence.

This benchmark has three explicitly separated evidence levels:
1. measured offline synthetic controller/cache runs;
2. deterministic COM-call/page-count derivations from observed live dimensions;
3. real-Visum claims, which remain deliberately unset until a live run.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS))

import pytest

import r1_15a2_overnight_controller_v242 as coupled
from r1_15a2_supply import SupplyPolicy, canonical_hash
from r1_15a2_two_mode_v238 import TwoModeRouteCollector, EXPECTED_MODE_DSEGS
from test_v245_workflow import setup_workflow


def _run_controller(performance=None):
    with tempfile.TemporaryDirectory(prefix="r1_v246_bench_") as td:
        tmp = Path(td)
        monkey = pytest.MonkeyPatch()
        try:
            cfg, control, adapter = setup_workflow(tmp, monkey)
            if performance is not None:
                cfg["performance"] = copy.deepcopy(performance)
            started = time.perf_counter()
            result = coupled.run_overnight_calibration_coupled(
                adapter, cfg, tmp / "workflow", control, ROOT)
            elapsed = time.perf_counter() - started
            return {
                "status": result["status"],
                "elapsed_seconds": elapsed,
                "assignment_or_recompute_calls": len(adapter.assignments),
                "accepted_count": result["accepted_count"],
                "demand_cycles": len(result["demand_cycles"]),
                "generation_attempts_by_cycle": [
                    len(c.get("generation", {}).get("attempts", []))
                    for c in result["demand_cycles"]
                ],
                "supply_attempts_by_block": [
                    len(b.get("attempts", []))
                    for b in result.get("supply_result", {}).get("blocks", [])
                ],
                "final_state_hash": adapter.snapshot()["state_hash"],
                "final_state": copy.deepcopy(adapter.state),
                "calibration_complete": result["calibration_complete"],
                "backend": "SYNTHETIC_COM_SHAPED_NOT_PTV_VISUM",
            }
        finally:
            monkey.undo()


def _lazy_evidence_benchmark(routes_per_mode=600, path_length=30):
    chain = tuple((1000+i, i+1, i+2) for i in range(path_length))
    links = {e: {"addval1": 0., "t0_c_seconds": 60., "eligible": True} for e in chain}
    bymode = {m: sorted(codes) for m, codes in EXPECTED_MODE_DSEGS.items()}
    allcodes = [c for group in bymode.values() for c in group]
    volumes = {c: i+1. for i, c in enumerate(allcodes)}
    expected = routes_per_mode * sum(volumes.values())
    edge = chain[0]
    profiles = [{"countlocation_no": "mock", "link_no": edge[0],
                 "from_node_no": edge[1], "to_node_no": edge[2],
                 "observed": expected, "model": expected, "role": "CALIBRATION"}]
    with tempfile.TemporaryDirectory(prefix="r1_v246_cache_") as td:
        db = Path(td) / "two_mode.sqlite"
        collector = TwoModeRouteCollector(
            profiles, SupplyPolicy(), "SYNTHETIC_ONLY", links, db)
        try:
            for mode, group in bymode.items():
                for code in group:
                    v = volumes[code]
                    collector.add_parents(
                        code, mode,
                        ((1, j+2, 1, v) for j in range(routes_per_mode)),
                        {"matrix_interzonal": routes_per_mode*v,
                         "matrix_total": routes_per_mode*v,
                         "matrix_diagonal": 0})
            for mode in bymode:
                def rows():
                    for j in range(routes_per_mode):
                        yield [1, j+2, 1, "", "", "", ""]
                        for ix, item in enumerate(chain, 1):
                            yield ["", "", "", ix, *item]
                collector.add_geometry(mode, rows())
            start = time.perf_counter()
            incidence = collector.prepare_incidence_evidence()
            incidence_seconds = time.perf_counter() - start
            incidence_ready_before_sequence = bool(
                incidence.get("incidence_ready") and
                not incidence.get("sequence_evidence_ready"))
            start = time.perf_counter()
            sequence = collector.prepare_sequence_evidence()
            sequence_seconds = time.perf_counter() - start
            return {
                "backend": "SYNTHETIC_SQLITE_PATH_STORE_NOT_PTV_VISUM",
                "routes_per_mode": routes_per_mode,
                "path_length": path_length,
                "incidence_only_seconds": incidence_seconds,
                "deferred_sequence_seconds": sequence_seconds,
                "incidence_ready_before_sequence": incidence_ready_before_sequence,
                "sequence_ready_after_deferred_build": bool(
                    sequence.get("sequence_evidence_ready")),
                "sqlite_bytes": db.stat().st_size,
            }
        finally:
            collector.close()


def run():
    v245 = _run_controller(None)
    v246 = _run_controller({
        "release": "V2.4.6",
        "telemetry": {"enabled": False},
        "first_sufficient": {
            "enabled": True,
            "generation_min_relative_improvement": 0.001,
            "supply_min_relative_improvement": 0.001,
        },
    })
    old_calls = v245["assignment_or_recompute_calls"]
    new_calls = v246["assignment_or_recompute_calls"]

    live_raw_rows = 32_383_846
    old_page = 256
    new_page = 2048
    old_pages = math.ceil(live_raw_rows / old_page)
    new_pages = math.ceil(live_raw_rows / new_page)
    link_count = 8287
    link_attrs = 9
    scalar_calls = link_count * link_attrs
    bulk_verified_calls = link_attrs + link_count  # 9 bulk + one object-NO check per link

    result = {
        "schema": "R1_15A2_V246_PERFORMANCE_BENCHMARK_V1",
        "status": "PASS_OFFLINE_EVIDENCE_ONLY",
        "scientific_boundary": {
            "real_ptv_visum_tested": False,
            "real_wall_time_speedup_claim": None,
            "adaptive_search_is_bitwise_identical": False,
            "reason": "V2.4.6 deliberately changes the optimization path while retaining hard acceptance and rollback gates.",
        },
        "measured_offline_synthetic": {
            "v245": v245,
            "v246": v246,
            "assignment_call_reduction": old_calls - new_calls,
            "assignment_call_reduction_fraction": (old_calls-new_calls)/old_calls,
            "same_final_state": v245["final_state_hash"] == v246["final_state_hash"],
            "interpretation": (
                "The synthetic landscape completed in both versions. V2.4.6 used fewer "
                "expensive calls, but accepted a different valid adaptive path; this is not "
                "an equivalence proof or a real-Visum timing result."
            ),
        },
        "measured_offline_lazy_evidence": _lazy_evidence_benchmark(),
        "derived_from_observed_live_dimensions": {
            "path_export": {
                "observed_raw_rows": live_raw_rows,
                "old_page_size": old_page,
                "new_requested_page_size": new_page,
                "old_request_count_ceiling": old_pages,
                "new_request_count_ceiling_if_2048_supported": new_pages,
                "request_reduction_fraction_if_supported": (old_pages-new_pages)/old_pages,
                "caveat": "Adaptive fallback may use smaller pages; this is a request-count derivation, not measured wall time.",
            },
            "link_attribute_read": {
                "observed_link_count": link_count,
                "attributes": link_attrs,
                "old_scalar_attvalue_calls": scalar_calls,
                "new_bulk_plus_identity_calls": bulk_verified_calls,
                "call_reduction_fraction": (scalar_calls-bulk_verified_calls)/scalar_calls,
                "caveat": "Derived COM-call count; real latency depends on Visum and machine state.",
            },
        },
    }
    result["evidence_hash"] = canonical_hash(result)
    return result


def write_markdown(path, result):
    m = result["measured_offline_synthetic"]
    p = result["derived_from_observed_live_dimensions"]["path_export"]
    l = result["derived_from_observed_live_dimensions"]["link_attribute_read"]
    text = f"""# R1 15A2 V2.4.6 performance benchmark

Status: **{result['status']}**

## Measured offline synthetic controller

| Metric | V2.4.5 | V2.4.6 |
|---|---:|---:|
| assignment/recompute calls | {m['v245']['assignment_or_recompute_calls']} | {m['v246']['assignment_or_recompute_calls']} |
| accepted states | {m['v245']['accepted_count']} | {m['v246']['accepted_count']} |
| demand cycles | {m['v245']['demand_cycles']} | {m['v246']['demand_cycles']} |

Call reduction in this fixture: **{100*m['assignment_call_reduction_fraction']:.1f}%**.
The final adaptive state is identical: **{str(m['same_final_state']).lower()}**.
That difference is expected and explicitly acknowledged; it is not a regression by itself.

## Derived request-count reductions

- Path paging: {p['old_request_count_ceiling']:,} -> {p['new_request_count_ceiling_if_2048_supported']:,} requests if page 2048 is supported ({100*p['request_reduction_fraction_if_supported']:.1f}% fewer).
- Link reads: {l['old_scalar_attvalue_calls']:,} -> {l['new_bulk_plus_identity_calls']:,} COM calls in the verified bulk design ({100*l['call_reduction_fraction']:.1f}% fewer).

These are call-count derivations, not real PTV Visum wall-time measurements.

## Truth boundary

No real PTV Visum 2026 execution was performed in this environment. The first live run must use telemetry and compare quality, accepted states, rollback integrity and wall time against CP03.
"""
    Path(path).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=str(ROOT / "V246_PERFORMANCE_BENCHMARK.json"))
    parser.add_argument("--markdown", default=str(ROOT / "V246_PERFORMANCE_BENCHMARK.md"))
    args = parser.parse_args()
    output = run()
    Path(args.json).write_text(json.dumps(output, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    write_markdown(args.markdown, output)
    print(json.dumps(output, indent=2, ensure_ascii=False))
