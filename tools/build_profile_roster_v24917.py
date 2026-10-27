# -*- coding: utf-8 -*-
"""Build the V24917 reduced CountLocation roster from a Visum CountLocation export.

usage: python3 tools/build_profile_roster_v24917.py <COUNTLOCATION-export.xlsx> [--exclude NO,NO,...]

Rows are taken from the sealed 488 authorities (observed value, edge, weight unchanged);
the export only selects which CountLocations enter the calibration objective.
Writes into authorities/:
  R1_PROFILE_ROSTER_V24917_CSD.csv, R1_PROFILE_ROSTER_V24917_CITY.csv,
  R1_PROFILE_ROSTER_V24917_SOURCE.xlsx, R1_PROFILE_ROSTER_V24917.json
"""
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "authorities"
CSD488 = AUTH / "R1_CSD2022_COUNTLOCATION_AUTHORITY_CURRENT_362_20261022.csv"
CITY488 = AUTH / "R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_CURRENT_126_20261022.csv"
OUT_CSD = AUTH / "R1_PROFILE_ROSTER_V24917_CSD.csv"
OUT_CITY = AUTH / "R1_PROFILE_ROSTER_V24917_CITY.csv"
OUT_XLSX = AUTH / "R1_PROFILE_ROSTER_V24917_SOURCE.xlsx"
OUT_META = AUTH / "R1_PROFILE_ROSTER_V24917.json"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_export(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(x).strip() if x is not None else "" for x in rows[0]]
    col = {h: i for i, h in enumerate(hdr)}
    need = ["No", "FromNodeNo", "ToNodeNo", "LinkNo", "R1 Obs RPDI"]
    miss = [n for n in need if n not in col]
    if miss:
        raise SystemExit("EXPORT_COLUMNS_MISSING:%s" % miss)
    out = {}
    for r in rows[1:]:
        v = r[col["No"]]
        if v is None or str(v).strip() == "":
            continue
        no = int(float(v))
        if no in out:
            raise SystemExit("EXPORT_DUPLICATE_NO:%d" % no)
        out[no] = {"obs": float(r[col["R1 Obs RPDI"]]),
                   "edge": (int(float(r[col["LinkNo"]])), int(float(r[col["FromNodeNo"]])), int(float(r[col["ToNodeNo"]])))}
    return out


def filt(src, keep, export, dst):
    with open(src, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = [r for r in reader if int(r["countlocation_no"]) in keep]
    for r in rows:
        e = export[int(r["countlocation_no"])]
        edge = tuple(int(r[k]) for k in ("current_link_no", "current_from_node_no", "current_to_node_no"))
        if abs(float(r["observed_passenger_cars_O"]) - e["obs"]) > 1e-6 or edge != e["edge"]:
            raise SystemExit("EXPORT_DIFFERS_FROM_AUTHORITY:%s" % r["countlocation_no"])
    with open(dst, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return rows


def main(xlsx, exclude=()):
    export = read_export(xlsx)
    unknown = sorted(set(exclude) - set(export))
    if unknown:
        raise SystemExit("EXCLUDE_NOT_IN_EXPORT:%s" % unknown)
    for no in exclude:
        export.pop(no)
    keep = set(export)
    csd = filt(CSD488, keep, export, OUT_CSD)
    city = filt(CITY488, keep, export, OUT_CITY)
    found = {int(r["countlocation_no"]) for r in csd + city}
    if found != keep:
        raise SystemExit("EXPORT_NOT_IN_488_AUTHORITY:%s" % sorted(keep - found)[:30])
    shutil.copyfile(xlsx, OUT_XLSX)
    meta = {
        "schema": "R1_15A2_V24917_PROFILE_ROSTER_V1",
        "rows": len(found), "calibration": len(found), "validation": 0,
        "csd_rows": len(csd), "city_rows": len(city),
        "csd_csv": "authorities/" + OUT_CSD.name, "csd_sha256": sha(OUT_CSD),
        "city_csv": "authorities/" + OUT_CITY.name, "city_sha256": sha(OUT_CITY),
        "source_xlsx": "authorities/" + OUT_XLSX.name, "source_xlsx_sha256": sha(OUT_XLSX),
        "source_xlsx_original_name": Path(xlsx).name,
        "excluded_from_export": sorted(exclude),
        "parent_authority": {"csd": CSD488.name, "csd_sha256": sha(CSD488),
                             "city": CITY488.name, "city_sha256": sha(CITY488)},
        "observed_sum": round(sum(float(r["observed_passenger_cars_O"]) for r in csd + city), 3),
        "weights": "UNCHANGED_FROM_PARENT_AUTHORITY",
        "countlocation_nos": sorted(found),
    }
    OUT_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in meta.items() if k != "countlocation_nos"}, indent=2))




# ---------------------------------------------------------------- helper
HELPER_SRC = ROOT / "helpers" / "R1_12D_CURRENT_COUNTLOCATION_488_ALL_CALIBRATION_20261022.py"
HELPER_OUT = ROOT / "helpers" / "R1_12D_PROFILE_ROSTER_V24917.py"


def _sub(text, old, new, count=1):
    if text.count(old) != count:
        raise SystemExit("HELPER_TEMPLATE_CHANGED:%r found %d" % (old[:60], text.count(old)))
    return text.replace(old, new)


def build_helper(meta):
    t = HELPER_SRC.read_text(encoding="utf-8-sig")
    t = _sub(t, 'SCRIPT_ID = "R1_12D_CURRENT_COUNTLOCATION_488_ALL_CALIBRATION_20261022"',
             'SCRIPT_ID = "R1_12D_PROFILE_ROSTER_V24917"')
    t = _sub(t, "EXPECTED_ROWS = 488\nEXPECTED_CALIBRATION = 488\n",
             "EXPECTED_ROWS = %d\nEXPECTED_CALIBRATION = %d\n" % (meta["rows"], meta["calibration"]))
    t = _sub(t, "EXPECTED_CSD = 362\nEXPECTED_CITY_ACTIVE = 126\n",
             "EXPECTED_CSD = %d\nEXPECTED_CITY_ACTIVE = %d\n" % (meta["csd_rows"], meta["city_rows"]))
    t = _sub(t, 'AUTHORITY_CSV_NAME = "R1_CSD2022_COUNTLOCATION_AUTHORITY_CURRENT_362_20261022.csv"',
             'AUTHORITY_CSV_NAME = "%s"' % Path(meta["csd_csv"]).name)
    t = _sub(t, 'AUTHORITY_SHA256 = "86319e09010e2c4c261437a805541f9ff45b6bd0a3fe48d0757123f595c112ba"',
             'AUTHORITY_SHA256 = "%s"' % meta["csd_sha256"])
    t = _sub(t, 'CITY_CSV_NAME = "R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_CURRENT_126_20261022.csv"',
             'CITY_CSV_NAME = "%s"' % Path(meta["city_csv"]).name)
    t = _sub(t, 'CITY_SHA256 = "2154cfd4fb080f63ec3f6e233d27bb8d7787a0598febf38c14e7851f3f66a7e0"',
             'CITY_SHA256 = "%s"\n'
             '# V24917 reduced calibration roster (user CountLocation table); other CountLocations\n'
             '# that may still exist in the model are ignored by this helper.\n'
             'ROSTER_NOS = frozenset(%r)\n\n\n'
             'def _roster_authority_path(name):\n'
             '    beside = Path(__file__).resolve().parent / name\n'
             '    if beside.is_file():\n'
             '        return beside\n'
             '    alt = os.environ.get("R1_PROFILE_ROSTER_AUTH_DIR", "")\n'
             '    return Path(alt) / name if alt else beside\n' % (meta["city_sha256"], sorted(meta["countlocation_nos"])))
    t = _sub(t, '{"CALIBRATION": 362,', '{"CALIBRATION": EXPECTED_CSD,')
    t = _sub(t, "authority_path = Path(__file__).resolve().parent / AUTHORITY_CSV_NAME",
             "authority_path = _roster_authority_path(AUTHORITY_CSV_NAME)")
    t = _sub(t, "city_path = Path(__file__).resolve().parent / CITY_CSV_NAME",
             "city_path = _roster_authority_path(CITY_CSV_NAME)")
    t = _sub(t, '''        if no is None:
            continue
        if RESERVED_FIRST <= no <= RESERVED_LAST:
            rows.append(obj)
        elif CITY_FIRST <= no <= CITY_LAST:
            # Only active CITY profiles enter 12D. Inactive ones remain in Visum.
            if as_int(att(obj, ["R1_ACTIVE", "R1 Active"], 0), 0) == 1:
                rows.append(obj)''', '''        if no is None or no not in ROSTER_NOS:
            continue
        if RESERVED_FIRST <= no <= RESERVED_LAST or CITY_FIRST <= no <= CITY_LAST:
            rows.append(obj)''')
    t = _sub(t, '"status": "PASS_CURRENT_TABLE_488_ALL_CALIBRATION"', '"status": "PASS_V24917_PROFILE_ROSTER_ALL_CALIBRATION"')
    if "\nimport os\n" not in t:
        t = _sub(t, "from pathlib import Path\n", "from pathlib import Path\nimport os\n")
    HELPER_OUT.write_text(t, encoding="utf-8")
    meta["helper"] = "helpers/" + HELPER_OUT.name
    meta["helper_sha256"] = sha(HELPER_OUT)
    meta["helper_template"] = "helpers/" + HELPER_SRC.name
    meta["helper_template_sha256"] = sha(HELPER_SRC)
    OUT_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("helper", HELPER_OUT.name, meta["helper_sha256"])


if __name__ == "__main__":
    args = sys.argv[1:]
    excl = []
    if "--exclude" in args:
        i = args.index("--exclude")
        excl = [int(x) for x in args[i + 1].split(",") if x.strip()]
        del args[i:i + 2]
    main(args[0], excl)
    build_helper(json.loads(OUT_META.read_text(encoding="utf-8")))
