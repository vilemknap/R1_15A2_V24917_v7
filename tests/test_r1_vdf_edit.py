# -*- coding: utf-8 -*-
"""R1_VDF_EDIT.py: VDF 7 capacity factor edit on the real procedure XML (fake Visum)."""
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XML = (ROOT / "tests" / "data" / "R1_PROCEDURE_SEQUENCE_20261016.xml").read_text(encoding="utf-8")
M = runpy.run_path(str(ROOT / "R1_VDF_EDIT.py"), run_name="__r1_test__")


class FakeProcedures:
    def __init__(self, xml, corrupt=False, no_options=False):
        self.xml = xml
        self.corrupt = corrupt
        self.loaded = []
        if no_options:
            self.OpenXmlWithOptions = None

    def SaveXml(self, path):
        Path(path).write_text(self.xml, encoding="utf-8")

    def OpenXmlWithOptions(self, path, ops, funcs, mode=0):
        self._load(path, "OPTIONS")

    def Open(self, path):
        self._load(path, "FULL")

    def _load(self, path, how):
        text = Path(path).read_text(encoding="utf-8")
        if self.corrupt and "PROCEDURES_EDITED" in str(path):
            text = text.replace('NAME="D-2"', 'NAME="D-2X"')     # unrequested change
        self.xml = text
        self.loaded.append(how)


class FakeVisum:
    def __init__(self, **kw):
        self.Procedures = FakeProcedures(XML, **kw)


def vdf7(xml):
    return M["vdf_table"](xml)[("LINKVDFUNCTIONSPARAMETERS", 7)]


def test_current_values_match_expected():
    row = vdf7(XML)
    assert row["NAME"] == "I. - 3/4 pruh" and row["BPR_A"] == "0.35" and row["BPR_B"] == "3.5"
    assert row["CAPACITYFACTOR"] == "1"


def test_dry_run_writes_nothing(tmp_path):
    v = FakeVisum()
    status, out = M["run"](v, tmp_path, dry_run=True)
    assert status == "PASS_DRY_RUN_NOTHING_WRITTEN"
    assert v.Procedures.loaded == [] and vdf7(v.Procedures.xml)["CAPACITYFACTOR"] == "1"
    assert vdf7((out / "PROCEDURES_EDITED.xml").read_text(encoding="utf-8"))["CAPACITYFACTOR"] == "1.8"


def test_apply_changes_only_vdf7_capacity(tmp_path):
    v = FakeVisum()
    status, out = M["run"](v, tmp_path, dry_run=False)
    assert status == "PASS_APPLIED_NOT_SAVED", (out / "00_STATUS.txt").read_text()
    assert v.Procedures.loaded == ["OPTIONS"]
    before, after = M["vdf_table"](XML), M["vdf_table"](v.Procedures.xml)
    changed = [(k, a) for k in before for a in before[k] if before[k][a] != after[k][a]]
    assert changed == [(("LINKVDFUNCTIONSPARAMETERS", 7), "CAPACITYFACTOR")]
    assert len(v.Procedures.xml) == len(XML) + 2                  # "1" -> "1.8", rest byte-identical
    status2, _ = M["run"](v, tmp_path, dry_run=False)
    assert status2 == "PASS_ALREADY_APPLIED_NOTHING_WRITTEN"


def test_unrequested_change_is_rolled_back(tmp_path):
    v = FakeVisum(corrupt=True)
    status, out = M["run"](v, tmp_path, dry_run=False)
    assert status == "FAILED_ROLLED_BACK"
    assert v.Procedures.xml == XML


def test_precheck_refuses_unexpected_model(tmp_path):
    v = FakeVisum()
    v.Procedures.xml = XML.replace('BPR_A="0.35" BPR_B="3.5"', 'BPR_A="0.5" BPR_B="3.5"')
    status, _ = M["run"](v, tmp_path, dry_run=False)
    assert status == "FAILED_PRECHECK_NOTHING_WRITTEN" and v.Procedures.loaded == []


def test_fallback_full_open(tmp_path):
    v = FakeVisum(no_options=True)
    status, _ = M["run"](v, tmp_path, dry_run=False)
    assert status == "PASS_APPLIED_NOT_SAVED" and v.Procedures.loaded == ["FULL"]
