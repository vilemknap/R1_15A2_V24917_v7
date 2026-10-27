from __future__ import annotations

import hashlib
import inspect
from types import SimpleNamespace

import numpy as np
import pytest

import r1_15a2_finecdf_bridge_v24916 as bridge
import r1_15a2_td09c_16or17_hotfix_v24916 as fix
from r1_15a2_supply import SupplyContractError
from test_v245_native_bridge import fixture


def _prepare(tmp_path, monkeypatch, scope="NATIVE16", dynamic=False):
    ref, path, sha, visum, cfg, control, grav, mats, calls = fixture(tmp_path)
    op = visum.Procedures.Operations.items[1]
    params = op.TripDistributionParameters
    raw = params.AttValue("DSTRATSET")
    if scope == "NATIVE16":
        params.SetAttValue("DSTRATSET", raw.replace("4_FOREIGN,", "").replace(",4_FOREIGN", ""))
    if scope == "MISSING_SCHOOL":
        params.SetAttValue("DSTRATSET", raw.replace(",5_SCHOOL", ""))
    if scope == "EXTRA":
        params.SetAttValue("DSTRATSET", raw + ",6_OTHER")
    if scope == "DUPLICATE":
        params.SetAttValue("DSTRATSET", raw + ",1_WORK_E_C")
    monkeypatch.setattr(bridge.NoDirectMatrixWriteTDAdapter, "__init__", fix._compatible_init)
    outer = SimpleNamespace(v24916_dynamic_skims=object()) if dynamic else None
    return ref, path, sha, visum, cfg, control, grav, mats, calls, outer


def test_v24916_native16_preserves_foreign_and_restores_scope(tmp_path, monkeypatch):
    ref, path, sha, v, cfg, ctl, grav, mats, calls, outer = _prepare(
        tmp_path, monkeypatch, dynamic=False
    )
    p = tmp_path / "inner"
    p.mkdir()
    params = v.Procedures.Operations.items[1].TripDistributionParameters
    original_dset = params.AttValue("DSTRATSET")
    foreign = mats[9116].values.copy()
    b = bridge.NoDirectMatrixWriteTDAdapter(v, ref, p, ctl, outer_adapter=outer)
    assert b.td09c_scope == "NATIVE16_FOREIGN_SEPARATE"
    assert b.dynamic_skim_enabled is False
    assert len(b.original_dset.split(",")) == 16
    assert "4_FOREIGN" not in b.active_dset
    b.isolate_td()
    b.execute()
    b.restore_controls()
    assert params.AttValue("DSTRATSET") == original_dset
    assert [op.AttValue("ACTIVE") for op in v.Procedures.Operations.items] == [1, 1, 1]
    assert np.array_equal(mats[9116].values, foreign)
    assert (p / "TD09C_NATIVE_SCOPE_CONTRACT.json").is_file()



def test_v24916_native16_constructor_preserves_dynamic_skim_binding(tmp_path, monkeypatch):
    ref, path, sha, v, cfg, ctl, grav, mats, calls, outer = _prepare(
        tmp_path, monkeypatch, dynamic=True
    )
    p = tmp_path / "dynamic_inner"
    p.mkdir()
    b = bridge.NoDirectMatrixWriteTDAdapter(v, ref, p, ctl, outer_adapter=outer)
    assert b.td09c_scope == "NATIVE16_FOREIGN_SEPARATE"
    assert b.dynamic_skim_enabled is True
    assert b.outer_adapter is outer
    assert b.dynamic_skim_epoch is None
    assert b.dynamic_eval_index == 0

def test_v24916_full17_scope_still_supported(tmp_path, monkeypatch):
    ref, path, sha, v, cfg, ctl, grav, mats, calls, outer = _prepare(
        tmp_path, monkeypatch, "FULL17"
    )
    p = tmp_path / "inner"
    p.mkdir()
    b = bridge.NoDirectMatrixWriteTDAdapter(v, ref, p, ctl)
    assert b.td09c_scope == "FULL17"
    assert len(b.original_dset.split(",")) == 17


@pytest.mark.parametrize("scope", ["MISSING_SCHOOL", "EXTRA", "DUPLICATE"])
def test_v24916_unauthorized_td_scope_changes_fail_closed(tmp_path, monkeypatch, scope):
    ref, path, sha, v, cfg, ctl, grav, mats, calls, outer = _prepare(
        tmp_path, monkeypatch, scope
    )
    p = tmp_path / "inner"
    p.mkdir()
    with pytest.raises(SupplyContractError, match="EXPECTED_ONE_APPROVED|DUPLICATE_DSTRAT"):
        bridge.NoDirectMatrixWriteTDAdapter(v, ref, p, ctl)
    assert not calls


def test_v24916_native16_requires_readable_frozen_foreign_abc(tmp_path, monkeypatch):
    ref, path, sha, v, cfg, ctl, grav, mats, calls, outer = _prepare(tmp_path, monkeypatch)
    p = tmp_path / "inner"
    p.mkdir()
    params = v.Procedures.Operations.items[1].TripDistributionParameters
    original = params.TripDistributionDStratParameters
    params.TripDistributionDStratParameters = (
        lambda name: (_ for _ in ()).throw(KeyError(name))
        if name == "4_FOREIGN"
        else original(name)
    )
    with pytest.raises(SupplyContractError, match="16_ONLY_FOREIGN_ABC_READ_FAILED"):
        bridge.NoDirectMatrixWriteTDAdapter(v, ref, p, ctl)


def test_v24916_td09c_parent_constructor_hash_is_pinned():
    assert (
        hashlib.sha256(inspect.getsource(bridge.NoDirectMatrixWriteTDAdapter.__init__).encode()).hexdigest()
        == fix.PARENT_INIT_SHA256
    )


def test_v24916_td09c_compat_constructor_has_no_procedure_or_matrix_writes():
    code = inspect.getsource(fix._compatible_init)
    assert "SetAttValue(" not in code
    assert ".SetValues(" not in code
    assert "Procedures.Execute(" not in code


def test_v24916_td09c_readonly_preflight_supports_native16_and_full17(tmp_path, monkeypatch):
    for kind in ("NATIVE16", "FULL17"):
        ref, path, sha, v, cfg, ctl, grav, mats, calls, outer = _prepare(
            tmp_path, monkeypatch, kind
        )
        status = fix.read_only_source_preflight(v)
        assert status["status"] == "PASS"
        assert status["scope"] == (
            "NATIVE16_FOREIGN_SEPARATE" if kind == "NATIVE16" else "FULL17"
        )
        assert status["model_modified"] is False
        assert not calls
