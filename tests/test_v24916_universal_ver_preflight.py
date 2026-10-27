from __future__ import annotations

from types import SimpleNamespace
import pytest

import r1_15a2_fresh_baseline_live_preflight_v24916p2c as pf


class _CL:
    def __init__(self, no, obs, edge):
        self.values = {
            "NO": no,
            "R1_OBS_RPDI": obs,
            "LINKNO": edge[0],
            "FROMNODENO": edge[1],
            "TONODENO": edge[2],
        }
    def AttValue(self, name):
        return self.values[name]


class _Coll:
    def __init__(self, rows):
        self.by_no = {int(r["countlocation_no"]): _CL(
            int(r["countlocation_no"]), float(r["observed_passenger_cars_O"]),
            (int(r["current_link_no"]), int(r["current_from_node_no"]), int(r["current_to_node_no"])))
            for r in rows}
    def ItemByKey(self, no):
        return self.by_no[int(no)]


def _rows():
    rows=[]
    for i in range(1,489):
        rows.append({
            "countlocation_no": str(i),
            "observed_passenger_cars_O": str(float(i)),
            "current_link_no": str(1000+i),
            "current_from_node_no": str(2000+i),
            "current_to_node_no": str(3000+i),
            "profile_id": f"P{i}",
        })
    return rows


def test_live_profile488_compatibility_accepts_dynamic_model(monkeypatch, tmp_path):
    rows=_rows()
    monkeypatch.setattr(pf, "_profile488_authority", lambda root: {"rows":488})
    monkeypatch.setattr(pf, "_read_csv", lambda path: rows[:244] if "CSD" in str(path) else rows[244:])
    monkeypatch.setattr(pf, "_call", lambda fn, label, cfg: fn())
    visum=SimpleNamespace(Net=SimpleNamespace(CountLocations=_Coll(rows)))
    result=pf._live_profile488_compatibility(visum, tmp_path, {})
    assert result["passes"] is True
    assert result["checked_rows"] == 488
    assert result["source_model_mutated"] is False


def test_live_profile488_compatibility_rejects_wrong_geometry(monkeypatch, tmp_path):
    rows=_rows()
    coll=_Coll(rows)
    coll.by_no[77].values["LINKNO"] = 999999
    monkeypatch.setattr(pf, "_profile488_authority", lambda root: {"rows":488})
    monkeypatch.setattr(pf, "_read_csv", lambda path: rows[:244] if "CSD" in str(path) else rows[244:])
    monkeypatch.setattr(pf, "_call", lambda fn, label, cfg: fn())
    visum=SimpleNamespace(Net=SimpleNamespace(CountLocations=coll))
    with pytest.raises(RuntimeError, match="PROFILE488_LIVE_MODEL_INCOMPATIBLE"):
        pf._live_profile488_compatibility(visum, tmp_path, {})
