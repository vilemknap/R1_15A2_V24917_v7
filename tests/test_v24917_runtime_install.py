"""V24917 launcher wiring and runtime installation (isolated subprocess)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r'''
import json, sys, importlib.util
from pathlib import Path
root = Path(sys.argv[1]); out = Path(sys.argv[2])
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location("v17", root / "01_SPUSTIT_V24917_TARGETED_CATCHUP.py")
v17 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v17)   # no Visum -> no run
v16 = v17.load_v16_launcher()
calls = []
v16._install_runtime = lambda visum, authority, manifest, workspace: calls.append(1) or {"parent": "ok"}
v16_main_called = []
import r1_15a2_com_compat as com
class _Op:
    def __init__(self, t, a): self.t, self.a = t, a
    def AttValue(self, name): return {"OPERATIONTYPE": self.t, "ACTIVE": self.a}.get(name, "")
class _Ops:
    def __init__(self, ops): self.ops = ops
    def GetAll(self): return self.ops
ops = [_Op(65, 1), _Op(75, 1)] + [_Op(101, 1)] * 4 + [_Op(75, 1)] + [_Op(104, 0)] * 8 + [_Op(104, 1)] * 6
class _V: pass
fake_visum = _V(); fake_visum.Procedures = _V(); fake_visum.Procedures.Operations = _Ops(ops)
mod, installed = v17.prepare(fake_visum, None, print_fn=lambda *a: None, v16=v16)
import r1_15a2_trial_adapter_v24917 as a17, r1_15a2_runtime_delta_v24917 as d17
import r1_15a2_multiblock as mb, r1_15a2_runtime_v1 as rt
res = {
  "visum_bound": mod.Visum is fake_visum,
  "adapter": mod.ActiveVisumAdapter is a17.VisumAdapter,
  "delta": mod.apply_active_runtime_delta is d17.apply_active_runtime_delta,
  "validate": mod.validate_active_runtime_delta is d17.validate_active_runtime_delta,
}
status = mod._install_runtime(fake_visum, {}, {}, str(out))
res.update({
  "parent_install_called": calls == [1],
  "status_file": (out / "V24917_RUNTIME_STATUS.json").is_file(),
  "tg_gate": bool(getattr(mod.force100._evaluate_candidate, "__r1_generation_gate_nonfatal__", False)),
  "demand_policy_gen": bool(getattr(mod.force100._generation_update_once, "__r1_demand_policy__", False)),
  "demand_policy_td": bool(getattr(mod.force100._finecdf_td_once, "__r1_demand_policy__", False)),
  "mb_patched": bool(getattr(mb._signed_generation_refinement, "__r1_v24917__", False)),
  "diagfast_guard": rt.run_12d.__name__ == "run_12d_direct_guard" and rt.run_11d.__name__ == "run_11d_direct_guard",
  "diagfast_integrity": status["v24917"]["diagfast"]["integrity"]["status"],
  "v24917_manifest": status["v24917_manifest"]["passes"],
  "parent_eq_preloaded": "r1_15a2_parent_equivalence_v24917" in sys.modules,
  "parent_eq_source_exact": Path(sys.modules["r1_15a2_parent_equivalence_v24917"].__file__).resolve() == (root / "r1_15a2_parent_equivalence_v24917.py").resolve(),
  "skim_type_detected": com.SKIMS_PRT == 104 and status["v24917_prt_skim_operation_type"]["code"] == 104,
})
print(json.dumps(res))
'''


def test_launcher_prepare_and_install(tmp_path):
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "lad"))
    env.pop("R1_DIAGFAST_DISABLE", None)
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT), str(tmp_path)],
                          capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=600)
    assert proc.returncode == 0, proc.stderr[-4000:]
    res = json.loads(proc.stdout.strip().splitlines()[-1])
    assert all(v is True or v == "PASS" for v in res.values()), res


def test_v24917_manifest_covers_all_new_runtime_files():
    manifest = json.loads((ROOT / "V24917_RUNTIME_MANIFEST.json").read_text(encoding="utf-8"))
    names = set(manifest["required_files"])
    for name in ["01_SPUSTIT_V24917_TARGETED_CATCHUP.py", "r1_15a2_zonal_count_fit_v24917.py",
                 "R1_TDLONG1_READ_ONLY_PROBE.py",
                 "r1_15a2_targeted_generation_v24917.py", "r1_15a2_trial_adapter_v24917.py",
                 "r1_15a2_active_demand_evidence_v24917.py", "r1_15a2_runtime_delta_v24917.py",
                 "r1_15a2_v24917_runtime.py", "r1_15a2_generation_gate_nonfatal_v1.py",
                 "r1_15a2_demand_policy_v1.py", "r1_15a2_diagfast_v1.py", "r1_15a2_diagfast_v2.py",
                 "r1_15a2_diagfast_numpy_v2.py", "r1_15a2_diagfast_runtime_v1.py",
                 "r1_15a2_diagfast_parity_v1.py", "r1_15a2_diagfast_direct_v2.py",
                 "r1_15a2_long_od_mask_v24917.py", "r1_15a2_tdlong1_probe_v24917.py",
                 "r1_15a2_long_distance_guard_v24917.py", "r1_15a2_mobility_zone_v24917.py",
                 "helpers/R1_12D_DIAGFAST_V1.py", "helpers/R1_11D_DIAGFAST_V1.py",
                 "V24916_PERF2C_RUNTIME_MANIFEST.json", "DIAGFAST_V1_RELEASE_MANIFEST.json"]:
        assert name in names, name


def test_v24916_sealed_runtime_manifest_still_passes():
    sys.path.insert(0, str(ROOT))
    from r1_15a2_runtime_manifest_v24916p2c import verify_runtime_manifest
    assert verify_runtime_manifest(ROOT)["passes"] is True


def test_importfix1_parent_module_survives_package_sys_path_removal(monkeypatch):
    """Regression of 2026-10-27 cycle-1 ModuleNotFoundError."""
    import r1_15a2_com_compat  # already loaded by bootstrap in real Visum
    import r1_15a2_supply
    import r1_15a2_v24917_runtime as runtime
    import sys
    name = runtime.PARENT_EQ_MODULE
    original = sys.modules.pop(name, None)
    try:
        # Simulate an embedded host restoring the pre-launch Python path.
        monkeypatch.setattr(sys, "path", [x for x in sys.path if Path(x or ".").resolve() != ROOT])
        assert str(ROOT) not in sys.path
        result = runtime.preload_parent_equivalence(root=ROOT)
        assert result["status"] == "BOUND_BY_MANIFEST_VERIFIED_ABSOLUTE_PATH"
        assert sys.modules[name].__file__ == str(ROOT / (name + ".py"))
        # Test actual late import used inside STEP1.generation_block.
        exec("import r1_15a2_parent_equivalence_v24917 as eq; assert eq.parent_scope")
        assert str(ROOT) not in sys.path
        assert runtime.preload_parent_equivalence(root=ROOT)["status"] == "ALREADY_BOUND"
    finally:
        sys.modules.pop(name, None)
        if original is not None:
            sys.modules[name] = original


def test_importfix1_rejects_mismatched_parent_proof_before_any_trial(tmp_path):
    import hashlib
    import r1_15a2_v24917_runtime as runtime
    package = tmp_path
    name = runtime.PARENT_EQ_MODULE + ".py"
    (package / name).write_text("SOME_CORRUPTED_MODULE = True\n", encoding="utf-8")
    (package / "V24917_RUNTIME_MANIFEST.json").write_text(
        json.dumps({"required_files": {name: hashlib.sha256(b"DIFFERENT_SOURCE").hexdigest()}}), encoding="utf-8")
    import pytest
    with pytest.raises(RuntimeError, match="PARENT_EQ_SOURCE_HASH_MISMATCH"):
        runtime.preload_parent_equivalence(root=package)


def test_importfix1_rejects_stale_module_from_other_package(monkeypatch):
    import types
    import r1_15a2_v24917_runtime as runtime
    stale = types.ModuleType(runtime.PARENT_EQ_MODULE)
    stale.__file__ = "/wrong/package/r1_15a2_parent_equivalence_v24917.py"
    monkeypatch.setitem(sys.modules, runtime.PARENT_EQ_MODULE, stale)
    import pytest
    with pytest.raises(RuntimeError, match="PARENT_EQ_WRONG_MODULE_ORIGIN"):
        runtime.preload_parent_equivalence(root=ROOT)
