from pathlib import Path
import csv
import hashlib
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_FRESH100_PROFILE488_FRESHCACHE_SAVEFIX1_NO_WALLCLOCK.py'
CSD = ROOT / 'authorities' / 'R1_CSD2022_COUNTLOCATION_AUTHORITY_CURRENT_362_20261022.csv'
CITY = ROOT / 'authorities' / 'R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_CURRENT_126_20261022.csv'
XLSX = ROOT / 'authorities' / 'COUNTLOCATION-2026-10-22-02-23-34.xlsx'


def _rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def _load_launcher():
    spec = importlib.util.spec_from_file_location('profile488_launcher_test', LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_authority_is_exactly_488_all_calibration():
    csd = _rows(CSD)
    city = _rows(CITY)
    rows = csd + city
    assert len(csd) == 362
    assert len(city) == 126
    assert len(rows) == 488
    assert all(r['role'] == 'CALIBRATION' for r in rows)
    assert len({int(r['countlocation_no']) for r in rows}) == 488
    assert len({r['profile_id'] for r in rows}) == 488
    assert all(float(r['live_weight']) > 0 for r in rows)
    assert all(int(r['current_link_no']) > 0 for r in rows)
    assert all(int(r['current_from_node_no']) > 0 for r in rows)
    assert all(int(r['current_to_node_no']) > 0 for r in rows)
    assert all(r['observation_direction'] == 'BOTH' for r in city)


def test_source_workbook_is_sealed_user_table():
    assert hashlib.sha256(XLSX.read_bytes()).hexdigest() == '0244e311488e88f754a691e8c1d535608a13360e91086ee116d6d9e71bf7f860'


def test_launcher_binds_current_authority_not_old_roster():
    mod = _load_launcher()
    cfg = {}
    obs = mod._bind_current_profile_authority(cfg)
    assert len(obs) == 488
    assert all(x['role'] == 'CALIBRATION' for x in obs)
    assert cfg['12d_helper_name'] == 'R1_12D_CURRENT_COUNTLOCATION_488_ALL_CALIBRATION_20261022.py'
    assert cfg['current_countlocation_authority']['validation'] == 0
    assert cfg['current_countlocation_authority']['policy'] == 'EVERY_ROW_IN_USER_TABLE_IS_CALIBRATION_AUTHORITY'


def test_working_copy_metadata_forces_all_profiles_into_calibration():
    mod = _load_launcher()
    obs = mod._load_current_profile_authority()

    class Obj:
        def __init__(self, row):
            self.v = {
                'NO': row['no'], 'R1_ACTIVE': 0, 'R1_ROLE': 'VALIDATION',
                'R1_OBS_RPDI': row['observed'],
                'LINKNO': row['edge_key'][0], 'FROMNODENO': row['edge_key'][1], 'TONODENO': row['edge_key'][2],
            }
        def AttValue(self, name): return self.v[name]
        def SetAttValue(self, name, value): self.v[name] = value

    class Coll:
        def __init__(self, observations): self.items = {r['no']: Obj(r) for r in observations}
        def ItemByKey(self, no): return self.items[no]

    class Net: pass
    class Visum: pass
    v = Visum(); v.Net = Net(); v.Net.CountLocations = Coll(obs)
    result = mod._apply_current_profile_metadata_to_working_copy(v, obs)
    assert result['rows'] == 488
    assert result['calibration_rows'] == 488
    assert result['validation_rows'] == 0
    assert all(o.v['R1_ACTIVE'] == 1 and o.v['R1_ROLE'] == 'CALIBRATION' for o in v.Net.CountLocations.items.values())
