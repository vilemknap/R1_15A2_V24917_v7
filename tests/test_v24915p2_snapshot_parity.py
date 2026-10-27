# -*- coding: utf-8 -*-
"""Exact semantic parity and synthetic read-count benchmark for PERF2."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Mapping

import pytest

from r1_15a2_candidate_readback_bundle_v24915p2 import CandidateReadbackManager
from r1_15a2_supply import canonical_hash


def _cfg() -> Dict[str, Any]:
    return {
        "performance": {
            "v24915_perf2_candidate_readback_bundle": {
                "enabled": True,
                "shadow_parity_mode": True,
                "fallback_to_legacy": True,
                "require_exact_snapshot_parity": True,
            }
        }
    }


@dataclass
class CountingMatrix:
    matrix_no: int
    values: tuple[tuple[float, ...], ...]
    get_values_calls: int = 0

    def GetValues(self):
        self.get_values_calls += 1
        return [list(row) for row in self.values]


class SyntheticLegacyReader:
    """Plain-Python analogue of the legacy VisumAdapter.snapshot read set."""

    def __init__(self) -> None:
        self.links = {
            "1:10:20": {"addval1": 0.0, "fixed": {"length": 1.2, "type_no": 10}},
            "2:20:10": {"addval1": 0.5, "fixed": {"length": 1.2, "type_no": 10}},
        }
        self.dseg_map = {"NATIVE_CW": 101, "NATIVE_CS": 102}
        self.matrices = {
            101: CountingMatrix(101, ((0.0, 2.0), (1.0, 0.0))),
            102: CountingMatrix(102, ((0.0, 3.0), (4.0, 0.0))),
        }
        self.generation = {
            "ADD_PROD_W": {"1": 1.0, "2": 1.1},
            "ADD_ATT_W": {"1": 0.9, "2": 1.0},
        }
        self.td = [
            {"component": "WORK_E_C", "current_b": 0.0, "current_c": -0.1, "status": "OK"},
            {"component": "SERV_E_C", "current_b": 0.2, "current_c": -0.2, "status": "OK"},
        ]
        self.operations = [
            {"no": 1, "type": 45, "active": 1, "name": "TG"},
            {"no": 2, "type": 46, "active": 1, "name": "TD"},
            {"no": 3, "type": 101, "active": 1, "name": "PrT"},
        ]
        self.snapshot_calls = 0
        self.link_reads = 0
        self.dseg_reads = 0
        self.generation_reads = 0
        self.td_reads = 0
        self.operation_reads = 0

    def snapshot(self) -> Dict[str, Any]:
        self.snapshot_calls += 1
        self.link_reads += 1
        addval = {key: row["addval1"] for key, row in sorted(self.links.items())}
        fixed = [row["fixed"] for _key, row in sorted(self.links.items())]
        self.dseg_reads += 1
        dseg_map = copy.deepcopy(self.dseg_map)
        matrix_rows = []
        for no, matrix in sorted(self.matrices.items()):
            values = matrix.GetValues()
            matrix_rows.append({
                "matrix_no": no,
                "rows": len(values),
                "cols": len(values[0]),
                "sha256_float64_le": canonical_hash(values),
            })
        self.generation_reads += 1
        generation = copy.deepcopy(self.generation)
        self.td_reads += 1
        td = copy.deepcopy(sorted(self.td, key=lambda row: row["component"]))
        self.operation_reads += 1
        operations = copy.deepcopy(self.operations)
        result = {
            "addval1": addval,
            "addval_hash": canonical_hash(addval),
            "fixed_link_hash": canonical_hash(fixed),
            "matrices": matrix_rows,
            "matrix_hash": canonical_hash(matrix_rows),
            "dseg_map": dseg_map,
            "dseg_hash": canonical_hash(dseg_map),
            "generation_values": generation,
            "generation_hash": canonical_hash(generation),
            "td_values": td,
            "td_hash": canonical_hash(td),
            "operations_hash": canonical_hash(operations),
        }
        result["state_hash"] = canonical_hash(result)
        return result

    @property
    def matrix_getvalues_calls(self) -> int:
        return sum(matrix.get_values_calls for matrix in self.matrices.values())


def _ready_manager(block: str) -> CandidateReadbackManager:
    manager = CandidateReadbackManager(
        _cfg(), visum_session_token="VISUM-SESSION", run_token="RUN-TOKEN")
    manager.begin_candidate(
        accepted_parent_state_hash="a" * 64,
        block=block,
        candidate_write_signature=canonical_hash({"block": block, "candidate": 1}),
        parameter_evidence={"block": block})
    manager.mark_assignment_started(
        reason="PROCEDURES_EXECUTE:" + block,
        procedure_plan={"mode": "PHASE_SPECIFIC", "block": block})
    manager.mark_assignment_completed({"gap": 1.0e-5, "block": block})
    return manager


@pytest.mark.parametrize("block", ["GENERATION", "TD_FINECDF", "SUPPLY_ADDVAL1"])
def test_legacy_and_bundle_snapshot_payloads_are_exact_for_all_blocks(block):
    reader = SyntheticLegacyReader()
    manager = _ready_manager(block)
    legacy = reader.snapshot()
    bundle = manager.capture(snapshot_factory=lambda: copy.deepcopy(legacy))
    assert bundle.snapshot() == legacy
    assert manager.snapshot_from_current() == legacy
    assert manager.snapshot_from_current()["state_hash"] == legacy["state_hash"]
    for key in (
        "state_hash", "addval_hash", "fixed_link_hash", "matrix_hash",
        "dseg_hash", "generation_hash", "td_hash", "operations_hash",
    ):
        assert bundle.semantic_snapshot_payload[key] == legacy[key]


def test_bundle_reuses_one_matrix_read_set_for_three_snapshot_consumers():
    legacy_reader = SyntheticLegacyReader()
    legacy_payloads = [legacy_reader.snapshot() for _ in range(3)]
    assert legacy_payloads[0] == legacy_payloads[1] == legacy_payloads[2]
    legacy_getvalues = legacy_reader.matrix_getvalues_calls

    perf_reader = SyntheticLegacyReader()
    manager = _ready_manager("GENERATION")
    bundle = manager.capture(snapshot_factory=perf_reader.snapshot)
    optimized_payloads = [manager.snapshot_from_current() for _ in range(3)]

    assert optimized_payloads[0] == optimized_payloads[1] == optimized_payloads[2]
    assert optimized_payloads[0] == bundle.snapshot()
    assert optimized_payloads[0] == legacy_payloads[0]
    assert perf_reader.matrix_getvalues_calls == len(perf_reader.matrices)
    assert legacy_getvalues == 3 * len(legacy_reader.matrices)
    assert perf_reader.matrix_getvalues_calls < legacy_getvalues
    telemetry = manager.telemetry_snapshot()
    assert telemetry["counts"]["MATRIX_GETVALUES_COUNT"] == len(perf_reader.matrices)
    assert telemetry["counts"]["SNAPSHOT_FROM_BUNDLE"] == 3
    assert telemetry["MODEL_MUTATION_EPOCH"] == manager.mutation_epoch
    assert telemetry["ASSIGNMENT_EPOCH"] == manager.assignment_epoch


def test_bundle_returns_defensive_copies_not_mutable_authority():
    reader = SyntheticLegacyReader()
    manager = _ready_manager("TD_FINECDF")
    bundle = manager.capture(snapshot_factory=reader.snapshot)
    first = manager.snapshot_from_current()
    first["generation_values"]["ADD_PROD_W"]["1"] = 999.0
    second = manager.snapshot_from_current()
    assert second == bundle.snapshot()
    assert second["generation_values"]["ADD_PROD_W"]["1"] == 1.0
