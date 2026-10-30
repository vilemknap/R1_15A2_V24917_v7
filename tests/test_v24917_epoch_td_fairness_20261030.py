"""Offline regression for conditional native path epochs and bounded TD group coverage."""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pytest

import r1_15a2_resume_a0001_v24917 as resume
import r1_15a2_td_joint_v24917 as joint


def test_a0001_source_store_never_retired_and_refresh_is_native(monkeypatch, tmp_path):
    import r1_15a2_two_mode_v238 as tm
    from r1_15a2_supply import SupplyContractError

    original = tmp_path / "OLD" / "TWO_MODE_PATH_STORE.sqlite"
    original.parent.mkdir()
    original.write_bytes(b"immutable")
    target = tmp_path / "RUN_NEW" / "CALIBRATION"
    target.mkdir(parents=True)
    calls = []
    state = {"approved": False}

    def native_build(diag, folder, snapshot, **kwargs):
        calls.append(("build", Path(folder), dict(kwargs)))
        return ("native-built", {}, {})

    def retire(path, folder):
        calls.append(("retire", Path(path)))
        return {"retired": True}

    adapter = NS(
        _build_cache=native_build,
        _retire_obsolete_epoch_store=retire,
        cache=NS(route_db_path=str(original), read_only=True),
        path_epoch_index=1,
        path_epoch_accepts=1,
        cache_live_snapshot={"state_hash": "POST_TD"},
    )
    proof = resume.install_verified_post_acceptance_epoch_refresh(
        adapter, original, target, lambda: state["approved"])
    assert proof["original_sqlite_protected"]
    assert adapter._retire_obsolete_epoch_store(str(original), target)["retired"] is False
    assert original.read_bytes() == b"immutable"

    with pytest.raises(SupplyContractError, match="NO_PATH_ENUMERATION_ALLOWED"):
        adapter._build_cache({}, target / "EPOCH2", {"state_hash": "POST_TD"})
    state["approved"] = True
    with pytest.raises(SupplyContractError, match="NO_PATH_ENUMERATION_ALLOWED"):
        adapter._build_cache({}, target / "EPOCH2", {"state_hash": "POST_TD"})

    adapter.path_epoch_accepts = 2
    with pytest.raises(SupplyContractError, match="POST_ACCEPT_STATE_NOT_VERIFIED"):
        adapter._build_cache({}, target / "EPOCH2", {"state_hash": "OTHER"})
    with pytest.raises(SupplyContractError, match="OUTSIDE_NEW_RUN"):
        adapter._build_cache({}, tmp_path / "UNSAFE", {"state_hash": "POST_TD"})

    result = adapter._build_cache({}, target / "EPOCH2", {"state_hash": "POST_TD"},
                                  build_sequence_evidence=False,
                                  allow_persistent_restore=True)
    assert result[0] == "native-built"
    assert calls[0] == ("build", target / "EPOCH2",
                        {"build_sequence_evidence": False,
                         "allow_persistent_restore": False})
    assert original.read_bytes() == b"immutable"
    assert (target / "EPOCH2" / "A0001_EPOCH_REFRESH_AUTHORITY.json").exists()
    assert adapter._retire_obsolete_epoch_store(str(target/"EPOCH2"/"TWO_MODE_PATH_STORE.sqlite"),target)["retired"] is True


def test_round_robin_td_probes_reach_school_and_long_inside_28_budget():
    groups = ["WORK_" + str(i) for i in range(5)] + ["SERV_" + str(i) for i in range(5)] + ["SCHOOL", "LONG_COMPOSITE"]
    x = {k: np.array([1.0, -1.0]) for k in groups}
    space = NS(
        probe={k: np.array([0.2, 0.2]) for k in groups},
        trust={k: np.array([1.0, 1.0]) for k in groups},
        bounds={k: np.array([[0.0, 3.0], [-3.0, 0.0]]) for k in groups},
    )
    per_group = [list(joint.coordinate_proposals(space, x, [k], {k:1.0})) for k in groups]
    trials = [v for j in range(4) for part in per_group for v in part[j:j+1]]
    first_27 = trials[:27]
    first_polled = [p[0] for p in first_27]
    assert set(first_polled) == set(groups)
    assert first_polled.index("SCHOOL") < 12
    assert first_polled.index("LONG_COMPOSITE") < 12
    assert all(first_polled.count(k) >= 2 for k in groups)
