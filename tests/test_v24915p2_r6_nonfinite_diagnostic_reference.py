import copy
import math

from r1_15a2_candidate_readback_bundle_v24915p2 import (
    CandidateReadbackManager,
    diagnostic_reference_hash,
)
from r1_15a2_supply import canonical_hash


def _snapshot():
    payload = {
        "addval1": {"1|1|2": 0.0},
        "addval_hash": "a" * 64,
        "fixed_link_hash": "b" * 64,
        "matrices": [],
        "matrix_hash": "c" * 64,
        "dseg_map": {},
        "dseg_hash": "d" * 64,
        "generation_values": {},
        "generation_hash": "e" * 64,
        "td_values": [],
        "td_hash": "f" * 64,
        "operations_hash": "0" * 64,
    }
    payload["state_hash"] = canonical_hash(payload)
    return payload


def _ready_manager():
    m = CandidateReadbackManager({"performance":{"v24915_perf2_candidate_readback_bundle":{"enabled": True}}}, visum_session_token="S", run_token="R")
    parent = _snapshot()["state_hash"]
    m.begin_candidate(
        accepted_parent_state_hash=parent,
        block="GENERATION",
        candidate_write_signature="1" * 64,
        parameter_evidence={"rows": 1},
        baseline_profile_rows=[],
    )
    m.mark_assignment_started(reason="TEST")
    m.mark_assignment_completed({"gap": 0.0})
    m.capture(snapshot_factory=_snapshot)
    return m


def test_finite_diagnostic_hash_is_backward_identical():
    diag = {"d12": {"rows": [1, 2]}, "d11": {"x": 2.5}, "signals": {"y": 3}}
    assert diagnostic_reference_hash(diag) == canonical_hash(diag)


def test_nonfinite_diagnostics_are_hashable_and_input_is_unchanged():
    diag = {
        "d12": {"rows": [{"metric": float("inf")}]},
        "d11": {"summary": {"low": float("-inf"), "missing": float("nan")}},
        "signals": {"weighted_objective": float("inf")},
    }
    original = copy.deepcopy(diag)
    h1 = diagnostic_reference_hash(diag)
    h2 = diagnostic_reference_hash(diag)
    assert len(h1) == 64
    assert h1 == h2
    assert math.isinf(diag["d12"]["rows"][0]["metric"])
    assert math.isinf(diag["d11"]["summary"]["low"])
    assert math.isnan(diag["d11"]["summary"]["missing"])
    assert math.isinf(original["signals"]["weighted_objective"])


def test_positive_negative_infinity_and_nan_have_distinct_evidence_hashes():
    hashes = {
        diagnostic_reference_hash({"x": float("inf")}),
        diagnostic_reference_hash({"x": float("-inf")}),
        diagnostic_reference_hash({"x": float("nan")}),
        diagnostic_reference_hash({"x": None}),
    }
    assert len(hashes) == 4


def test_attach_diagnostics_accepts_live_nonfinite_sentinels_and_rebinds_bundle():
    m = _ready_manager()
    diag = {
        "d12": {"rows": [{"geh": 10.0}]},
        "d11": {"summary": {"weighted_objective": float("inf")}},
        "signals": {"components": [{"objective": float("inf")}]},
    }
    m.attach_diagnostics(diag)
    current = m.require_current()
    ref = current.diagnostics_reference
    assert ref["diagnostics_payload_hash"] == diagnostic_reference_hash(diag)
    assert ref["d11_hash"] == diagnostic_reference_hash(diag["d11"])
    assert ref["signals_hash"] == diagnostic_reference_hash(diag["signals"])
    assert current.payload_hash


def test_unserializable_perf2_reference_falls_back_without_failing_diagnostics():
    class Unsupported:
        pass

    m = _ready_manager()
    before = m.current
    m.attach_diagnostics({"d12": {}, "d11": {}, "signals": {"x": Unsupported()}})
    assert m.pending_diagnostics_reference is None
    assert m.current is before
    assert m.telemetry_counts["BUNDLE_FALLBACK"] >= 1


def test_live_adapter_diagnostics_path_does_not_fail_on_infinity(monkeypatch, tmp_path):
    import r1_15a2_trial_adapter_v24915p2 as p2

    class BareAdapter(p2.VisumAdapter):
        def __init__(self):
            self.cfg = {
                "performance": {
                    "v24915_perf2_candidate_readback_bundle": {
                        "enabled": True,
                        "shadow_parity_mode": True,
                        "fallback_to_legacy": True,
                        "require_exact_snapshot_parity": True,
                    },
                    "v24915_perf1": {"phase_specific_procseq": {"enabled": False}},
                }
            }
            self.telemetry = None
            self.readback_manager = CandidateReadbackManager(
                self.cfg, visum_session_token="S", run_token="R")

    diag = {
        "d12": {"rows": [{"model": 0.0}]},
        "d11": {"summary": {"weighted_objective": float("inf")}},
        "signals": {"components": [{"objective": float("inf")}]},
    }

    def parent_diagnostics(self, folder, label="CURRENT"):
        return copy.deepcopy(diag)

    monkeypatch.setattr(p2._PERF1, "diagnostics", parent_diagnostics)
    adapter = BareAdapter()
    result = adapter.diagnostics(tmp_path, "BASELINE")
    assert math.isinf(result["d11"]["summary"]["weighted_objective"])
    assert adapter.readback_manager.pending_diagnostics_reference is not None
    assert adapter.readback_manager.pending_diagnostics_reference["diagnostics_payload_hash"] == diagnostic_reference_hash(diag)
