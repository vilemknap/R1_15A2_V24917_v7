from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_FRESH100_PROFILE488_FRESHCACHE_SAVEFIX1_NO_WALLCLOCK.py"


def test_profile_bind_uses_distinct_saveversion_target():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert 'working = folder / "WORKING_START.ver"' in text
    assert 'profile_bound_working = folder / "WORKING_PROFILE488_START.ver"' in text
    assert 'rt.save_version(visum, working)' in text
    assert 'rt.save_version(visum, profile_bound_working)' in text
    # The previously failing duplicate second save must be absent.
    tail = text.split('profile_bound_working = folder / "WORKING_PROFILE488_START.ver"', 1)[1]
    assert 'normalized_working_cp = rt.save_version(visum, working)' not in tail


def test_profile_bound_semantic_sidecar_follows_second_checkpoint():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert 'version_path=profile_bound_working' in text
    assert 'restart.sidecar_path(profile_bound_working)' in text
    assert 'WORKING_PROFILE488_COPY.json' in text
