"""Regressions from the first real V2.4.7 path-epoch run on 2026-10-16."""
from pathlib import Path

import numpy as np
import pytest

from r1_15a2_trial_adapter_v240 import VisumAdapter as PathEpochAdapter
from test_supply_v22 import profile
from test_two_mode_v238 import authority, hierarchy, store, SEQS
from test_v247_path_epochs import bare_epoch_adapter


def test_real_v247_failure_positive_intrazonal_7_7_does_not_force_reenumeration(tmp_path):
    """A positive diagonal OD has no network path and must not trigger refresh."""
    c = store(tmp_path, profiles=[profile(model=0)])
    try:
        # Frozen path support exists only for the interzonal 1->2 relation.
        c.add_parents("NATIVE_CW", "C", [[1, 2, 1, 6.0], [1, 2, 2, 4.0]], authority([6.0, 4.0]))
        c.add_geometry("C", hierarchy())
        c.prepare_incidence_evidence()
        live = np.zeros((7, 7), dtype=float)
        live[0, 1] = 10.0
        live[6, 6] = 25.0  # exact shape of the live V2.4.7 blocker: 7 -> 7
        result, summary = c.incidence({
            "expected_zones": 7,
            "path_export_dsegs": ["NATIVE_CW"],
            "mutable_dsegs": ["NATIVE_CW"],
            "mutable_relation_policy": "ALL_MUTABLE_RELATIONS",
        }, None, live_od_matrices={"NATIVE_CW": live})
        assert result["q_current"].tolist() == [10.0]
        assert result["intrazonal_path_support_policy"] == \
            "NO_NETWORK_PATH_REQUIRED_EXCLUDED_FROM_PATH_INCIDENCE"
        assert summary["source"] == "FROZEN_PATH_EPOCH_LIVE_OD_REWEIGHT_NO_COM_REEXPORT"
    finally:
        c.close()


def test_positive_offdiagonal_without_support_still_forces_reenumeration(tmp_path):
    c = store(tmp_path, profiles=[profile(model=0)])
    try:
        c.add_parents("NATIVE_CW", "C", [[1, 2, 1, 6.0], [1, 2, 2, 4.0]], authority([6.0, 4.0]))
        c.add_geometry("C", hierarchy())
        c.prepare_incidence_evidence()
        live = np.zeros((3, 3), dtype=float)
        live[0, 1] = 10.0
        live[1, 2] = 5.0  # genuine new interzonal support gap
        with pytest.raises(Exception, match="PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION:NATIVE_CW:2:3"):
            c.incidence({
                "expected_zones": 3,
                "path_export_dsegs": ["NATIVE_CW"],
                "mutable_dsegs": ["NATIVE_CW"],
                "mutable_relation_policy": "ALL_MUTABLE_RELATIONS",
            }, None, live_od_matrices={"NATIVE_CW": live})
    finally:
        c.close()


def test_windows_locked_obsolete_store_cleanup_is_deferred_not_fatal(tmp_path, monkeypatch):
    a = bare_epoch_adapter()
    a.cfg["performance"]["path_epochs"].update({
        "cleanup_obsolete_sqlite_after_verified_refresh": True,
        "retain_sqlite_stores": 1,
    })
    old_dir = tmp_path / "epoch-old"
    old_dir.mkdir()
    store_path = old_dir / "TWO_MODE_PATH_STORE.sqlite"
    store_path.write_bytes(b"old-store")
    original_unlink = Path.unlink

    def locked_unlink(self, *args, **kwargs):
        if self == store_path:
            raise PermissionError(32, "file is in use", str(self))
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    record = PathEpochAdapter._retire_obsolete_epoch_store(
        a, store_path, tmp_path / "audit")
    assert record["retired"] is False
    assert record["reason"] == "DELETE_DEFERRED_WINDOWS_FILE_LOCK"
    assert store_path.exists()
    assert (tmp_path / "audit" / "PATH_EPOCH_STORE_RETENTION.json").is_file()


def _zero_share_cfg():
    return {
        "expected_zones": 3,
        "path_export_dsegs": ["NATIVE_CW"],
        "mutable_dsegs": ["NATIVE_CW"],
        "mutable_relation_policy": "ALL_MUTABLE_RELATIONS",
        "dseg_path_volume_relative_tolerance": 0.01,
        "two_mode": {"zero_share_residual_policy": {
            "enabled": True,
            "max_dseg_relative_volume": 0.01,
            "action": "EXCLUDE_FROM_GUIDANCE_PRESERVE_BASE_MARGINS",
        }},
    }


def _zero_share_store(tmp_path):
    c = store(tmp_path, profiles=[profile(model=100)])
    c.add_parents(
        "NATIVE_CW", "C",
        [[1, 2, 1, 100.0], [1, 3, 1, 0.0]],
        {"matrix_no": 9301, "matrix_total": 100.0, "matrix_diagonal": 0.0,
         "matrix_interzonal": 100.0, "matrix_sha256": "fake", "matrix_shape": [3, 3]},
    )
    c.add_geometry("C", hierarchy(
        seqs=(SEQS[0], SEQS[0]),
        keys=((1, 2, 1), (1, 3, 1))))
    c.prepare_incidence_evidence()
    return c


def test_real_v2481_existing_geometry_zero_share_residual_is_not_reenumerated_when_within_parity_contract(tmp_path):
    """Live 1->7 analogue: geometry exists, saved DSeg share is zero, residual is tiny.

    The relation remains in projection base marginals but is excluded from sparse
    path guidance so no route share is invented.  Fresh Visum assignment remains
    the candidate acceptance authority.
    """
    c = _zero_share_store(tmp_path)
    try:
        live = np.zeros((3, 3), dtype=float)
        live[0, 1] = 100.0
        live[0, 2] = 0.5
        result, summary = c.incidence(_zero_share_cfg(), None,
                                      live_od_matrices={"NATIVE_CW": live})
        assert result["q_current"].tolist() == [100.0]
        assert len(result["projection_base_variables"]) == 2
        gap = [m for m in result["projection_base_variables"] if int(m["destination"]) == 3][0]
        assert gap["q_current"] == pytest.approx(0.5)
        assert gap["actuatable_relation"] == 0
        audit = result["zero_share_residual_audit"]
        assert audit["accepted"] is True
        assert audit["row_count"] == 1
        assert audit["volume"] == pytest.approx(0.5)
        assert audit["by_dseg"]["NATIVE_CW"]["relative_volume"] == pytest.approx(0.5 / 100.5)
        assert summary["source"] == "FROZEN_PATH_EPOCH_LIVE_OD_REWEIGHT_NO_COM_REEXPORT"
    finally:
        c.close()


def test_zero_share_residual_above_existing_path_parity_contract_still_fails_closed(tmp_path):
    c = _zero_share_store(tmp_path)
    try:
        live = np.zeros((3, 3), dtype=float)
        live[0, 1] = 100.0
        live[0, 2] = 2.0
        with pytest.raises(Exception, match="PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION.*ZERO_SHARE_RESIDUAL_EXCEEDS_GUIDANCE_TOLERANCE"):
            c.incidence(_zero_share_cfg(), None, live_od_matrices={"NATIVE_CW": live})
    finally:
        c.close()
