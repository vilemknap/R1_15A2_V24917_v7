import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_FRESH100_TGTD100_ONLY_SEMFIX1_NO_WALLCLOCK.py'


def _load_launcher():
    old = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location('fresh100_semfix1_launcher', LAUNCHER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path[:] = old


def _snapshot(seed):
    # Valid 64-char hex hashes; change selected fields by seed.
    names = (
        'fixed_link_hash', 'dseg_hash', 'operations_hash', 'addval_hash',
        'matrix_hash', 'generation_hash', 'td_hash'
    )
    return {name: (('%x' % ((idx + seed) % 16)) * 64) for idx, name in enumerate(names)}


def test_stale_adjacent_sidecar_is_diagnostic_only_for_fresh_baseline(tmp_path):
    m = _load_launcher()
    ver = tmp_path / 'baseline.ver'
    ver.write_bytes(b'not-a-real-ver-needed-for-sidecar-policy-test')

    old_auth = m.restart.build_authority(_snapshot(1), version_path=ver, raw_ver_sha256='a' * 64)
    Path(str(ver) + '.semantic.json').write_text(json.dumps(old_auth), encoding='utf-8')

    live_auth = m.restart.build_authority(_snapshot(7), version_path=ver, raw_ver_sha256='b' * 64)
    result = m._fresh_baseline_sidecar_diagnostic(ver, live_auth)

    assert result['restart_allowed'] is True
    assert result['passes'] is False
    assert result['mismatches']
    assert result['status'] == 'HISTORICAL_SIDECAR_MISMATCH_IGNORED_FOR_FRESH_BASELINE'
    assert result['fresh_start_sidecar_role'] == 'HISTORICAL_DIAGNOSTIC_ONLY'


def test_matching_adjacent_sidecar_remains_diagnostic(tmp_path):
    m = _load_launcher()
    ver = tmp_path / 'baseline.ver'
    ver.write_bytes(b'x')
    live_auth = m.restart.build_authority(_snapshot(3), version_path=ver, raw_ver_sha256='c' * 64)
    Path(str(ver) + '.semantic.json').write_text(json.dumps(live_auth), encoding='utf-8')

    result = m._fresh_baseline_sidecar_diagnostic(ver, live_auth)
    assert result['restart_allowed'] is True
    assert result['passes'] is True
    assert result['status'] == 'HISTORICAL_SIDECAR_SEMANTICS_MATCH_DIAGNOSTIC'
