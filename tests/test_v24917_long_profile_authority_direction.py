"""The real CSD authority uses DIRECTIONAL; LONG must retain its exact edge."""
import copy
import importlib
from pathlib import Path

import pytest

from test_v24917_long_cache_generation import live, payload
from test_v24917_long_incidence_read import harness


ROOT = Path(__file__).resolve().parents[1]


def test_actual_roster_loader_is_compatible_with_long_profile_authority(monkeypatch):
    roster = importlib.import_module('r1_15a2_profile_roster_v24917')
    parent = importlib.import_module('r1_15a2_fresh0_shortroot_parent_v24916')
    reader = importlib.import_module('r1_15a2_long_incidence_read_v24917')
    meta = roster.load_meta(ROOT)
    # Use the actual bootstrap loader with the same reduced-roster binding.
    # Track its global constants so this read-only test restores them afterward.
    for name in ('CURRENT_12D_HELPER', 'CURRENT_CSD_AUTH_REL', 'CURRENT_CITY_AUTH_REL',
                 'CURRENT_COUNTLOCATION_SOURCE_REL', 'CURRENT_CSD_AUTH_SHA256',
                 'CURRENT_CITY_AUTH_SHA256', 'CURRENT_COUNTLOCATION_SOURCE_SHA256',
                 'CURRENT_PROFILE_COUNT'):
        monkeypatch.setattr(parent, name, getattr(parent, name))
    roster._patch_fresh0(meta)
    observations = parent._load_current_profile_authority()
    assert len(observations) == meta['rows']
    assert sum(row['direction'] == 'DIRECTIONAL' for row in observations) == meta['csd_rows']
    assert sum(row['direction'] == 'BOTH' for row in observations) == meta['city_rows']
    profiles = []
    for row in observations:
        no, fr, to = row['edge_key']
        profile = dict(countlocation_no=row['no'], link_no=no,
                       from_node_no=fr, to_node_no=to, observation_direction='DIRECTED')
        if row['direction'] == 'BOTH':
            profile.update(observation_direction='BOTH', reverse_link_no=no,
                           reverse_from_node_no=to, reverse_to_node_no=fr)
        profiles.append(profile)
    cfg = {'api_approved_observations': observations}
    before = copy.deepcopy((cfg, profiles))
    assert reader._validate_profiles(profiles, cfg) == [str(row['no']) for row in observations]
    assert (cfg, profiles) == before


def test_directional_authority_reaches_shared_cache_and_nonzero_long_fit(live, monkeypatch):
    adapter, state, _ = live
    adapter.cfg['api_approved_observations'][0]['direction'] = 'DIRECTIONAL'
    result, observed, _, _ = payload(live, monkeypatch)
    generation = importlib.import_module('r1_15a2_long_school_generation_v24917')
    rows = generation.rows_at_scale(result, 1.)
    assert observed['profile_long_vehicle_flow'] == pytest.approx([160., 150.])
    assert result['summary']['long_generation_permitted'] is True
    assert rows and any(row['proposed'] != row['current'] for row in rows)
    assert {row['attr'] for row in rows} <= {'ADD_PROD_L', 'ADD_ATT_L'}
    assert state.exports == 0 and state.writes == []


def test_directional_authority_reaches_read_only_long_export(tmp_path):
    reader = importlib.import_module('r1_15a2_long_incidence_read_v24917')
    adapter, state, profiles = harness()
    adapter.cfg['api_approved_observations'][0]['direction'] = 'DIRECTIONAL'
    result = reader.read_current(adapter, profiles, tmp_path)
    assert state.exports == 1
    assert result['profile_long_vehicle_flow'] == pytest.approx([160., 150.])
    assert result['long_generation_permitted'] is False  # attribution alone never enables TG


@pytest.mark.parametrize('direction', ['', 'SIDEWAYS', 'BIDIRECTIONAL', 'ONE_WAY', None])
def test_unknown_authority_direction_remains_rejected(direction):
    reader = importlib.import_module('r1_15a2_long_incidence_read_v24917')
    adapter, state, profiles = harness()
    adapter.cfg['api_approved_observations'][0]['direction'] = direction
    with pytest.raises(ValueError, match='LONG_INCIDENCE_PROFILE_AUTHORITY_DIRECTION_INVALID'):
        reader._validate_profiles(profiles, adapter.cfg)
    assert state.exports == 0


@pytest.mark.parametrize('change', ['expand_directed', 'collapse_both', 'reverse_directed'])
def test_directional_alias_never_changes_physical_direction_scope(change):
    reader = importlib.import_module('r1_15a2_long_incidence_read_v24917')
    adapter, state, profiles = harness()
    adapter.cfg['api_approved_observations'][0]['direction'] = 'DIRECTIONAL'
    if change == 'expand_directed':
        profiles[0].update(observation_direction='BOTH', reverse_link_no=10,
                           reverse_from_node_no=2, reverse_to_node_no=1)
    elif change == 'collapse_both':
        profiles[1]['observation_direction'] = 'DIRECTED'
    else:
        profiles[0].update(from_node_no=2, to_node_no=1)
    with pytest.raises(ValueError, match='LONG_INCIDENCE_PROFILE_DIRECTION_AUTHORITY_MISMATCH'):
        reader._validate_profiles(profiles, adapter.cfg)
    assert state.exports == 0
