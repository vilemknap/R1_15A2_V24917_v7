from copy import deepcopy
from pathlib import Path
import importlib.util

import pytest

from r1_15a2_persistent_path_cache_v248 import PersistentPathCacheManager
from r1_15a2_supply import canonical_hash
from r1_15a2_two_mode_v238 import QuietControl
from test_supply_v22 import links
from test_v2483_cache_compat import source_and_target

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_6.py"
TARGET_RELEASE = "R1_15A2_V2_4_8_6_UNIFIED_ROOT_SATURATION_20261016"
SOURCES = {
    "R1_15A2_V2_4_8_5_STABLE_PROJECT_ROOT_20261016":
        "709d0eb18d65fdb5cc02a24cdeaf199f53dda63af143f34fb2eda15fbaa55613",
    "R1_15A2_V2_4_8_5_GENERATION_SATURATION_HOTFIX_20261016":
        "3315c25d3e9f0a1cd6088d47bc9276358ab24c3be4e127906a03da6758a8508f",
}
PATH_HASHES = {
    "r1_15a2_two_mode_v238.py":
        "a58980069e942b6782f6d906443e81922f81e6596eb5de5be456719f96ce15ad",
    "r1_15a2_trial_adapter_v240.py":
        "af28f414d6b9ddc882023c06637e06f075aeb394d3fd60fa5dd20c4107837484",
    "r1_15a2_persistent_path_cache_v248.py":
        "4aa3b8b6a5688a2637fc91c62f73ed9dfd9743d957631df6e47807240f0ad08b",
}


def load_actual_compatibility():
    spec = importlib.util.spec_from_file_location("v2486_cache_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_config()["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]


@pytest.mark.parametrize("source_release", sorted(SOURCES))
def test_v2486_accepts_both_divergent_v2485_cache_contracts(source_release, tmp_path):
    _source, target, rows, snap, _policy, manifest = source_and_target(tmp_path)
    target = deepcopy(target)
    target["release"] = TARGET_RELEASE
    target["config_sha256"] = "9" * 64
    target["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"] = load_actual_compatibility()

    # Recast the synthetic predecessor manifest as the exact V2485 source
    # identity while keeping every non-consumer contract field unchanged.
    manifest = deepcopy(manifest)
    manifest["release"] = source_release
    contract = manifest["contract"]
    contract["config_sha256"] = SOURCES[source_release]
    contract["path_implementation_files"].update(PATH_HASHES)
    contract["contract_hash"] = canonical_hash(
        {k: v for k, v in contract.items() if k != "contract_hash"})

    manager = PersistentPathCacheManager(target, QuietControl())
    result = manager.validate_manifest(manifest, snap, rows, links(), manifest["sqlite_schema"])
    assert result["mode"] == "EXPLICIT_PREDECESSOR_READ_COMPATIBILITY"
    assert result["source_release"] == source_release
    assert result["target_release"] == TARGET_RELEASE
