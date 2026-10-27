# -*- coding: utf-8 -*-
"""ONE-CLICK V24917: targeted, coarse catch-up of traffic volume (fresh cycle 1).

Visum: open the .ver to start from, then Scripts -> Run script file -> this file.

V24917 = V24916 FRESH0 ISOLATED ACTIVE TARGETING (all files unchanged) plus:
  * TG proposal from a zonal count fit on the exact path incidence
    (targeted per zone, no uniform family step); CATCH_UP phase while
    model/observed < 0.80 with up to +50 % / -20 % per zone and cycle;
  * coefficient envelope ADD_PROD/ATT [0.25, 5] (ZAHR reference x [0.25, 5]);
  * FlowBundle evidence publish fix (V24916 never published its evidence);
  * PrT skim OPERATIONTYPE detected from the live procedure sequence
    (V24916 hard-coded 103 -> EXPECTED_6_ACTIVE_PRT_SKIMS_FOUND_0);
  * TG pre-apply gate non-fatal (cycle-19 failure);
  * TD only every N-th cycle and on TG plateau, early stop after stationarity
    (R1_RUN_OPTIONS.json);
  * DIAGFAST V2 bulk/NumPy 12D+11D with inline parity and LEGACY fallback.
Acceptance (fresh assignment + live 12D/11D + all guards + rollback) unchanged.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
V16_LAUNCHER = "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py"
V17_MANIFEST = "V24917_RUNTIME_MANIFEST.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_v24917_manifest(root: Path = HERE) -> dict:
    manifest = json.loads((root / V17_MANIFEST).read_text(encoding="utf-8"))
    bad = [rel for rel, sha in manifest["required_files"].items()
           if not (root / rel).is_file() or _sha256(root / rel) != sha]
    if bad:
        raise RuntimeError("V24917_RUNTIME_MANIFEST_FAIL:" + ",".join(bad[:20]))
    return {"passes": True, "release": manifest["release"], "files": len(manifest["required_files"])}


def load_v16_launcher():
    """Load the sealed V24916 launcher as a module (it does not auto-run without Visum)."""
    spec = importlib.util.spec_from_file_location("_r1_v24916_launcher", HERE / V16_LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)      # purges r1_15a2_* modules and imports V24916
    return module


def prepare(visum, com=None, print_fn=print, v16=None):
    # The Visum Python host lives across runs; drop stale directory listings of a
    # package folder that was replaced while Visum stayed open.
    importlib.invalidate_caches()
    v17_manifest = verify_v24917_manifest()
    if v16 is None:
        v16 = load_v16_launcher()
    import r1_15a2_runtime_delta_v24917 as delta
    import r1_15a2_trial_adapter_v24917 as adapter17
    import r1_15a2_v24917_runtime as runtime17
    import r1_15a2_runtime_v1 as rt
    import r1_15a2_skim_optype_v24917 as skim_optype
    import r1_15a2_profile_roster_v24917 as roster

    roster_status = roster.install_static(print_fn=print_fn)
    import r1_15a2_long_school_generation_v24917 as lsgen
    ls_status = lsgen.activate(visum)
    print_fn("R1 V24917 LONG/SCHOOL generation: %s" % (
        "ACTIVE (all 4 attributes verified)" if ls_status.get("active") else
        "DEFERRED (transient/unverified COM, W/S continues): " + str(ls_status.get("error"))
        if ls_status.get("reason") != "ATTRIBUTES_MISSING" else
        "INACTIVE (verified missing attribute): " + str(ls_status.get("failed_attr"))))
    import r1_15a2_boundary_generation_v24917 as bdgen
    bd_status = bdgen.activate(visum)
    print_fn("R1 V24917 border-crossing P/A lever: %s" % (
        "ACTIVE zones=%s W/S P=%.0f" % (bd_status.get("zones"), bd_status.get("ws_total_p", 0.0))
        if bd_status.get("active") else "inactive - %s" % bd_status.get("reason")))
    import r1_15a2_intrazonal_penalty_v24917 as izpen
    iz_status = izpen.activate(visum, print_fn=print_fn)
    if not iz_status.get("active"):
        print_fn("R1 V24917 IZ lever inactive: %s" % iz_status.get("reason"))
    skim_status = skim_optype.apply(visum)
    print_fn("V24917 PrT skim OPERATIONTYPE=%s (%s, V24916 constant was %s)"
             % (skim_status["code"], skim_status["method"], skim_status["previous_constant"]))
    v16.Visum = visum
    if com is not None:
        v16.COM = com
    v16.ActiveVisumAdapter = adapter17.VisumAdapter
    v16.apply_active_runtime_delta = delta.apply_active_runtime_delta
    v16.validate_active_runtime_delta = delta.validate_active_runtime_delta
    original_install = v16._install_runtime
    installed = {}

    def install_runtime(visum_, authority, manifest, workspace):
        status = dict(original_install(visum_, authority, manifest, workspace))
        v17 = runtime17.install_all(v16.force100, rt, print_fn=print_fn)
        installed.update(v17)
        status["v24917"] = runtime17.public_status(v17)
        status["v24917_manifest"] = v17_manifest
        status["v24917_profile_roster"] = roster_status
        status["v24917_long_school"] = ls_status
        status["v24917_boundary_generation"] = bd_status
        status["v24917_intrazonal_penalty"] = iz_status
        status["v24917_prt_skim_operation_type"] = {k: v for k, v in skim_status.items()
                                                    if k != "inventory"}
        try:
            path = Path(workspace) / "V24917_RUNTIME_STATUS.json"
            path.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            print_fn("V24917 status write warning:", repr(exc))
        return status

    v16._install_runtime = install_runtime
    print_fn("=== R1 15A2 V24917 TARGETED CATCH-UP (zonal count fit, +50%%/cycle, envelope 0.25-5) ===")
    print_fn("Release: " + delta.RELEASE)
    return v16, installed


def main():
    visum = globals().get("Visum")
    com = globals().get("COM")
    if visum is None and com is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    old_path = list(sys.path)
    try:
        v16, _installed = prepare(visum if visum is not None else com, com)
        return v16.main()
    finally:
        sys.path[:] = old_path


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
