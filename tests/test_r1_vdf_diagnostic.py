# -*- coding: utf-8 -*-
"""R1_VDF_DIAGNOSTIC.py: read-only BPR/VDF diagnostic on a fake Visum network."""
import csv
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakeLinks:
    def __init__(self, rows):
        self.rows = rows

    def GetMultiAttValues(self, attr):
        if attr == "VOLVEH_TSYS(C_noT,AP)":
            raise RuntimeError("unknown attribute")
        return [(i + 1, r.get(attr, 0.0)) for i, r in enumerate(self.rows)]


class FakeVisum:
    def __init__(self, rows):
        self.Net = type("N", (), {"Links": FakeLinks(rows)})()


def test_vdf_diagnostic_profiles_and_classes(tmp_path):
    mod = runpy.run_path(str(ROOT / "R1_VDF_DIAGNOSTIC.py"), run_name="__r1_test__")
    roster = mod["read_roster"](ROOT)
    assert len(roster) > 200
    rows = []
    for k, r in enumerate(roster[:40]):
        rows.append({"NO": r["link"], "FROMNODENO": r["from"], "TONODENO": r["to"],
                     "TYPENO": [1, 2, 11, 13][k % 4], "LENGTH": 1.0, "CAPPRT": 2000.0, "V0PRT": 90.0,
                     "T0_PRTSYS(C)": 40.0, "TCUR_PRTSYS(C)": 60.0, "VOLVEHPRT(AP)": 1800.0,
                     "VOLCAPRATIOPRT(AP)": 0.9 + 0.01 * k, "NUMLANES": 1,
                     "VOLVEH_TSYS(C,AP)": 1500.0})
    out = mod["run"](FakeVisum(rows), ROOT, tmp_path)
    status = (out / "00_STATUS.txt").read_text(encoding="utf-8")
    assert "PASS_READ_ONLY" in status
    prof = list(csv.DictReader(open(out / "01_PROFILES_VDF.csv", encoding="utf-8-sig"), delimiter=";"))
    assert len(prof) >= 35
    assert {p["vdf_no"] for p in prof} <= {"9", "2", "11", "12"}
    p = prof[0]
    assert float(p["tcur_over_t0"]) == 1.5
    summ = list(csv.DictReader(open(out / "02_VDF_CLASS_SUMMARY.csv", encoding="utf-8-sig"), delimiter=";"))
    d6 = [s for s in summ if s["vdf_no"] == "9"][0]
    assert d6["bpr_b"] == "6.0" and float(d6["network_km"]) > 0
