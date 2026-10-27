"""Current LONG vehicle OD-to-profile attribution; no TG actuator is enabled."""
import numpy as np
import pytest

import r1_15a2_long_profile_incidence_v24917 as longinc


def _path(o, d, index, volume, code="NATIVE_CL"):
    return {"dseg_code": code, "OrigZoneNo": o, "DestZoneNo": d,
            "Index": index, "Vol(AP)": volume}


def _link(o, d, index, seq, no, fr, to):
    return {"dseg_code": "NATIVE_CL", "OrigZoneNo": o, "DestZoneNo": d,
            "PathIndex": index, "Index": seq, "LinkNo": no,
            "FromNodeNo": fr, "ToNodeNo": to}


def _fixture():
    paths = [_path(1, 2, 1, 80), _path(1, 2, 2, 20), _path(2, 1, 1, 50)]
    links = [_link(1, 2, 1, 1, 10, 1, 2), _link(1, 2, 1, 2, 10, 1, 2),
             _link(1, 2, 1, 3, 20, 2, 3), _link(1, 2, 2, 1, 20, 3, 2),
             _link(2, 1, 1, 1, 20, 3, 2)]
    profiles = [{"link_no": 10, "from_node_no": 1, "to_node_no": 2},
                {"link_no": 20, "from_node_no": 2, "to_node_no": 3,
                 "observation_direction": "BOTH", "reverse_link_no": 20,
                 "reverse_from_node_no": 3, "reverse_to_node_no": 2}]
    final = np.array([[5., 100.], [50., 0.]])
    comp = {no: np.zeros((2, 2)) for no in longinc.COMPONENT_MATRICES}
    comp[9291][:] = [[5., 60.], [10., 0.]]
    comp[9292][:] = [[0., 40.], [40., 0.]]
    return paths, links, profiles, (1, 2), final, comp


def test_exact_saved_path_multiplicity_bidirection_and_component_parity():
    inputs = _fixture()
    out = longinc.build_observed_long_incidence(*inputs)
    assert out["status"] == "OBSERVED_LONG_OD_PROFILE_ONLY"
    assert out["long_generation_permitted"] is False
    assert out["tg_sensitivity_verified"] is False
    assert out["unrouted_intrazonal_volume"] == pytest.approx(5.)
    assert out["vehicle_production"] == pytest.approx([105., 50.])
    assert out["vehicle_attraction"] == pytest.approx([55., 100.])
    assert out["vehicle_total"] == pytest.approx(155.)
    assert out["matrix_parity_max_abs"] == 0.
    assert out["path_od_parity_max_abs_offdiag"] == 0.
    assert len(out["variables"]) == 2
    assert out["profile_long_vehicle_flow"] == pytest.approx([160., 150.])
    assert out["component_profile_vehicle_flow"]["9291"] == pytest.approx([96., 70.])
    assert out["component_profile_vehicle_flow"]["9292"] == pytest.approx([64., 80.])
    assert out["incidence"].forward(np.ones(2)) == pytest.approx([160., 150.])


def test_component_sum_and_saved_path_od_must_match_final_matrix():
    paths, links, profiles, zones, final, comp = _fixture()
    bad = {no: a.copy() for no, a in comp.items()}
    bad[9291][0, 1] += 1.
    with pytest.raises(ValueError, match="COMPONENT_TO_FINAL_OD_MISMATCH"):
        longinc.build_observed_long_incidence(paths, links, profiles, zones, final, bad)
    bad_paths = list(paths)
    bad_paths[0] = dict(bad_paths[0], **{"Vol(AP)": 79.})
    with pytest.raises(ValueError, match="PATH_TO_FINAL_OD_MISMATCH"):
        longinc.build_observed_long_incidence(bad_paths, links, profiles, zones, final, comp)


def test_pathlink_and_source_scope_fail_closed():
    paths, links, profiles, zones, final, comp = _fixture()
    with pytest.raises(ValueError, match="POSITIVE_PATH_WITHOUT_LINKS"):
        longinc.build_observed_long_incidence(paths, links[:4], profiles, zones, final, comp)
    with pytest.raises(ValueError, match="INVALID_OR_ORPHAN_PATHLINK"):
        longinc.build_observed_long_incidence(paths, links + [_link(2, 1, 99, 1, 20, 3, 2)],
                                              profiles, zones, final, comp)
    with pytest.raises(ValueError, match="NOT_NATIVE_CL_PATHS"):
        longinc.build_observed_long_incidence([dict(paths[0], dseg_code="NATIVE_CW")]
                                              + paths[1:], links, profiles, zones, final, comp)


def test_input_matrices_are_not_mutated_and_invalid_matrix_rejected():
    paths, links, profiles, zones, final, comp = _fixture()
    original = final.copy()
    longinc.build_observed_long_incidence(paths, links, profiles, zones, final, comp)
    assert np.array_equal(final, original)
    assert comp[9291][0, 1] == 60.
    with pytest.raises(ValueError, match="MATRIX_INVALID"):
        longinc.build_observed_long_incidence(paths, links, profiles, zones,
                                              np.array([[5., np.nan], [50., 0.]]), comp)
    with pytest.raises(ValueError, match="ZONE_AXIS_INVALID"):
        longinc.build_observed_long_incidence(paths, links, profiles, (1.0, 2), final, comp)
    with pytest.raises(ValueError, match="NO_PROFILES"):
        longinc.build_observed_long_incidence(paths, links, [], zones, final, comp)
