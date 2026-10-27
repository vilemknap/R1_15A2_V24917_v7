"""Location-only regression for Visum.IO.CurrentVersionFile."""
from pathlib import Path
import pytest
import r1_15a2_live_api_audit as audit


class IO:
    def __init__(self, current):
        self.CurrentVersionFile = current


class FakeVisum:
    def __init__(self, current, getpath=None):
        self.IO = IO(current)
        self._getpath = getpath
    def GetPath(self, file_type):
        raise AssertionError('GetPath(2) MUST NOT be used to choose output root')


def test_outputs_follow_loaded_version_and_ignore_different_project_dir(tmp_path):
    ver_dir = tmp_path/'actual_model_location'
    ver_dir.mkdir()
    ver = ver_dir/'my_model.ver'
    ver.write_bytes(b'test version fixture')
    root, source = audit.project_output_root(FakeVisum(str(ver)))
    assert root == ver.parent/'R1_15A2_COM_API_PREFLIGHT'
    assert source == 'Visum.IO.CurrentVersionFile'
    assert root.is_dir()


@pytest.mark.parametrize('current', [None, '', ' ', 'model.ver', 'C:/not-existing/model.ver',
                                    '/tmp/exist_missing.ver', '/tmp/wrong.xlsx'])
def test_no_implicit_fallback_on_bad_current_version(tmp_path, monkeypatch, current):
    # Explicitly prove we do not fall back to project directories or home.
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'unsafe_fallback'))
    with pytest.raises(RuntimeError,match='VISUM_CURRENT_VERSION_FILE'):
        audit.project_output_root(FakeVisum(current))
    assert not (tmp_path/'unsafe_fallback').exists()


def test_unavailable_com_property_is_an_error(tmp_path):
    class Missing:
        def GetPath(self, *args):
            raise AssertionError('GetPath must not be queried')
    with pytest.raises(RuntimeError,match='VISUM_CURRENT_VERSION_FILE_UNAVAILABLE'):
        audit.project_output_root(Missing())


def test_missing_permissions_stop_instead_of_writing_elsewhere(tmp_path, monkeypatch):
    ver = tmp_path/'test.ver'
    ver.write_text('model')
    original = Path.mkdir
    def deny_here(self,*args,**kwargs):
        if self.name == 'R1_15A2_COM_API_PREFLIGHT':
            raise PermissionError('read only model directory')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path, 'mkdir', deny_here)
    with pytest.raises(PermissionError,match='read only'):
        audit.project_output_root(FakeVisum(str(ver)))
