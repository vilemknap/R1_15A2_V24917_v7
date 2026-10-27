# -*- coding: utf-8 -*-
"""GENFIX1 live parent guard: reject drift and retain bounded forensic evidence."""
import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest

import r1_15a2_generation_state_v24917 as guard
from r1_15a2_supply import SupplyContractError


def state():
    return {
        "state_hash": "parent", "matrix_hash": "matrix-old", "generation_hash": "generation-old",
        "td_hash": "td-old", "operations_hash": "operations-old", "dseg_hash": "dseg-old",
        "fixed_link_hash": "fixed", "addval_hash": "addval-old", "addval1": {"1|1|2": 0.0},
        "matrices": [{"matrix_no": 9101, "rows": 2, "cols": 2, "sha256_float64_le": "od-old"}],
        "generation_values": {"ADD_PROD_W": {"1": 1.0, "2": 1.5}},
        "td_values": [{"component": "WORK_E_C", "current_b": -0.1, "current_c": -0.2, "status": "OK"}],
        "dseg_map": {"NATIVE_CW": 9101},
        "v24917_iz_penalty": {"1": 0.0}, "v24917_ic_base_sha": "base-old",
    }


def read(folder, name):
    return json.loads((folder / name).read_text(encoding="utf-8"))


def test_exact_parent_passes_uses_fallback_and_never_changes_expected(tmp_path):
    expected = state()
    before = copy.deepcopy(expected)
    current = copy.deepcopy(expected)
    adapter = SimpleNamespace(snapshot=lambda: current, generation_guard_snapshot=None)
    assert guard.require_parent(adapter, expected, tmp_path, phase="BEFORE_DESIGN") is current
    assert expected == before
    check = read(tmp_path, "GENERATION_PARENT_CHECK.json")
    assert check["passes"] and check["status"] == "EXACT_PARENT_MATCH"
    assert check["snapshot_source"] == "snapshot" and check["parent_rebased"] is False
    assert not (tmp_path / "GENERATION_PARENT_DIFF.json").exists()


@pytest.mark.parametrize("domain,field,detail", [
    ("matrix", "matrices", "matrices"),
    ("generation", "generation_values", "generation_values"),
    ("td", "td_values", "td_values"),
    ("operations", "operations_hash", None),
    ("dseg", "dseg_map", "dseg_map"),
    ("addval", "addval1", "addval1"),
    ("extension", "v24917_iz_penalty", "extensions"),
    ("base_extension", "v24917_ic_base_sha", "extensions"),
])
def test_true_mutations_rejected_even_if_state_hash_is_unchanged(tmp_path, domain, field, detail):
    expected = state()
    before = copy.deepcopy(expected)
    current = copy.deepcopy(expected)
    if domain == "matrix":
        current["matrices"][0]["sha256_float64_le"] = "od-new"
    elif domain == "generation":
        current["generation_values"]["ADD_PROD_W"]["2"] = 1.6
    elif domain == "td":
        current["td_values"][0]["current_c"] = -0.25
    elif domain == "operations":
        current["operations_hash"] = "operations-new"
    elif domain == "dseg":
        current["dseg_map"]["NATIVE_CW"] = 9102
    elif domain == "addval":
        current["addval1"]["1|1|2"] = 0.1
    elif domain == "extension":
        current["v24917_iz_penalty"]["1"] = 0.1
    else:
        current["v24917_ic_base_sha"] = "base-new"
    adapter = SimpleNamespace(snapshot=lambda: current)
    with pytest.raises(SupplyContractError, match="^V242_GENERATION_TRIAL_PARENT_CHANGED$"):
        guard.require_parent(adapter, expected, tmp_path, phase="AFTER_DESIGN")
    assert expected == before
    diff = read(tmp_path, "GENERATION_PARENT_DIFF.json")
    assert diff["changed_top_level_keys"] == [field]
    assert diff["expected_state_hash"] == diff["current_state_hash"] == "parent"
    assert not diff["passes"] and diff["parent_rebased"] is False
    if detail:
        assert len(diff[detail]["sample"]) == 1
    if domain == "matrix":
        row = diff["matrices"]["sample"][0]
        assert row["before"]["sha256_float64_le"] == "od-old"
        assert row["current"]["sha256_float64_le"] == "od-new"
    if domain == "operations":
        assert diff["changed_hash_domains"] == ["operations_hash"]
        assert diff["operation_inventory"]["status"] == "UNAVAILABLE_NO_VISUM"


def test_optional_live_api_wins_over_stale_cached_snapshot(tmp_path):
    expected, current = state(), state()
    current["generation_values"]["ADD_PROD_W"]["1"] = 2.0
    calls = []

    def cached():
        calls.append("cached")
        return expected

    def live():
        calls.append("live")
        return current

    adapter = SimpleNamespace(snapshot=cached, generation_guard_snapshot=live)
    with pytest.raises(SupplyContractError, match="PARENT_CHANGED"):
        guard.require_parent(adapter, expected, tmp_path, phase="BEFORE_APPLY")
    assert calls == ["live"]
    assert read(tmp_path, "GENERATION_PARENT_CHECK.json")["snapshot_source"] == "generation_guard_snapshot"


def test_generation_samples_are_bounded_but_total_count_is_exact(tmp_path):
    expected, current = state(), state()
    n = guard.SAMPLE_LIMIT + 37
    expected["generation_values"] = {"ADD_PROD_W": {str(i): 1.0 for i in range(n)}}
    current["generation_values"] = {"ADD_PROD_W": {str(i): 1.01 for i in range(n)}}
    with pytest.raises(SupplyContractError):
        guard.require_parent(SimpleNamespace(snapshot=lambda: current), expected, tmp_path, phase="AFTER_DESIGN")
    part = read(tmp_path, "GENERATION_PARENT_DIFF.json")["generation_values"]
    assert part["changed_value_count"] == n and part["truncated"] is True
    assert len(part["sample"]) == guard.SAMPLE_LIMIT
    assert part["changed_attributes"] == ["ADD_PROD_W"]


def test_added_removed_values_and_same_hash_new_extension_are_reported(tmp_path):
    expected, current = state(), state()
    del current["generation_values"]["ADD_PROD_W"]["1"]
    current["generation_values"]["ADD_PROD_W"]["3"] = 1.25
    current["new_extension"] = {"x": True}
    with pytest.raises(SupplyContractError):
        guard.require_parent(SimpleNamespace(snapshot=lambda: current), expected, tmp_path, phase="AFTER_DESIGN")
    diff = read(tmp_path, "GENERATION_PARENT_DIFF.json")
    by_zone = {row["zone_no"]: row for row in diff["generation_values"]["sample"]}
    assert not by_zone["1"]["current_present"] and by_zone["1"]["before_present"]
    assert not by_zone["3"]["before_present"] and by_zone["3"]["current_present"]
    assert diff["extensions"]["sample"][0]["key"] == "new_extension"


def test_read_failure_is_audited_and_original_exception_reraised(tmp_path):
    error = RuntimeError("COM disconnected")

    def read_live():
        raise error

    with pytest.raises(RuntimeError) as caught:
        guard.require_parent(SimpleNamespace(snapshot=read_live), state(), tmp_path, phase="BEFORE_DESIGN")
    assert caught.value is error
    check = read(tmp_path, "GENERATION_PARENT_CHECK.json")
    assert check["status"] == "SNAPSHOT_READ_FAILED"
    assert check["error_type"] == "RuntimeError" and check["error"] == "COM disconnected"


def test_audit_write_failure_does_not_replace_primary_mismatch(tmp_path, monkeypatch):
    current = state()
    current["operations_hash"] = "changed"

    def fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(guard, "atomic_json", fail_write)
    with pytest.raises(SupplyContractError, match="^V242_GENERATION_TRIAL_PARENT_CHANGED$") as caught:
        guard.require_parent(SimpleNamespace(snapshot=lambda: current), state(), tmp_path, phase="AFTER_DESIGN")
    assert "disk full" in caught.value.generation_parent_audit_error


def test_audit_write_failure_does_not_replace_snapshot_read_error(tmp_path, monkeypatch):
    primary = RuntimeError("COM failed")

    def reader():
        raise primary

    def writer(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(guard, "atomic_json", writer)
    with pytest.raises(RuntimeError) as caught:
        guard.require_parent(SimpleNamespace(snapshot=reader), state(), tmp_path, phase="BEFORE_DESIGN")
    assert caught.value is primary
    assert "disk full" in primary.generation_parent_audit_error


def test_operation_inventory_current_only_and_read_errors_do_not_mask_mismatch(tmp_path, monkeypatch):
    import r1_15a2_com_compat as com
    current = state()
    current["operations_hash"] = "changed"
    adapter = SimpleNamespace(snapshot=lambda: current, visum=object())
    monkeypatch.setattr(com, "operation_rows", lambda v: [
        {"no": 1, "type": 45, "active": 0, "comment": "TG", "object": object()}])
    with pytest.raises(SupplyContractError):
        guard.require_parent(adapter, state(), tmp_path / "ok", phase="AFTER_DESIGN")
    view = read(tmp_path / "ok", "GENERATION_PARENT_DIFF.json")["operation_inventory"]
    assert view["view"] == "CURRENT_ONLY" and view["before_inventory_available"] is False
    assert view["sample"][0]["active"] == 0 and "object" not in view["sample"][0]

    def fail_inventory(v):
        raise RuntimeError("COM rejected inventory")

    monkeypatch.setattr(com, "operation_rows", fail_inventory)
    with pytest.raises(SupplyContractError, match="PARENT_CHANGED"):
        guard.require_parent(adapter, state(), tmp_path / "error", phase="AFTER_DESIGN")
    view = read(tmp_path / "error", "GENERATION_PARENT_DIFF.json")["operation_inventory"]
    assert view["status"] == "READ_FAILED" and "COM rejected" in view["error"]


def test_numpy_scalars_are_safe_and_large_matrix_values_are_never_dumped(tmp_path):
    expected, current = state(), state()
    current["generation_values"]["ADD_PROD_W"]["1"] = np.float64(1.1)
    current["matrices"][0]["sha256_float64_le"] = "new"
    current["matrices"][0]["values"] = [[999999.0] * 300] * 300
    current["scalar_extension"] = {"flag": np.bool_(True), "number": np.int64(4)}
    with pytest.raises(SupplyContractError):
        guard.require_parent(SimpleNamespace(snapshot=lambda: current), expected, tmp_path, phase="AFTER_DESIGN")
    text = (tmp_path / "GENERATION_PARENT_DIFF.json").read_text(encoding="utf-8")
    diff = json.loads(text)
    assert "999999" not in text
    assert len(text) < 12000
    assert diff["generation_values"]["sample"][0]["current"] == 1.1
    assert diff["extensions"]["sample"][0]["current"] == {"flag": True, "number": 4}

