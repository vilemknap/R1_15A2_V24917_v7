"""MOBILITYFIX1 regressions: legitimate structural zeros and failure evidence."""
import json
from pathlib import Path

import pytest

import r1_15a2_mobility_guard_v24917 as mg
from r1_15a2_trial_adapter_v24917 import VisumAdapter


def row(z, fp, mult):
    d = {"zone_no": z, "NOT_ZAHR": 1.0, "ADD_PROD_W": mult, "ADD_PROD_S": 1.0}
    for fam in ("WORK", "SERVICE"):
        for attr in mg.FP_ATTRS[fam]:
            d[attr] = fp if fam == "WORK" else 2.0
    return d


def test_domestic_zero_mass_and_zero_coefficient_excluded_from_ratio():
    rows = [row(1, 1.0, 1.2), row(2, 0.0, 0.0)]
    prod = mg.zone_productions(rows, "WORK")
    assert set(prod) == {1}
    assert mg.ratio(prod) == pytest.approx(1.2)
    proposal = [{"zone_no": 1, "family": "WORK", "role": "PROD", "log_step": 0.0}]
    _, proof = mg.guard(proposal, rows, {"enabled": True, "lo": .75, "hi": 1.25})
    assert proof["passes"]
    assert proof["families"]["WORK"]["zones"] == 1


def test_positive_mass_with_zero_multiplier_still_fail_closed():
    with pytest.raises(ValueError, match="INVALID_MULTIPLIER:WORK:1"):
        mg.zone_productions([row(1, 1.0, 0.0)], "WORK")


def test_missing_even_if_zero_mass_is_not_silently_ignored():
    r = row(1, 0.0, 0.0)
    del r[mg.FP_ATTRS["WORK"][0]]
    with pytest.raises(KeyError, match="FP_ATTRIBUTE_MISSING:WORK:1"):
        mg.zone_productions([r], "WORK")


def test_nonfinite_coefficients_still_fail_even_with_zero_mass():
    with pytest.raises(ValueError, match="NONFINITE_MULTIPLIER:WORK:1"):
        mg.zone_productions([row(1, 0.0, float("nan"))], "WORK")


def test_blocked_generation_keeps_original_stage_and_cause(tmp_path):
    adapter = VisumAdapter.__new__(VisumAdapter)
    context = {"projection": None, "v24917_ls": {}, "v24917_bd": {}}
    result = adapter._blocked_generation(context, tmp_path, ValueError("INVALID_EXAMPLE"),
                                         stage="FLOWBUNDLE_MASK")
    assert result["v24917"]["status"] == "BLOCKED_MOBILITY_DATA"
    assert result["v24917"]["failure_stage"] == "FLOWBUNDLE_MASK"
    assert "ValueError:INVALID_EXAMPLE" == result["v24917"]["error"]
    assert "v24917_ls" not in result
    evidence = json.loads((tmp_path / "V24917_MOBILITY_BLOCKED.json").read_text())
    assert evidence["failure_stage"] == "FLOWBUNDLE_MASK"
