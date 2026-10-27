"""CP01 fail-closed publication regressions, using the actual checkpoint function."""
import hashlib
import json
from pathlib import Path

import pytest
import r1_15a2_overnight_controller_v240 as mod
from tests.synthetic_v22_adapter import SyntheticAdapter, synthetic_config


def _first(root):
    a = SyntheticAdapter(synthetic_config())
    cp = mod._save_rotating_checkpoint(a, root, 0)
    latest = root / "LATEST_ACCEPTED_CHECKPOINT.json"
    assert hashlib.sha256(Path(cp["path"]).read_bytes()).hexdigest() == cp["sha256"]
    return a, latest, latest.read_bytes()


@pytest.mark.parametrize("failed_pointer", ["SLOT_A.json", "LATEST_ACCEPTED_CHECKPOINT.json"])
def test_pointer_failure_never_advances_canonical_latest(tmp_path, monkeypatch, failed_pointer):
    root = tmp_path / "run"
    a, latest, before_bytes = _first(root)
    saved = mod.atomic_json
    def fail(path, value):
        if Path(path).name == failed_pointer:
            raise OSError("INJECTED_POINTER_DISK_FAILURE:" + failed_pointer)
        return saved(path, value)
    monkeypatch.setattr(mod, "atomic_json", fail)
    with pytest.raises(OSError, match="INJECTED_POINTER_DISK_FAILURE"):
        mod._save_rotating_checkpoint(a, root, 1)
    assert latest.read_bytes() == before_bytes
    assert not (root / "CHECKPOINTS/SLOT_A.json").exists()
    old = json.loads(before_bytes)
    old_file = Path(old["checkpoint"]["path"])
    assert old_file.is_file()
    assert hashlib.sha256(old_file.read_bytes()).hexdigest() == old["checkpoint"]["sha256"]
    monkeypatch.setattr(mod, "atomic_json", saved)
    cp = mod._save_rotating_checkpoint(a, root, 1)
    assert json.loads(latest.read_text())["checkpoint"] == cp


def test_failed_later_same_slot_restores_previous_slot_and_latest(tmp_path, monkeypatch):
    root = tmp_path / "run"
    a, latest, _ = _first(root)
    mod._save_rotating_checkpoint(a, root, 1)
    original_latest = latest.read_bytes()
    original_slot_b = (root/"CHECKPOINTS/SLOT_B.json").read_bytes()
    saved = mod.atomic_json
    def fail(path,value):
        if Path(path).name == "LATEST_ACCEPTED_CHECKPOINT.json":
            raise OSError("INJECTED_LATEST_FAILURE")
        return saved(path,value)
    monkeypatch.setattr(mod, "atomic_json", fail)
    with pytest.raises(OSError, match="INJECTED_LATEST_FAILURE"):
        mod._save_rotating_checkpoint(a,root,2)
    assert latest.read_bytes() == original_latest
    assert (root/"CHECKPOINTS/SLOT_B.json").read_bytes() == original_slot_b
    old=json.loads(original_slot_b)["checkpoint"]
    assert hashlib.sha256(Path(old["path"]).read_bytes()).hexdigest()==old["sha256"]


def test_latest_publish_comes_after_slot_and_payload_verification(tmp_path,monkeypatch):
    root=tmp_path/"run"
    a, latest, _ = _first(root)
    order=[]
    saved=mod.atomic_json
    def record(path,value):
        order.append(Path(path).name)
        return saved(path,value)
    monkeypatch.setattr(mod,"atomic_json",record)
    mod._save_rotating_checkpoint(a,root,1)
    assert order.index("SLOT_A.json") < order.index("LATEST_ACCEPTED_CHECKPOINT.json")
    assert (root/"CHECKPOINTS/SLOT_A.json").is_file()


def test_slot_post_replace_error_still_rolls_back_auxiliary_pointer(tmp_path,monkeypatch):
    root=tmp_path/"run"
    a, latest, old_latest = _first(root)
    actual=mod.atomic_json
    def after_write_fail(path,value):
        actual(path,value)
        if Path(path).name == "SLOT_A.json":
            raise OSError("INJECTED_AFTER_REPLACE")
    monkeypatch.setattr(mod,"atomic_json",after_write_fail)
    with pytest.raises(OSError,match="INJECTED_AFTER_REPLACE"):
        mod._save_rotating_checkpoint(a,root,1)
    assert latest.read_bytes() == old_latest
    assert not (root/"CHECKPOINTS/SLOT_A.json").exists()
