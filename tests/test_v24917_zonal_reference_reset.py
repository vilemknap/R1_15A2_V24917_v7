"""Standalone reset: exact COM index/zone identity, durable backup and rollback."""
import copy
import importlib.util
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('zonal_reset_script', ROOT / 'R1_RESET_ZONAL_COEFFICIENTS.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class Zones:
    def __init__(self):
        # Nonmatching indices/NO and shuffled getter order prevent index-as-zone mistakes.
        self.binding = {i: 10000 + 682 - i for i in range(1, 682)}
        self.values = {attr: {no: (0.0 if no % 17 == 0 else 4.3834111531621103)
                             for no in self.binding.values()} for attr in m.REFERENCES}
        self.values['COUNTRY_ADD'] = {no: .6 for no in self.binding.values()}
        self.writes = []
        self.fault = None
        self.read_fault = None

    def GetMultiAttValues(self, attr, active_only):
        assert active_only is False
        if self.read_fault and attr == self.read_fault[0]:
            return self.read_fault[1](self)
        return [(i, no if attr == 'NO' else self.values[attr][no])
                for i, no in reversed(list(self.binding.items()))]

    def SetMultiAttValues(self, attr, rows):
        assert attr in m.REFERENCES
        self.writes.append(attr)
        for i, value in rows:
            self.values[attr][self.binding[i]] = value
            if self.fault:
                self.fault(self, attr, i)


def host():
    zones = Zones()
    return SimpleNamespace(Net=SimpleNamespace(Zones=zones)), zones


def test_exact_reset_and_backup_and_protected_attribute(tmp_path):
    visum, zones = host()
    original = copy.deepcopy(zones.values)
    result = m.reset_coefficients(visum, tmp_path)
    assert result['status'] == 'RESET_VERIFIED_NATIVE_RECOMPUTE_REQUIRED'
    assert result['native_recomputed'] is False and result['model_saved'] is False
    for attr, reference in m.REFERENCES.items():
        assert zones.values[attr] == {no: (0.0 if v == 0 else reference) for no, v in original[attr].items()}
    assert zones.values['COUNTRY_ADD'] == original['COUNTRY_ADD']
    folder = Path(result['backup_directory'])
    backup = json.loads((folder / 'BEFORE.json').read_text())
    assert backup['before'] == {a: {str(z): v for z, v in original[a].items()} for a in m.REFERENCES}
    assert len((folder / 'OBNOVA_KOEFICIENTU.att').read_text().splitlines()) == 683
    assert json.loads((folder / 'REPORT.json').read_text()) == result


def test_second_reset_performs_no_writes(tmp_path):
    visum, zones = host()
    m.reset_coefficients(visum, tmp_path)
    zones.writes.clear()
    assert m.reset_coefficients(visum, tmp_path)['changed_cells'] == 0
    assert zones.writes == []


@pytest.mark.parametrize('attribute', list(m.REFERENCES))
def test_partial_com_setter_failure_restores_every_original_value(tmp_path, attribute):
    visum, zones = host()
    original = copy.deepcopy(zones.values)
    fired = []
    def fail_once(z, attr, index):
        if attr == attribute and index == 5 and not fired:
            fired.append(True)
            raise RuntimeError('partially written COM bulk setter')
    zones.fault = fail_once
    with pytest.raises(m.ResetError, match='ROLLBACK_VERIFIED;'):
        m.reset_coefficients(visum, tmp_path)
    assert zones.values == original
    report = json.loads(next(tmp_path.glob('*/REPORT.json')).read_text())
    assert report['status'] == 'ROLLBACK_VERIFIED'


def test_silent_setter_mismatch_is_detected_and_restored(tmp_path):
    visum, zones = host()
    original = copy.deepcopy(zones.values)
    fired = []
    def miswrite(z, attr, index):
        if attr == 'ADD_PROD_L' and index == 10 and not fired:
            fired.append(True)
            z.values[attr][z.binding[index]] = .9
    zones.fault = miswrite
    with pytest.raises(m.ResetError, match='RESET_READBACK_MISMATCH'):
        m.reset_coefficients(visum, tmp_path)
    assert zones.values == original


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -.1, None, True, ''])
def test_invalid_input_never_writes(tmp_path, bad):
    visum, zones = host()
    zones.values['ZAHR_ATR_SERV'][next(iter(zones.binding.values()))] = bad
    with pytest.raises((m.ResetError, ValueError)):
        m.reset_coefficients(visum, tmp_path)
    assert zones.writes == []


@pytest.mark.parametrize('fault', ['missing_attr', 'missing_row', 'duplicate_row', 'fractional_index', 'wrong_count', 'duplicate_zone'])
def test_incomplete_preflight_never_writes(tmp_path, fault):
    visum, zones = host()
    if fault == 'missing_attr':
        del zones.values['ADD_ATT_L']
    elif fault == 'wrong_count':
        zones.binding.pop(1)
    elif fault == 'duplicate_zone':
        zones.binding[1] = zones.binding[2]
    else:
        def read(z):
            rows = [(i, 1.0) for i in z.binding]
            if fault == 'missing_row':
                rows.pop()
            elif fault == 'duplicate_row':
                rows[-1] = rows[0]
            else:
                rows[0] = (1.1, 1)
            return rows
        zones.read_fault = ('ADD_PROD_L', read)
    with pytest.raises((m.ResetError, KeyError)):
        m.reset_coefficients(visum, tmp_path)
    assert zones.writes == []


def test_backup_failure_prevents_any_live_write(tmp_path, monkeypatch):
    visum, zones = host()
    def unavailable(*args):
        raise OSError('backup disk unavailable')
    monkeypatch.setattr(m, '_backup', unavailable)
    with pytest.raises(OSError):
        m.reset_coefficients(visum, tmp_path)
    assert zones.writes == []


def test_parent_drift_while_backup_is_written_aborts_without_overwriting(tmp_path, monkeypatch):
    visum, zones = host()
    original_backup = m._backup
    def drift(*args):
        original_backup(*args)
        zones.values['ADD_PROD_W'][next(iter(zones.binding.values()))] = 9
    monkeypatch.setattr(m, '_backup', drift)
    with pytest.raises(m.ResetError, match='PARENT_CHANGED_BEFORE_WRITE'):
        m.reset_coefficients(visum, tmp_path)
    assert zones.writes == []
    assert 9 in zones.values['ADD_PROD_W'].values()


def test_unrecorded_success_is_rolled_back(tmp_path, monkeypatch):
    visum, zones = host()
    original = copy.deepcopy(zones.values)
    write_json = m._write_json
    def fail_final(path, data):
        if data.get('status') == 'RESET_VERIFIED_NATIVE_RECOMPUTE_REQUIRED':
            raise OSError('final report disk error')
        write_json(path, data)
    monkeypatch.setattr(m, '_write_json', fail_final)
    with pytest.raises(m.ResetError, match='ROLLBACK_VERIFIED;'):
        m.reset_coefficients(visum, tmp_path)
    assert zones.values == original


def test_rollback_failure_is_explicit_and_never_called_success(tmp_path):
    visum, zones = host()
    def blocked(z, attr, index):
        if (len(z.writes) == 1 and index == 2) or len(z.writes) > 1:
            raise RuntimeError('permanent setter failure')
    zones.fault = blocked
    with pytest.raises(m.ResetError, match='ROLLBACK_UNVERIFIED_REOPEN_SAVED_MODEL'):
        m.reset_coefficients(visum, tmp_path)
    report = json.loads(next(tmp_path.glob('*/REPORT.json')).read_text())
    assert report['status'] == 'ROLLBACK_UNVERIFIED_REOPEN_SAVED_MODEL'
    assert report['rollback_errors']


def test_changed_com_order_rolls_back_by_zone_no(tmp_path):
    visum, zones = host()
    original = copy.deepcopy(zones.values)
    fired = []
    def reorder(z, attr, index):
        if attr == 'ADD_PROD_W' and index == 681 and not fired:
            fired.append(True)
            z.binding = {i: no for i, no in zip(z.binding, reversed(list(z.binding.values())))}
    zones.fault = reorder
    with pytest.raises(m.ResetError, match='ROLLBACK_VERIFIED;'):
        m.reset_coefficients(visum, tmp_path)
    assert zones.values == original


def test_visum_injected_host_entrypoint_without_main_name(tmp_path, monkeypatch, capsys):
    visum, zones = host()
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    runpy.run_path(str(ROOT / 'R1_RESET_ZONAL_COEFFICIENTS.py'),
                   init_globals={'Visum': visum}, run_name='visum_embedded_script')
    assert 'Reset koeficientu overen' in capsys.readouterr().out
    assert zones.writes


def test_actual_uploaded_workbook_matches_standalone_script(tmp_path):
    # Independent data preparation and live implementation must agree on all 8853 cells.
    from xml.etree import ElementTree as E
    from zipfile import ZipFile
    n = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    folder = ROOT / 'artifacts_zonal_reset_20261029'
    datasets = []
    for file in ['ZONE_PUVODNI_PRED_RESETEM.xlsx', 'ZONE_REFERENCNI_KOEFICIENTY_20261029.xlsx']:
        with ZipFile(folder / file) as z:
            strings = [''.join(x.itertext()) for x in E.fromstring(z.read('xl/sharedStrings.xml'))]
            rows = E.fromstring(z.read('xl/worksheets/sheet1.xml')).find('s:sheetData', n)
            def value(c):
                v = c.find('s:v', n)
                return strings[int(v.text)] if c.get('t') == 's' and v is not None else (v.text if v is not None else None)
            import re
            heads = {re.sub('[0-9]', '', c.get('r')): value(c) for c in rows[0]}
            data = {a: {} for a in m.REFERENCES}
            for row in list(rows)[1:]:
                d = {heads[re.sub('[0-9]', '', c.get('r'))]: value(c) for c in row}
                for a in data:
                    data[a][int(d['No'])] = float(d[a])
            datasets.append(data)
    visum, zones = host()
    zones.binding = {i: i for i in range(1, 682)}
    zones.values = copy.deepcopy(datasets[0])
    result = m.reset_coefficients(visum, tmp_path)
    assert zones.values == datasets[1]
    assert result['changed_cells'] == 5169
