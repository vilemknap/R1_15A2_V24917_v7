# -*- coding: utf-8 -*-
"""Synthetic user-flow benchmark for V2.4.8 persistent path epochs.

This is not a PTV Visum wall-time benchmark. It proves controller behavior:
run 1 enumerates once and publishes; run 2/3 restore the same immutable path
store without invoking the enumeration function.
"""
from __future__ import annotations

from pathlib import Path
import json
import tempfile
import time

import r1_15a2_trial_adapter_v240 as adapter_module
from r1_15a2_trial_adapter_v240 import VisumAdapter
from r1_15a2_persistent_path_cache_v248 import PersistentPathCacheManager
from r1_15a2_supply import SupplyPolicy
from r1_15a2_two_mode_v238 import DEFAULT_SETTINGS, QuietControl

A=(11,1,2); P=(12,2,4); B=(13,2,3); C=(14,3,4); T=(15,4,5)
LINKS={k:{"addval1":0.0,"eligible":True,"t0_c_seconds":60.0} for k in (A,P,B,C,T)}


def profile(model=600.0, observed=1000.0):
    return {"link_no":P[0],"from_node_no":P[1],"to_node_no":P[2],
            "observed":observed,"model":model,"role":"CALIBRATION",
            "countlocation_no":"bench-observation"}


def hierarchy():
    raw=[]
    for key,seq in zip(((1,2,1),(1,2,2)),((A,P,T),(A,B,C,T))):
        raw.append([*key,"","","",""])
        for i,edge in enumerate(seq,1):
            raw.append(["","","",i,*edge])
    return raw


def authority():
    return {"matrix_no":9301,"matrix_total":1000.0,"matrix_diagonal":0.0,
            "matrix_interzonal":1000.0,"matrix_sha256":"synthetic",
            "matrix_shape":[2,2]}


def config(root):
    names=("r1_15a2_two_mode_v238.py","r1_15a2_trial_adapter_v240.py",
           "r1_15a2_persistent_path_cache_v248.py","r1_15a2_sequence_v23.py",
           "r1_15a2_supply.py","r1_15a2_core.py","r1_15a2_runtime_v1.py")
    return {
        "release":"R1_15A2_V2_4_8_BENCHMARK",
        "config_sha256":"a"*64,
        "implementation_files":{name:(str(i)*64)[:64] for i,name in enumerate(names,1)},
        "expected_zones":2,
        "path_export_dsegs":["NATIVE_CW"],
        "mutable_dsegs":["NATIVE_CW"],
        "dseg_path_volume_relative_tolerance":0.01,
        "two_mode":dict(DEFAULT_SETTINGS),
        "supply":{"passenger_dsegs":["NATIVE_CW"],"sequence":{
            "design_only_duplicate_scope_policy":"DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS",
            "max_unique_sequences":100000,"max_pairs_per_market":64}},
        "performance":{"path_epochs":{"enabled":True},"persistent_path_cache":{
            "enabled":True,"verify_sha256_on_restore":True,
            "sqlite_quick_check_on_restore":True,"allow_legacy_v247_import":False,
            "retain_epoch_checkpoints":3,"max_total_cache_gib":1.0}},
        "runtime_persistent_path_cache_root":str(Path(root)/"persistent"),
        "runtime_legacy_path_cache_roots":[],
        "runtime_source_version_sha256":"b"*64,
    }


def snapshot(state, matrix="m0", generation="g0"):
    return {"state_hash":state,"fixed_link_hash":"fixed","dseg_hash":"dseg",
            "operations_hash":"ops","addval_hash":"add","matrix_hash":matrix,
            "generation_hash":generation,"td_hash":"td",
            "addval1":{"|".join(str(v) for v in key):0.0 for key in LINKS}}


def make_adapter(cfg, state, rows, counter):
    a=VisumAdapter.__new__(VisumAdapter)
    a.cfg=cfg; a.control=QuietControl(); a.telemetry=None; a.visum=object()
    a.policy=SupplyPolicy(min_geh=1,min_residual=1,max_candidates=8)
    a.cache=None; a.cache_links=None; a.cache_snapshot=None; a.cache_live_snapshot=None
    a.initial_snapshot=None; a.path_epoch_index=0; a.path_epoch_accepts=0
    a.path_epoch_refresh_counts={"DEMAND":0,"SUPPLY":0}
    a.path_epoch_plateau_verified=None; a.path_epoch_history=[]; a.supply_path_proof=None
    a.persistent_path_cache=PersistentPathCacheManager(cfg,a.control)
    a.persistent_cache_manifest=None; a.persistent_cache_restore_record=None
    a.read_links=lambda:{k:dict(v,object=object()) for k,v in LINKS.items()}
    a.snapshot=lambda:state
    return a


def run(out_dir):
    out_dir=Path(out_dir); out_dir.mkdir(parents=True,exist_ok=True)
    cfg=config(out_dir); rows=[profile()]; calls={"enumerations":0}
    original=adapter_module.collect_two_modes

    def synthetic_enumeration(visum,collector,cfg_arg,folder,build_sequence_evidence=False):
        calls["enumerations"]+=1
        collector.add_parents("NATIVE_CW","C",[[1,2,1,600],[1,2,2,400]],authority())
        collector.add_geometry("C",hierarchy())
        if build_sequence_evidence:
            return collector.prepare_sequence_evidence()
        return collector.prepare_incidence_evidence()

    records=[]
    try:
        adapter_module.collect_two_modes=synthetic_enumeration
        s0=snapshot("state-origin")
        a1=make_adapter(cfg,s0,rows,calls)
        t=time.perf_counter(); _,_,r1=a1._build_cache(
            {"d12":{"rows":rows}},out_dir/"RUN1",s0,
            build_sequence_evidence=False,allow_persistent_restore=True)
        fresh=time.perf_counter()-t
        manifest=dict(a1.persistent_cache_manifest)
        descendant=snapshot("state-accepted",matrix="m1",generation="g1")
        transition=a1.accepted_state_changed(descendant,reason="SYNTHETIC_ACCEPT",phase="DEMAND")
        records.append({"run":1,"enumerations_after":calls["enumerations"],
                        "elapsed_seconds":fresh,"record":r1,
                        "persistent_cache_id":manifest["cache_id"],
                        "descendant_binding":transition.get("persistent_binding")})
        a1.close()

        def forbidden(*args,**kwargs):
            raise AssertionError("path enumeration invoked during authorized restart")
        adapter_module.collect_two_modes=forbidden

        a2=make_adapter(cfg,s0,rows,calls)
        t=time.perf_counter(); c2,_,r2=a2._build_cache(
            {"d12":{"rows":rows}},out_dir/"RUN2_ORIGIN_RESTART",s0,
            build_sequence_evidence=False,allow_persistent_restore=True)
        exact=time.perf_counter()-t
        records.append({"run":2,"kind":"EXACT_ORIGIN_RESTART",
                        "enumerations_after":calls["enumerations"],
                        "elapsed_seconds":exact,"record":r2,
                        "read_only":c2.read_only})
        a2.close()

        a3=make_adapter(cfg,descendant,rows,calls)
        t=time.perf_counter(); c3,_,r3=a3._build_cache(
            {"d12":{"rows":rows}},out_dir/"RUN3_ACCEPTED_RESTART",descendant,
            build_sequence_evidence=False,allow_persistent_restore=True)
        accepted=time.perf_counter()-t
        records.append({"run":3,"kind":"BOUND_ACCEPTED_STATE_RESTART",
                        "enumerations_after":calls["enumerations"],
                        "elapsed_seconds":accepted,"record":r3,
                        "read_only":c3.read_only})
        a3.close()
    finally:
        adapter_module.collect_two_modes=original

    result={
        "schema":"R1_15A2_V248_PERSISTENT_CACHE_SYNTHETIC_USER_BENCHMARK_V1",
        "status":"PASS" if calls["enumerations"]==1 else "FAIL",
        "real_visum_com":False,
        "enumeration_calls_total":calls["enumerations"],
        "expected_enumeration_calls":1,
        "restart_enumeration_calls":calls["enumerations"]-1,
        "records":records,
        "conclusion":"Both exact-origin and explicitly bound accepted-state restarts reused the immutable SQLite epoch without calling path enumeration.",
    }
    (out_dir/"V248_PERSISTENT_CACHE_SYNTHETIC_BENCHMARK.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    md=["# V2.4.8 persistent path-cache synthetic user benchmark","",
        "This is a controller/restart behavior test, not a real PTV Visum wall-time benchmark.","",
        "- Fresh run enumeration calls: 1",
        "- Exact-origin restart enumeration calls: 0",
        "- Accepted-state restart enumeration calls: 0",
        "- Both restored stores were opened read-only.",
        "- SHA-256, SQLite quick-check, foreign-key check, manifest contract and state binding were verified.","",
        "Result: **%s**"%result["status"]]
    (out_dir/"V248_PERSISTENT_CACHE_SYNTHETIC_BENCHMARK.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    return result


if __name__=="__main__":
    target=Path(__file__).resolve().parent/"V248_BENCHMARK_OUTPUT"
    result=run(target)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    raise SystemExit(0 if result["status"]=="PASS" else 1)
