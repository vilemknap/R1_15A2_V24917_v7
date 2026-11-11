import copy
import importlib.util
import json
from pathlib import Path
import runpy

import numpy as np
import pytest

from test_scenario_io import fake, io

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('export_2022_tested', ROOT / 'export_2022.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


@pytest.fixture
def opened_2022():
    v = fake()
    v.IO.CurrentVersionFile = r'C:\calibration\CHECKPOINTS\ACCEPTED_A_0003_d18f2c796ad6.ver'
    return v


def export(v, folder):
    return exporter.run_export_2022(v, folder, vars(io))


def test_export_current_checkpoint_without_import_or_recompute_and_without_model_writes(tmp_path, opened_2022):
    v = opened_2022
    v.Net.DemandSegments.items['NATIVE_CF'].ODMatrix.arr[0, 1] = 1.2345679
    v.Net.DemandSegments.items['EXOG_EE_CF'].ODMatrix.arr[0, 1] = 2.125
    for no in range(9291, 9296):
        v.Net.Matrices.items[no].arr[1, 0] = 2.
    v.Net.Matrices.items[9305].arr[1, 0] = 10.
    v.Net.Matrices.items[7001].arr[0, 1:4] = [.5, 1.5, .49999999999999994]
    v.Net.Matrices.items[7002].arr[1, 0] = 2.5
    matrices = {no: m.arr.copy() for no, m in v.Net.Matrices.items.items()}
    zones = copy.deepcopy(v.Net.Zones.data)
    result = export(v, tmp_path)
    target, = tmp_path.glob('EXPORT_*')
    assert result == json.loads((target / 'EXPORT_MANIFEST.json').read_text())
    assert result['year'] == 2022 and result['status'] == 'PASS_EXPORTED'
    assert result['model_writes'] is result['version_saved'] is result['recomputed'] is False
    assert result['assignment_freshness'] == 'NOT_VERIFIED_BY_EXPORTER'
    assert result['fingerprint']['zone_order'] == list(range(681, 0, -1))
    assert '681 680 3.359568\n' in (target / 'R1_2022_OA_CAL_WORK.mtx').read_text()
    assert '680 681 10.000000\n' in (target / 'R1_2022_OA_CAL_WORK.mtx').read_text()
    lnv = (target / 'R1_2022_LNV.mtx').read_text()
    assert '681 680 1\n' in lnv and '681 679 2\n' in lnv and '681 678 ' not in lnv
    assert '680 681 3\n' in (target / 'R1_2022_NV.mtx').read_text()
    for record in result['outputs']:
        assert io.digest((target / record['file']).read_bytes()) == record['sha256']
    assert result['outputs'][1]['maximum_cell_rounding_delta'] == .5
    assert v.Net.Zones.data == zones and not v.Net.Zones.calls
    assert all(np.array_equal(m.arr, matrices[no]) and m.calls == 0 for no, m in v.Net.Matrices.items.items())


def test_rounding_is_half_up_and_keeps_nearby_non_ties():
    source = np.array([0., .49999999999999994, .5, 1.5, 2.5, 3.49, 3.50000000001])
    assert np.array_equal(exporter.round_freight_half_up(source, io.ScenarioError), [0, 0, 1, 2, 3, 3, 4])


@pytest.mark.parametrize('bad', [-1., float('nan'), float('inf'), float(2**53)])
def test_invalid_freight_is_rejected_instead_of_truncated(bad):
    with pytest.raises(io.ScenarioError, match='INVALID_FREIGHT'):
        exporter.round_freight_half_up(np.array([bad]), io.ScenarioError)


@pytest.mark.parametrize('path', ['', r'C:\models\R1_2040.ver', r'C:\models\R1_2022_2025.ver'])
def test_unsaved_or_forecast_version_does_not_publish(tmp_path, opened_2022, path):
    opened_2022.IO.CurrentVersionFile = path
    with pytest.raises(io.ScenarioError):
        export(opened_2022, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('failure', ['freight_alias', 'passenger_alias', 'wrong_long', 'long_support', 'long_sum', 'nan', 'zones'])
def test_invalid_source_scope_or_values_never_publish(tmp_path, opened_2022, failure):
    v = opened_2022
    if failure == 'freight_alias':
        v.Net.DemandSegments.items['NV'] = v.Net.DemandSegments.items['LNV']
    elif failure == 'passenger_alias':
        v.Net.DemandSegments.items['LNV'] = v.Net.DemandSegments.items['NATIVE_CF']
    elif failure == 'wrong_long':
        v.Net.DemandSegments.items['NATIVE_CL'] = v.Net.DemandSegments.items['NATIVE_CF']
    elif failure == 'long_support':
        v.Net.Matrices.items[9697].arr[0, 1] = 79.9
        v.Net.Matrices.items[9111].arr[0, 1] = 1.
    elif failure == 'long_sum':
        v.Net.Matrices.items[9305].arr[0, 1] = 1.
    elif failure == 'nan':
        v.Net.Matrices.items[7001].arr[0, 1] = np.nan
    else:
        v.Net.Zones.order[0] = 1
    with pytest.raises(io.ScenarioError):
        export(v, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('mutation', ['matrix', 'model', 'order'])
def test_model_change_during_export_cleans_staging_and_preserves_previous_export(tmp_path, opened_2022, monkeypatch, mutation):
    v = opened_2022
    old = tmp_path / 'EXPORT_OLDER'
    old.mkdir()
    (old / 'keep.txt').write_text('previous valid export')
    original = io.write_matrix
    def write(*args):
        result = original(*args)
        if args[-1] == 'NV':
            if mutation == 'matrix':
                v.Net.Matrices.items[7001].arr[0, 1] += 1
            elif mutation == 'model':
                v.IO.CurrentVersionFile = r'C:\calibration\R1_2022_OTHER.ver'
            else:
                v.Net.Zones.order.reverse()
        return result
    monkeypatch.setattr(io, 'write_matrix', write)
    with pytest.raises(io.ScenarioError, match='CHANGED_DURING_EXPORT_2022'):
        export(v, tmp_path)
    assert list(tmp_path.iterdir()) == [old]
    assert (old / 'keep.txt').read_text() == 'previous valid export'


def test_write_failure_cleans_partial_export(tmp_path, opened_2022, monkeypatch):
    original = io.write_matrix
    def write(*args):
        if args[-1] == 'NV':
            raise OSError('disk failure')
        return original(*args)
    monkeypatch.setattr(io, 'write_matrix', write)
    with pytest.raises(OSError, match='disk failure'):
        export(opened_2022, tmp_path)
    assert not list(tmp_path.iterdir())


def test_repeated_export_creates_new_directory(tmp_path, opened_2022):
    export(opened_2022, tmp_path)
    export(opened_2022, tmp_path)
    assert len(list(tmp_path.glob('EXPORT_*'))) == 2


def test_launcher_uses_existing_visum_and_sealed_shared_code(tmp_path, opened_2022, monkeypatch, capsys):
    launcher = tmp_path / '2022' / '03_EXPORT_MATRICES_2022.py'
    launcher.parent.mkdir()
    launcher.write_bytes((ROOT / '2022' / launcher.name).read_bytes())
    (tmp_path / 'scenario_io.py').write_text('from test_scenario_io import io\nglobals().update(vars(io))\n')
    (tmp_path / 'export_2022.py').write_bytes((ROOT / 'export_2022.py').read_bytes())
    calls = []
    monkeypatch.setattr(io, 'validate_package', lambda: calls.append('package_checked'))
    runpy.run_path(str(launcher), init_globals={'COM': opened_2022})
    assert calls == ['package_checked']
    assert 'PASS_EXPORT 2022 ' in capsys.readouterr().out
    assert len(list(launcher.parent.glob('EXPORT_*/EXPORT_MANIFEST.json'))) == 1


def test_launcher_requires_visum_host():
    with pytest.raises(RuntimeError, match='inside PTV Visum'):
        runpy.run_path(str(ROOT / '2022' / '03_EXPORT_MATRICES_2022.py'), run_name='__main__')
