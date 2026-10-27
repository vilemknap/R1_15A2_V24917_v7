# -*- coding: utf-8 -*-
"""Live accepted-state V24916 evidence builder for active Generation/TD targeting.

This module is deliberately read-only with respect to the Visum model.  It
uses FlowBundle/fresh assignment-path DIS skims only to narrow candidate search.  Frozen path incidence
remains the numerical count-response authority and all acceptance remains in
parent live 12D/11D gates.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import r1_15a2_com_compat as com
import r1_15a2_core as core
import r1_15a2_runtime_v1 as rt
from r1_15a2_candidate_readback_bundle_v24915p2 import diagnostic_reference_hash
from r1_15a2_demand_evidence_v24916 import (
    build_generation_targets,
    build_supported_od,
    build_td_targeting,
    path_parity,
)
from r1_15a2_demand_evidence_v24916p2c import BoundedDemandEvidenceManager
from r1_15a2_flowbundle_v24916 import (
    FlowBundleContract,
    canonical_dseg,
    contract_hash,
    discover_dsegs,
    driver_profile_audit,
    profile_directed_keys,
)
from r1_15a2_flowbundle_v24916p2c import (
    FlowBundleEvidenceIdentity,
    FlowBundleMatrixReducer,
    ReducedFlowBundle,
    canonical_hash,
    ordered_zone_hash,
)

SCHEMA = "R1_15A2_V24916_ACTIVE_DEMAND_EVIDENCE_V1"


def _plain_multi(rows: Any) -> list[Any]:
    return [r[1] if isinstance(r, (tuple, list)) and len(r) >= 2 else r for r in (rows or [])]


def _call(adapter: Any, fn, label: str):
    return com.com_call_with_retry(
        fn, label=label, retry_policy=getattr(adapter, "com_retry_policy", None) or
        (getattr(adapter, "cfg", {}) or {}).get("com_resilience", {}) or {})


def _as_int(value: Any) -> int:
    return int(round(float(value)))


def _exact_link(adapter: Any, key: Sequence[int]) -> Any:
    no, fr, to = (int(x) for x in key)
    obj = _call(adapter, lambda: adapter.visum.Net.Links.ItemByKey(fr, to),
                f"Links.ItemByKey({fr},{to})")
    got = (
        _as_int(obj.AttValue("NO")),
        _as_int(obj.AttValue("FROMNODENO")),
        _as_int(obj.AttValue("TONODENO")),
    )
    if got != (no, fr, to):
        raise RuntimeError(
            "V24916_ACTIVE_LINK_READBACK_MISMATCH:%r!=%r" % (got, (no, fr, to)))
    return obj


def _read_flowbundle_matrix(adapter: Any, link: Any, dseg_obj: Any, code: str) -> Any:
    fb = adapter.visum.Net.FlowBundle
    _call(adapter, lambda: fb.Clear(), "FlowBundle.Clear[pre]")
    try:
        _call(adapter, lambda: setattr(fb, "DemandSegments", str(code)),
              f"FlowBundle.DemandSegments[{code}]")
        _call(adapter, lambda: fb.CreateCondition(link, None, False, False, 0, 0),
              "FlowBundle.CreateCondition[sealed]")
        _call(adapter, lambda: fb.ExecuteCurrentConditions(),
              "FlowBundle.ExecuteCurrentConditions[sealed]")
        matrix = _call(adapter, lambda: fb.GetOrCreateFlowBundleMatrix(dseg_obj),
                       f"FlowBundle.GetOrCreateFlowBundleMatrix[{code}]")
        return _call(adapter, lambda: matrix.GetValues(),
                     f"FlowBundleMatrix.GetValues[{code}]")
    finally:
        try:
            _call(adapter, lambda: fb.Clear(), "FlowBundle.Clear[post]")
        except Exception:
            pass


def _component_rows(diag: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    return (((diag or {}).get("d11") or {}).get("summary") or {}).get(
        "component_dist_summary_rows", []) or []


def _public_driver_audit(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in dict(row).items() if not str(k).startswith("_")}
            for row in rows]


class ActiveDemandEvidenceBuilder:
    """Bounded accepted-state evidence builder attached to one adapter/run."""

    def __init__(self, adapter: Any, package_root: Path, live_authority: Mapping[str, Any]):
        self.adapter = adapter
        self.root = Path(package_root)
        self.live_authority = dict(live_authority)
        self.cfg = dict((adapter.cfg or {}).get("demand_evidence_targeting") or {})
        self.runtime_cfg = dict((adapter.cfg or {}).get("v24916_flowbundle_skim_runtime") or {})
        self.manager = BoundedDemandEvidenceManager(
            max_entries=int(self.runtime_cfg.get("max_evidence_entries", 2)))
        self._zone_index: dict[int, int] = {int(z): i for i, z in enumerate(adapter.zones)}
        self._dsegs: list[dict[str, Any]] | None = None
        self.telemetry = {
            "FLOWBUNDLE_EVIDENCE_BUILD_COUNT": 0,
            "FLOWBUNDLE_EVIDENCE_REUSE_COUNT": 0,
            "FLOWBUNDLE_MATRIX_GETVALUES_COUNT": 0,
            "FLOWBUNDLE_MATRIX_GETVALUES_SECONDS": 0.0,
            "FLOWBUNDLE_RETAINED_OD_ROWS": 0,
            "FLOWBUNDLE_PROFILE_LOCAL_FALLBACKS": 0,
            "FLOWBUNDLE_GLOBAL_FALLBACKS": 0,
            "FLOWBUNDLE_TOTAL_PARITY_PASS": 0,
            "FLOWBUNDLE_TOTAL_PARITY_FAIL": 0,
        }

    def _distance_epoch(self):
        manager = getattr(self.adapter, "v24916_dynamic_skims", None)
        if manager is None:
            raise RuntimeError("V24916_ACTIVE_DYNAMIC_SKIM_MANAGER_MISSING")
        epoch = manager.require_current()
        expected_zone_hash = str((self.live_authority.get("zone_order") or {}).get("sha256", ""))
        if expected_zone_hash and epoch.zone_order_sha256 != expected_zone_hash:
            raise RuntimeError("V24916_ACTIVE_DYNAMIC_SKIM_ZONE_ORDER_MISMATCH")
        return epoch

    def distance_value(self, family: str, origin: int, destination: int) -> float | None:
        epoch = self._distance_epoch()
        fam = str(family or "").upper()
        if fam == "SCHOOL":
            fam = "WORK"
        values = epoch.family_distance.get(fam)
        if values is None:
            return None
        oi = self._zone_index.get(int(origin)); di = self._zone_index.get(int(destination))
        if oi is None or di is None:
            return None
        try:
            value = float(values[oi, di])
        except (TypeError, KeyError, IndexError):
            value = float(values[oi][di])
        return value if math.isfinite(value) else None

    def _native_dsegs(self) -> list[dict[str, Any]]:
        if self._dsegs is None:
            requested = list(self.cfg.get("flowbundle_target_dsegs") or self.adapter.cfg.get("path_export_dsegs", []))
            rows = discover_dsegs(self.adapter.visum, requested, ())
            by = {canonical_dseg(r["canonical_code"]): r for r in rows if r.get("role") == "TARGET_NATIVE"}
            missing = [canonical_dseg(c) for c in requested if canonical_dseg(c) not in by]
            if missing:
                raise RuntimeError("V24916_ACTIVE_NATIVE_DSEG_MISSING:" + ",".join(missing))
            self._dsegs = [by[canonical_dseg(c)] for c in requested]
        return list(self._dsegs)

    def _profile_rows(self) -> list[dict[str, Any]]:
        excluded = set((getattr(self.adapter.cache, "duplicate_scope_audit", {}) or {}).get(
            "excluded_conflicting_driver_indices", ()))
        rows=[]
        for index, raw in enumerate(getattr(self.adapter.cache, "profiles", []) or []):
            row=dict(raw)
            row["v249_duplicate_conflicted_driver"] = index in excluded
            row["v249_profile_index"] = index
            rows.append(row)
        return rows

    def _path_profile_od_rows(self, live_matrices: Mapping[str, Any]) -> list[dict[str, Any]]:
        collector = self.adapter.cache
        profiles = list(getattr(collector, "profiles", []) or [])
        profile_ids=[]
        for index,row in enumerate(profiles):
            value=row.get("countlocation_no", row.get("profile_id", index))
            profile_ids.append(str(value))
        out=[]
        zone_index={int(z):i for i,z in enumerate(self.adapter.zones)}
        query = """SELECT g.orig,g.dest,h.profile_index,SUM(v.volume*h.multiplicity),
                          COUNT(DISTINCT g.gid)
                   FROM volumes v
                   JOIN geometry g ON g.gid=v.gid
                   JOIN profile_hits h ON h.gid=g.gid
                   WHERE v.dseg=?
                   GROUP BY g.orig,g.dest,h.profile_index
                   ORDER BY g.orig,g.dest,h.profile_index"""
        total_query = """SELECT g.orig,g.dest,SUM(v.volume)
                         FROM volumes v JOIN geometry g ON g.gid=v.gid
                         WHERE v.dseg=? GROUP BY g.orig,g.dest"""
        for raw_code,matrix in sorted((live_matrices or {}).items()):
            code=core.norm_code(raw_code)
            stored={(int(o),int(d)):float(v or 0.0)
                    for o,d,v in collector.db.execute(total_query,(code,))}
            for origin,destination,profile_index,stored_through,npaths in collector.db.execute(query,(code,)):
                origin=int(origin); destination=int(destination)
                stored_total=float(stored.get((origin,destination),0.0))
                oi=zone_index.get(origin); di=zone_index.get(destination)
                if oi is None or di is None:
                    raise RuntimeError("V24916_ACTIVE_PATH_OD_ZONE_NOT_IN_ORDER")
                live_total=float(matrix[oi,di])
                scale=live_total/stored_total if stored_total>core.EPS else 0.0
                through=float(stored_through or 0.0)*scale
                pi=int(profile_index)
                out.append({
                    "profile_id": profile_ids[pi] if 0<=pi<len(profile_ids) else str(pi),
                    "profile_index": pi,
                    "dseg_code": code,
                    "origin": origin,
                    "destination": destination,
                    "path_profile_volume": through,
                    "path_count": int(npaths or 0),
                    "live_od_volume": live_total,
                    "stored_od_volume": stored_total,
                })
        return out

    def _identity(self, snapshot: Mapping[str, Any], diag: Mapping[str, Any], dist_epoch) -> FlowBundleEvidenceIdentity:
        rm = getattr(self.adapter, "readback_manager", None)
        assignment_epoch = int(getattr(rm, "assignment_epoch", 0) or 0)
        run_token = str(getattr(rm, "run_token", "NO_RB_RUN_TOKEN"))
        session_token = str(getattr(rm, "visum_session_token", "NO_RB_SESSION_TOKEN"))
        assignment_token = diagnostic_reference_hash({
            "assignment_epoch": assignment_epoch,
            "diagnostics": diag,
            "last_gap_evidence": getattr(self.adapter, "last_gap_evidence", None),
        })
        return FlowBundleEvidenceIdentity(
            run_token=run_token,
            visum_session_token=session_token,
            semantic_state_hash=str(snapshot["state_hash"]),
            assignment_token=assignment_token,
            assignment_epoch=assignment_epoch,
            path_epoch=int(getattr(self.adapter, "path_epoch_index", 0) or 0),
            path_basis_hash=str(self.adapter._epoch_basis() or ""),
            comparison_basis_hash=str(self.adapter._epoch_comparison_basis() or ""),
            zone_order_hash=ordered_zone_hash(self.adapter.zones),
            flowbundle_contract_hash=contract_hash(FlowBundleContract()),
            dist_km_hash=str(getattr(dist_epoch, "epoch_hash", getattr(dist_epoch, "identity_hash", ""))),
            targeting_config_hash=canonical_hash(self.cfg),
        )

    def build(self, diag: Mapping[str, Any], context: Mapping[str, Any], folder: Path,
              snapshot: Mapping[str, Any]):
        folder=Path(folder); folder.mkdir(parents=True, exist_ok=True)
        started=time.perf_counter()
        dist_epoch=self._distance_epoch()
        identity=self._identity(snapshot,diag,dist_epoch)
        cached=self.manager.get(identity)
        if cached is not None:
            self.telemetry["FLOWBUNDLE_EVIDENCE_REUSE_COUNT"] += 1
            return cached

        ecfg=dict(self.cfg.get("flowbundle") or {})
        audits=driver_profile_audit(
            self._profile_rows(),
            int(ecfg.get("max_profiles",12)),
            float(ecfg.get("min_profile_geh",10.0)),
            float(ecfg.get("min_profile_abs_residual",300.0)))
        selected=[r for r in audits if r.get("selected")]
        if not selected:
            self.telemetry["FLOWBUNDLE_GLOBAL_FALLBACKS"] += 1
            raise RuntimeError("V24916_ACTIVE_NO_ELIGIBLE_UNDERLOAD_DRIVERS")

        dsegs=self._native_dsegs()
        zones=tuple(int(z) for z in self.adapter.zones)
        reducer=FlowBundleMatrixReducer(
            zones, top_k=int(self.runtime_cfg.get("flowbundle_top_k_od",3000)))
        reduced_map:dict[str,ReducedFlowBundle]={}
        flow_rows=[]
        profile_status=[]
        for audit in selected:
            profile=dict(audit["_source_row"])
            profile_id=str(audit["profile_id"])
            family=str(audit["_v24916_family"])
            residual=float(audit["_v24916_residual"])
            keys=profile_directed_keys(profile)
            if not keys or len(keys)>2:
                profile_status.append({"profile_id":profile_id,"status":"PATH_ONLY_PROFILE_FALLBACK","reason":"UNSUPPORTED_DIRECTION_SCOPE"})
                self.telemetry["FLOWBUNDLE_PROFILE_LOCAL_FALLBACKS"] += 1
                continue
            try:
                links=[_exact_link(self.adapter,key) for key in keys]
            except Exception as exc:
                profile_status.append({"profile_id":profile_id,"status":"PATH_ONLY_PROFILE_FALLBACK","reason":"LINK_READBACK_FAIL","error":repr(exc)[:500]})
                self.telemetry["FLOWBUNDLE_PROFILE_LOCAL_FALLBACKS"] += 1
                continue
            for dseg in [d for d in dsegs if str(d.get("family"))==family]:
                code=str(dseg["canonical_code"])
                key=f"{profile_id}|{code}"
                t0=time.perf_counter()
                try:
                    raw1=_read_flowbundle_matrix(self.adapter,links[0],dseg["object"],str(dseg["code"]))
                    self.telemetry["FLOWBUNDLE_MATRIX_GETVALUES_COUNT"] += 1
                    if len(links)==2:
                        raw2=_read_flowbundle_matrix(self.adapter,links[1],dseg["object"],str(dseg["code"]))
                        self.telemetry["FLOWBUNDLE_MATRIX_GETVALUES_COUNT"] += 1
                        red=reducer.reduce(raw1,raw2,source_directions=("FORWARD","REVERSE"))
                        raw2=None
                    else:
                        red=reducer.reduce(raw1,source_directions=("DIRECTED",))
                    raw1=None
                    self.telemetry["FLOWBUNDLE_MATRIX_GETVALUES_SECONDS"] += time.perf_counter()-t0
                    if red.total<=0.0:
                        raise RuntimeError("ZERO_FLOW")
                    reduced_map[key]=red
                    retained=red.retained_total
                    for origin,destination,volume in red.retained_od:
                        row={
                            "profile_id":profile_id,
                            "countlocation_no":profile.get("countlocation_no",profile_id),
                            "family":family,
                            "dseg_code":code,
                            "dseg_role":"TARGET_NATIVE",
                            "targeting_eligible":1,
                            "origin":int(origin),"destination":int(destination),
                            "flowbundle_volume":float(volume),
                            "flowbundle_total":float(red.total),
                            "retained_volume":float(retained),
                            "retained_coverage":float(retained/max(red.total,1e-12)),
                            "tail_volume":float(red.tail_total),
                            "observed":float(audit["observed"]),
                            "model":float(audit["model"]),
                            "residual":residual,
                            "geh":float(audit["geh"]),
                            "scope_kind":str(profile.get("observation_direction","DIRECTED")).upper(),
                            "condition_count":len(keys),
                            "distance_km":self.distance_value(family,origin,destination),
                        }
                        flow_rows.append(row)
                    profile_status.append({
                        "profile_id":profile_id,"dseg_code":code,"status":"OK",
                        "flowbundle_total":red.total,"retained_total":red.retained_total,
                        "tail_total":red.tail_total,"retained_od_rows":len(red.retained_od),
                        "source_directions":list(red.source_directions),
                    })
                except Exception as exc:
                    profile_status.append({"profile_id":profile_id,"dseg_code":code,"status":"PATH_ONLY_PROFILE_FALLBACK","reason":"FLOWBUNDLE_READ_OR_REDUCE_FAIL","error":repr(exc)[:800]})
                    self.telemetry["FLOWBUNDLE_PROFILE_LOCAL_FALLBACKS"] += 1

        if not flow_rows:
            self.telemetry["FLOWBUNDLE_GLOBAL_FALLBACKS"] += 1
            raise RuntimeError("V24916_ACTIVE_NO_POSITIVE_FLOWBUNDLE_TARGET_ROWS")

        incidence=context["incidence"]
        supported=build_supported_od(incidence.get("variables",[]))
        live_matrices=self.adapter._live_generation_matrices()
        path_rows=self._path_profile_od_rows(live_matrices)
        parity=path_parity(
            flow_rows,path_rows,
            float(ecfg.get("path_parity_relative_tolerance",0.02)),
            float(ecfg.get("path_parity_absolute_tolerance",2.0)),
            float(ecfg.get("od_parity_relative_tolerance",0.10)),
            float(ecfg.get("od_parity_absolute_tolerance",5.0)))
        passing=set(parity.get("passing_profile_dseg_keys",[]) or [])
        target_rows=[r for r in flow_rows if f"{r['profile_id']}|{core.norm_code(r['dseg_code'])}" in passing]
        if passing:
            self.telemetry["FLOWBUNDLE_TOTAL_PARITY_PASS"] += len(passing)
        failed=list(parity.get("failed_profile_dseg_keys",[]) or [])
        if failed:
            self.telemetry["FLOWBUNDLE_TOTAL_PARITY_FAIL"] += len(failed)
            self.telemetry["FLOWBUNDLE_PROFILE_LOCAL_FALLBACKS"] += len(failed)
        if not target_rows:
            self.telemetry["FLOWBUNDLE_GLOBAL_FALLBACKS"] += 1
            raise RuntimeError("V24916_ACTIVE_FLOWBUNDLE_PATH_PARITY_NO_PASSING_TARGET")

        generation_targets=build_generation_targets(target_rows,supported,self.cfg)
        td_targets=build_td_targeting(target_rows,_component_rows(diag),self.cfg)
        if generation_targets.get("status")!="ACTIVE":
            raise RuntimeError("V24916_ACTIVE_NO_SAFE_GENERATION_TARGETS")

        target_payload={
            "schema":SCHEMA,
            "generation_targets":{
                "status":generation_targets.get("status"),
                "zone_rows":generation_targets.get("zone_rows",[]),
                "allowed_zone_keys":[list(x) for x in sorted(generation_targets.get("allowed_zone_keys",set()))],
                "od_target_count":len(generation_targets.get("od_rows",[])),
            },
            "td_targets":td_targets,
            "parity":parity,
            "profile_status":profile_status,
            "driver_audit":_public_driver_audit(audits),
            "elapsed_seconds":time.perf_counter()-started,
            "acceptance_authority_changed":False,
        }
        snap=self.manager.publish(
            identity=identity, flowbundles=reduced_map,
            skim_identity=dist, target_payload=target_payload)
        self.telemetry["FLOWBUNDLE_EVIDENCE_BUILD_COUNT"] += 1
        self.telemetry["FLOWBUNDLE_RETAINED_OD_ROWS"] += sum(len(v.retained_od) for v in reduced_map.values())
        rt.write_json(folder/"V24916_ACTIVE_EVIDENCE.json", snap.as_dict())
        rt.write_json(folder/"V24916_ACTIVE_EVIDENCE_TELEMETRY.json", self.telemetry)
        return snap


__all__=["ActiveDemandEvidenceBuilder", "SCHEMA"]
