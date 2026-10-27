"""Developer-only: reseal DIAGFAST overlay manifest and the V24917 runtime manifest.

Never run this in response to a failed integrity check on a user machine.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = [
    "R1_TDLONG1_READ_ONLY_PROBE.py",
    "01_SPUSTIT_V24917_TDJOINT1.py",
    "02_SPUSTIT_V24917_TDJOINT1_60_40.py",
    "r1_15a2_td_joint_v24917.py",
    "r1_15a2_td_joint_runtime_v24917.py",
    "01_SPUSTIT_V24917_GENFIX2.py",
    "r1_15a2_parent_equivalence_v24917.py",
    "01_SPUSTIT_V24917_GENFIX1.py",
    "01_SPUSTIT_V24917_TARGETED_CATCHUP.py",
    "r1_15a2_zonal_count_fit_v24917.py",
    "r1_15a2_targeted_generation_v24917.py",
    "r1_15a2_trial_adapter_v24917.py",
    "r1_15a2_active_demand_evidence_v24917.py",
    "r1_15a2_runtime_delta_v24917.py",
    "r1_15a2_v24917_runtime.py",
    "r1_15a2_skim_optype_v24917.py",
    "r1_15a2_dynamic_11d_files_v24917.py",
    "r1_15a2_finecdf_gapfix_v24917.py",
    "r1_15a2_profile_roster_v24917.py",
    "r1_15a2_td_count_blend_v24917.py",
    "r1_15a2_long_school_generation_v24917.py",
    "r1_15a2_long_od_mask_v24917.py",
    "r1_15a2_long_profile_incidence_v24917.py",
    "r1_15a2_long_zonal_fit_v24917.py",
    "r1_15a2_tdlong1_probe_v24917.py",
    "r1_15a2_intrazonal_penalty_v24917.py",
    "r1_15a2_fast_trial_assignment_v24917.py",
    "r1_15a2_step_search_v24917.py",
    "r1_15a2_perf_v24917.py",
    "r1_15a2_combusy2_v24917.py",
    "r1_15a2_preflight_explain_v24917.py",
    "r1_15a2_boundary_generation_v24917.py",
    "r1_15a2_supply_mix_v24917.py",
    "r1_15a2_td_rollback_tolerant_v24917.py",
    "r1_15a2_severity_relax_v24917.py",
    "r1_15a2_rollback_consistency_v24917.py",
    "r1_15a2_boundary_pa_v24917.py",
    "r1_15a2_mobility_guard_v24917.py",
    "r1_15a2_snapshot_reads_v24917.py",
    "r1_15a2_generation_state_v24917.py",
    "R1_VDF_DIAGNOSTIC.py",
    "R1_VDF_EDIT.py",
    "R1_BOUNDARY_X_PA_UPLIFT_DRY_RUN.py",
    "R1_BOUNDARY_X_PA_UPLIFT_APPLY.py",
    "R1_ADD_INTRAZONAL_IMPEDANCE_MATRIX.py",
    "helpers/R1_12D_PROFILE_ROSTER_V24917.py",
    "authorities/R1_PROFILE_ROSTER_V24917.json",
    "authorities/R1_PROFILE_ROSTER_V24917_CSD.csv",
    "authorities/R1_PROFILE_ROSTER_V24917_CITY.csv",
    "authorities/R1_PROFILE_ROSTER_V24917_SOURCE.xlsx",
    "r1_15a2_generation_gate_nonfatal_v1.py",
    "r1_15a2_demand_policy_v1.py",
    "r1_15a2_diagfast_v1.py", "r1_15a2_diagfast_v2.py", "r1_15a2_diagfast_numpy_v2.py",
    "r1_15a2_diagfast_runtime_v1.py", "r1_15a2_diagfast_parity_v1.py",
    "r1_15a2_diagfast_direct_v2.py",
    "r1_15a2_long_distance_guard_v24917.py",
    "r1_15a2_mobility_zone_v24917.py",
    "r1_15a2_procseq_bootstrap_v24917.py",
    "helpers/R1_12D_DIAGFAST_V1.py", "helpers/R1_11D_DIAGFAST_V1.py",
    "V24916_PERF2C_RUNTIME_MANIFEST.json",
    "DIAGFAST_V1_BASE_MANIFEST.json",
    "DIAGFAST_V1_RELEASE_MANIFEST.json",
]


def sha(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def main():
    subprocess.run([sys.executable, str(ROOT / "diagfast_tools" / "refresh_source_manifest.py")],
                   check=True, cwd=str(ROOT))
    sys.path.insert(0, str(ROOT))
    import r1_15a2_runtime_delta_v24917 as delta
    manifest = {"schema": "R1_15A2_V24917_RUNTIME_MANIFEST_V1", "release": delta.RELEASE,
                "parent_release_manifest": "V24916_PERF2C_RUNTIME_MANIFEST.json",
                "required_files": {p: sha(p) for p in RUNTIME}}
    (ROOT / "V24917_RUNTIME_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("V24917 manifest:", len(RUNTIME), "files")


if __name__ == "__main__":
    main()
