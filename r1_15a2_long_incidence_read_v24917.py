"""Fresh, read-only LONG incidence acquisition using the existing bounded exporter.

No procedure, demand write, cache restore or generation activation occurs here.
The adapter binds completion of its own assignment/skims; caller flags cannot
substitute for that binding. The result remains observed vehicle attribution.
"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path

import numpy as np

import r1_15a2_com_compat as com
import r1_15a2_core as core
import r1_15a2_runtime_v1 as rt
import r1_15a2_long_profile_incidence_v24917 as incidence
import r1_15a2_long_support_distance_v24917 as support
from r1_15a2_long_distance_guard_v24917 import MIN_KM
from r1_15a2_skim_v24916 import zone_numbers
from r1_15a2_skim_v24916p2c import ordered_zone_hash
from r1_15a2_two_mode_v238 import atomic_json

RELEASE = "R1_15A2_V24917_LONG_CURRENT_INCIDENCE_V1"
MATRICES = incidence.COMPONENT_MATRICES + (incidence.FINAL_MATRIX,)


def _epoch(adapter, *, require_completed=False):
    manager = getattr(adapter, "readback_manager", None)
    skims = getattr(adapter, "v24916_dynamic_skims", None)
    if (manager is None or skims is None
            or (require_completed and not manager.assignment_completed)
            or manager.assignment_in_progress or manager.assignment_epoch <= 0):
        raise ValueError("LONG_INCIDENCE_COMPLETED_ASSIGNMENT_REQUIRED")
    epoch = skims.require_current()
    if (int(epoch.assignment_epoch) != int(manager.assignment_epoch)
            or epoch.zone_order_sha256 != ordered_zone_hash(adapter.zones)):
        raise ValueError("LONG_INCIDENCE_ASSIGNMENT_ZONE_EPOCH_MISMATCH")
    return {"assignment_epoch": int(manager.assignment_epoch),
            "mutation_epoch": int(manager.mutation_epoch),
            "skim_epoch_hash": str(epoch.epoch_hash),
            "assignment_token": str(epoch.assignment_token),
            "zone_order_sha256": epoch.zone_order_sha256}


def bind_after_assignment(adapter):
    """Called only after the adapter completes native assignment and DIS capture."""
    adapter._long_incidence_assignment_binding = _epoch(adapter, require_completed=True)


def _require_binding(adapter):
    current = _epoch(adapter)
    if current != getattr(adapter, "_long_incidence_assignment_binding", None):
        raise ValueError("LONG_INCIDENCE_ASSIGNMENT_BINDING_STALE_OR_MISSING")
    return current


def _call(adapter, fn, label):
    return com.com_call_with_retry(fn, label="LONG_INCIDENCE:" + label,
                                  retry_policy=getattr(adapter, "com_retry_policy", None))


def _matrices(adapter):
    if zone_numbers(adapter.visum, getattr(adapter, "com_retry_policy", None)) != list(adapter.zones):
        raise ValueError("LONG_INCIDENCE_LIVE_ZONE_ORDER_CHANGED")
    out = {}
    for no in MATRICES:
        matrix = _call(adapter, lambda: adapter.visum.Net.Matrices.ItemByKey(no), "MATRIX_LOOKUP")
        actual = com.exact_int(_call(adapter, lambda: matrix.AttValue("NO"), "MATRIX_NO"), "MATRIX_NO")
        if actual != no:
            raise ValueError("LONG_INCIDENCE_MATRIX_IDENTITY_MISMATCH")
        out[no] = incidence._matrix(_call(adapter, matrix.GetValues, "M%d" % no),
                                    len(adapter.zones), "M%d" % no)
    return out


def _profile_flows(adapter, profiles):
    values = {}
    flows = []
    for profile in profiles:
        keys = core._profile_link_keys(profile)
        if not keys:
            raise ValueError("LONG_INCIDENCE_PROFILE_LINK_INVALID")
        for no, fr, to in keys:
            key = (no, fr, to)
            if key not in values:
                link = _call(adapter, lambda: adapter.visum.Net.Links.ItemByKey(fr, to), "PROFILE_LINK")
                actual = com.exact_int(_call(adapter, lambda: link.AttValue("NO"), "LINK_NO"), "LINK_NO")
                if actual != no:
                    raise ValueError("LONG_INCIDENCE_PROFILE_LINK_IDENTITY_MISMATCH")
                value = com.finite_float(_call(adapter, lambda: link.AttValue(
                    "VOLVEH_DSEG(NATIVE_CL,AP)"), "NATIVE_CL_PROFILE_FLOW"), "LONG_PROFILE_FLOW")
                if value < 0.0:
                    raise ValueError("LONG_INCIDENCE_NEGATIVE_PROFILE_FLOW")
                values[key] = value
        flows.append(sum(values[key] for key in keys))
    return np.asarray(flows, dtype=float)


def _validate_profiles(profiles, cfg):
    authority = {}
    for row in cfg.get("api_approved_observations", ()):
        if str(row.get("role", "CALIBRATION")).upper() != "CALIBRATION":
            continue
        no = com.exact_int(row["no"], "COUNTLOCATION_NO")
        if no in authority:
            raise ValueError("LONG_INCIDENCE_DUPLICATE_PROFILE_AUTHORITY")
        key = tuple(com.exact_int(x, "PROFILE_EDGE") for x in row["edge_key"])
        if len(key) != 3:
            raise ValueError("LONG_INCIDENCE_PROFILE_AUTHORITY_EDGE_INVALID")
        direction = str(row.get("direction", "DIRECTED")).upper()
        if direction not in ("DIRECTED", "BOTH"):
            raise ValueError("LONG_INCIDENCE_PROFILE_AUTHORITY_DIRECTION_INVALID")
        keys = (key, (key[0], key[2], key[1])) if direction == "BOTH" else (key,)
        authority[no] = keys
    ids = [com.exact_int(p["countlocation_no"], "COUNTLOCATION_NO") for p in profiles]
    if not authority or len(set(ids)) != len(ids) or set(ids) != set(authority):
        raise ValueError("LONG_INCIDENCE_CALIBRATION_PROFILE_SCOPE_MISMATCH")
    for no, profile in zip(ids, profiles):
        if core._profile_link_keys(profile) != authority[no]:
            raise ValueError("LONG_INCIDENCE_PROFILE_DIRECTION_AUTHORITY_MISMATCH")
    return [str(no) for no in ids]


class _Collector:
    def __init__(self, profiles, zones, matrices):
        self.profiles, self.zones, self.matrices = profiles, zones, matrices
        self.result = None

    def consume(self, paths, links, dseg):
        return self.consume_stream(paths, iter(links), dseg)

    def consume_stream(self, paths, links, dseg):
        if (self.result is not None or dseg["norm_code"] != "NATIVE_CL"
                or int(dseg["matrix_no"]) != incidence.FINAL_MATRIX):
            raise ValueError("LONG_INCIDENCE_DSEG_MATRIX_SCOPE_MISMATCH")
        self.result = incidence.build_observed_long_incidence(
            paths, links, self.profiles, self.zones, self.matrices[incidence.FINAL_MATRIX],
            {no: self.matrices[no] for no in incidence.COMPONENT_MATRICES})
        return {"status": self.result["status"], "streamed": True,
                "incidence_nnz": int(self.result["incidence"].values.size)}


def read_current(adapter, profiles, folder):
    """Acquire a new snapshot. Explicit diagnostic call; never reuse W/S cache.

    ``profiles`` uses the same ordered live 12D rows as W/S Generation. Export
    configuration is a private copy: NATIVE_CL is NOT added to mutable_dsegs.
    Both OD reconstruction and directly read NATIVE_CL profile flows must agree.
    All six matrices, epochs, model parameters and source identity are rechecked
    after export. A fresh/empty output directory prevents stale success evidence.
    """
    binding = _require_binding(adapter)
    profiles = copy.deepcopy(list(profiles))
    ids = _validate_profiles(profiles, adapter.cfg)
    cfg = copy.deepcopy(adapter.cfg)
    cfg.update(path_export_dsegs=["NATIVE_CL"], mutable_dsegs=[],
               require_all_path_export_dsegs=True, require_verified_bounded_pathlink_com=True,
               path_export_fail_fast=True, dseg_path_volume_relative_tolerance=1.0e-8,
               expected_zones=len(adapter.zones))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError("LONG_INCIDENCE_FRESH_OUTPUT_DIRECTORY_REQUIRED")
    try:
        parent = adapter.generation_guard_snapshot()
        distance, source = support.read_current(adapter)
        matrices = _matrices(adapter)
        mask = distance >= MIN_KM  # no upper limit; FineCDF uses a separate axis
        if any(np.any(a[~mask] > 0.0) for a in matrices.values()):
            raise ValueError("LONG_INCIDENCE_OSRM_SUPPORT_NOT_APPLIED")
        live_flow = _profile_flows(adapter, profiles)
        collector = _Collector(profiles, tuple(adapter.zones), matrices)
        _, export = rt.export_actual_paths_and_build_incidence(
            adapter.visum, folder, cfg, profiles, set(),
            route_batch_callback=collector.consume, build_incidence=False)
        if (collector.result is None or export.get("dsegs") != ["NATIVE_CL"]
                or not export.get("all_selected_dsegs_complete")
                or not export.get("dseg_path_volume_parity_passes")):
            raise ValueError("LONG_INCIDENCE_INCOMPLETE_CURRENT_EXPORT")
        result = collector.result
        if not np.allclose(result["profile_long_vehicle_flow"], live_flow, rtol=1.e-8, atol=1.e-6):
            raise ValueError("LONG_INCIDENCE_LIVE_PROFILE_FLOW_PARITY_FAILED")
        after = _matrices(adapter)
        if any(not np.array_equal(matrices[no], after[no]) for no in MATRICES):
            raise ValueError("LONG_INCIDENCE_OD_CHANGED_DURING_EXPORT")
        if not np.array_equal(live_flow, _profile_flows(adapter, profiles)):
            raise ValueError("LONG_INCIDENCE_PROFILE_FLOW_CHANGED_DURING_EXPORT")
        _, source_after = support.read_current(adapter)
        if source != source_after or adapter.generation_guard_snapshot() != parent:
            raise ValueError("LONG_INCIDENCE_MODEL_CHANGED_DURING_EXPORT")
        if _require_binding(adapter) != binding:
            raise ValueError("LONG_INCIDENCE_EPOCH_CHANGED_DURING_EXPORT")
        result.update(source_status="CURRENT_ADAPTER_ASSIGNMENT_READ_AND_PARITY_CHECKED",
                      assignment_binding=binding, osrm_support=source,
                      profile_long_live_vehicle_flow=live_flow,
                      profile_parity_max_abs=float(np.max(np.abs(
                          live_flow - result["profile_long_vehicle_flow"]), initial=0.0)))
        op = result["incidence"]
        variables = result["variables"]
        archive = folder / "LONG_INCIDENCE.npz"
        with (folder / "LONG_INCIDENCE.npz.tmp").open("wb") as stream:
            np.savez_compressed(stream, row=op.row_idx, col=op.col_idx, value=op.values,
                shape=np.array([op.n_rows, op.n_cols]), zone_nos=np.array(adapter.zones),
                profile_identity=np.array(ids),
                origin=np.array([v["origin"] for v in variables], dtype=np.int64),
                destination=np.array([v["destination"] for v in variables], dtype=np.int64),
                q_current=np.array([v["q_current"] for v in variables]),
                component_matrices=np.array(incidence.COMPONENT_MATRICES),
                component_vehicle_od=np.array([[v["component_vehicle_od"][str(no)] for v in variables]
                                              for no in incidence.COMPONENT_MATRICES]),
                vehicle_production=result["vehicle_production"], vehicle_attraction=result["vehicle_attraction"],
                profile_flow=live_flow,
                component_profile_flow=np.array([result["component_profile_vehicle_flow"][str(no)]
                                                 for no in incidence.COMPONENT_MATRICES]))
        os.replace(folder / "LONG_INCIDENCE.npz.tmp", archive)
        report = {key: result[key] for key in (
            "status", "source_status", "tg_sensitivity_verified", "long_generation_permitted",
            "zone_order_sha256", "matrix_values_sha256", "path_summary",
            "matrix_parity_max_abs", "path_od_parity_max_abs_offdiag", "profile_parity_max_abs",
            "unrouted_intrazonal_volume", "vehicle_total", "assignment_binding", "osrm_support")}
        report.update(release=RELEASE, read_only=True,
                      validation_scope="READ_ONLY_ADAPTER_EXPORT_AND_PARITY",
                      profile_count=len(profiles), variable_count=op.n_cols, incidence_nnz=int(op.values.size),
                      minimum_osrm_km=MIN_KM, maximum_osrm_km=None, archive=archive.name,
                      archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                      export=export, profile_identity=ids)
        atomic_json(folder / "LONG_INCIDENCE_REPORT.json", report)
        return result
    except BaseException as exc:
        # A partial export/archive must never masquerade as a successful snapshot.
        for name in ("LONG_INCIDENCE_REPORT.json", "LONG_INCIDENCE.npz", "LONG_INCIDENCE.npz.tmp"):
            (folder / name).unlink(missing_ok=True)
        atomic_json(folder / "LONG_INCIDENCE_FAILURE.json", {
            "release": RELEASE, "status": "FAILED_READ_ONLY", "error": str(exc),
            "long_generation_permitted": False, "assignment_binding_at_start": binding})
        raise
