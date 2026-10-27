"""Exact saved-route supply proposals. No routing engine and no OD writes.

One raw ADDVAL1 unit adds TEN SECONDS to C/C_noT generalized link cost.
Route incidence proposes bounded changes, never substitutes for a new assignment.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping
import csv
import hashlib
import json
import math

import r1_15a2_core as core


class SupplyContractError(RuntimeError):
    """A missing or violated scientific/runtime contract, not a no-improvement result."""


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def number(value, label="number"):
    out = core.fval(value, None)
    if isinstance(value, bool) or out is None or not math.isfinite(out):
        raise SupplyContractError("INVALID_NUMERIC:" + label)
    return float(out)


def integer(value, label="integer"):
    out = number(value, label)
    if out != round(out):
        raise SupplyContractError("NONINTEGER_KEY:" + label)
    return int(out)


def edge_key(row):
    names = (("link_no", "LinkNo", "NO"), ("from_node_no", "FromNodeNo", "FROMNODENO"),
             ("to_node_no", "ToNodeNo", "TONODENO"))
    return tuple(integer(core.first_value(row, group), group[0]) for group in names)


def key_text(key):
    return "|".join(str(integer(x)) for x in key)


def observation_identity(rows, *, include_model=False):
    result = []
    seen = set()
    for row in rows:
        ident = str(core.first_value(row, ("countlocation_no", "obs_id", "code"), "")).strip()
        role = str(row.get("role", "")).upper()
        if not ident or ident in seen or role not in ("CALIBRATION", "VALIDATION", "DIAGNOSTIC"):
            raise SupplyContractError("INVALID_OBSERVATION_IDENTITY")
        seen.add(ident)
        rec = {"id": ident, "role": role, "keys": core._profile_link_keys(row),
               "observed": number(row.get("observed"), "observed"),
               "source_group": str(row.get("source_group", "CSD2022")),
               "profile_weight": number(row.get("profile_weight", 1.0), "profile_weight"),
               "period": str(row.get("period", row.get("time_basis", "")))}
        if rec["observed"] < 0:
            raise SupplyContractError("NEGATIVE_OBSERVATION")
        if include_model:
            rec["model"] = number(row.get("model"), "model")
            if rec["model"] < 0:
                raise SupplyContractError("NEGATIVE_MODEL_FLOW")
        result.append(rec)
    if not result:
        raise SupplyContractError("EMPTY_OBSERVATION_AUTHORITY")
    return canonical_hash(sorted(result, key=lambda x: x["id"]))


@dataclass(frozen=True)
class SupplyPolicy:
    lattice: float = 1.0
    max_step: float = 1.0
    max_cumulative: float = 4.0
    absolute_min: float = -50.0
    absolute_max: float = 50.0
    minimum_cost_seconds: float = 0.001
    max_bundle_equivalent_seconds: float = 60.0
    max_edges: int = 6
    max_candidates: int = 8
    max_driver_profiles: int = 8
    min_geh: float = 10.0
    min_residual: float = 300.0
    min_attribution_coverage: float = 0.995
    min_path_coverage: float = 0.98
    min_path_volume_coverage: float = 0.995
    parity_relative_tolerance: float = 0.02
    parity_absolute_tolerance: float = 1.0
    prior_lambda: float = 0.0001
    prior_sigma: float = 2.0

    @classmethod
    def from_config(cls, cfg):
        raw = cfg.get("supply", {})
        if number(raw.get("equivalent_seconds_per_addval1", 10.0)) != 10.0:
            raise SupplyContractError("ADDVAL1_MUST_EQUAL_TEN_GENERALIZED_SECONDS")
        known = cls.__dataclass_fields__
        obj = cls(**{k: raw[k] for k in known if k in raw})
        for k in known:
            v = number(getattr(obj, k), k)
            if k not in ("absolute_min", "absolute_max") and v < 0:
                raise SupplyContractError("NEGATIVE_POLICY:" + k)
        for k in ("max_edges", "max_candidates", "max_driver_profiles"):
            if integer(getattr(obj, k), k) < 1:
                raise SupplyContractError("INVALID_BUDGET:" + k)
        # V2.4.9.13 allows a half-ADDVAL lattice (5 generalized seconds) so
        # route-choice search can use both materially larger exploration moves
        # and a finer final backtracking step.  The impedance authority remains
        # exactly 10 seconds per ADDVAL unit; only the candidate lattice changes.
        allowed_lattices = (0.5, 1.0)
        if (not any(abs(obj.lattice - x) <= 1e-12 for x in allowed_lattices)
                or obj.max_step < obj.lattice
                or obj.prior_sigma <= 0 or obj.prior_lambda <= 0):
            raise SupplyContractError("INVALID_SECONDS_LATTICE_OR_PRIOR")
        if obj.absolute_min > obj.absolute_max or obj.max_cumulative < obj.lattice:
            raise SupplyContractError("INVALID_ADDVAL_BOUNDS")
        if any(not 0 < getattr(obj, k) <= 1 for k in
               ("min_attribution_coverage", "min_path_coverage", "min_path_volume_coverage")):
            raise SupplyContractError("INVALID_COVERAGE_POLICY")
        if obj.minimum_cost_seconds <= 0 or obj.max_bundle_equivalent_seconds < 10:
            raise SupplyContractError("INVALID_COST_DOMAIN_OR_BUNDLE_BUDGET")
        return obj


def validate_impedance_csv(path):
    """Verify the user-supplied active expression contract, retaining inactive rows."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    result = {}
    for cls in ("C", "C_noT", "LNV", "NV"):
        rr = [r for r in rows if r.get("TSYSCODE") == cls]
        switches = {integer(r.get("USE_DETAILED")) for r in rr}
        expected_switch = 1 if cls in ("C", "C_noT") else 0
        if switches != {expected_switch}:
            raise SupplyContractError("IMPEDANCE_SWITCH:" + cls)
        for kind in ("LINK", "CONNECTOR", "TURN", "MAINTURN"):
            selected = kind if expected_switch else "GENERAL"
            terms = [r for r in rr if r.get("NETOBJECTTYPE") == selected]
            if len(terms) != 1:
                raise SupplyContractError("IMPEDANCE_TERM_COUNT:" + cls + ":" + kind)
            term = terms[0]
            source = "C" if cls == "C_noT" and kind == "LINK" else cls
            has_add = cls in ("C", "C_noT") and kind == "LINK"
            if (number(term["FIRST_COEFF"]) != 100 or term["FIRST_ATTR"] != "TCUR_PRTSYS(%s)" % source
                or term["OPERATION"] != ("Add" if has_add else "None")
                or number(term["SECOND_COEFF"]) != (1000 if has_add else 0)
                or (has_add and term["SECOND_ATTR"] != "ADDVAL1")):
                raise SupplyContractError("ACTIVE_IMPEDANCE_CHANGED:" + cls + ":" + kind)
            result[cls + ":" + kind] = {"time_source": source,
                "equivalent_seconds_per_addval1": 10.0 if has_add else 0.0}
    return {"schema": "R1_15A2_ADDVAL1_TEN_SECONDS_V1", "stored_terms": len(rows),
            "effective": result, "authority_hash": canonical_hash(rows)}


class ActualRouteCollector:
    """Consume one official DSeg batch; retain only CAL driver/edge aggregates.

    Alternatives are explicit paths of the SAME (DSeg, origin, destination).
    Shared edges cancel in the conditional contrast. No graph search is used.
    """
    def __init__(self, profiles, policy, parent_hash, editable_keys, *, duplicate_scope_policy="FAIL"):
        self.policy = policy
        self.parent_hash = parent_hash
        self.profiles = [dict(x) for x in profiles]
        self.authority_hash = observation_identity(profiles, include_model=False)
        observation_identity(profiles, include_model=True)
        self.keys = [edge_key(x) for x in profiles]
        self.key_groups = [tuple(core._profile_link_keys(x)) for x in profiles]
        if any(not group for group in self.key_groups):
            raise SupplyContractError("INVALID_PROFILE_DIRECTION_GROUP")
        self.editable = set(editable_keys)
        self.flow = [0.0 for _ in profiles]
        # Several distinct approved CountLocations can map to the SAME directed
        # link. Their observations remain independent/unaltered in every 12D
        # diagnostic and the accepted-state objective.  A conflicting same-source
        # physical scope must never supply an arbitrary driver target.
        if duplicate_scope_policy not in ("FAIL", "DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS"):
            raise SupplyContractError("UNKNOWN_DUPLICATE_SCOPE_POLICY")
        same_source = defaultdict(list)
        edge_profiles = defaultdict(list)
        for index, row in enumerate(self.profiles):
            if str(row.get("role", "")).upper() == "CALIBRATION":
                same_source[(self.key_groups[index],
                             str(row.get("source_group", "CSD2022")))].append(index)
            for key in self.key_groups[index]:
                edge_profiles[key].append(index)
        same_source_groups = []
        excluded_driver_indices = set()
        for (scope, source), indices in sorted(same_source.items(), key=lambda x: (x[0][1], x[0][0])):
            if len(indices) < 2:
                continue
            rows = [{"row_index": i,
                     "countlocation_no": str(core.first_value(self.profiles[i],
                         ("countlocation_no", "obs_id", "code"), "")),
                     "observed": number(self.profiles[i]["observed"]),
                     "model": number(self.profiles[i]["model"]),
                     "weight": number(self.profiles[i].get("profile_weight", 1.0))}
                    for i in indices]
            conflict = len({(r["observed"], r["model"]) for r in rows}) != 1
            if conflict:
                excluded_driver_indices.update(indices)
            same_source_groups.append({"directed_scope": [list(e) for e in scope],
                                       "source_group": source,
                                       "conflict": conflict, "profiles": rows})
        conflicts = [r for r in same_source_groups if r["conflict"]]
        physical_overlap = []
        for key, indices in sorted(edge_profiles.items()):
            if len(indices) > 1:
                physical_overlap.append({"directed_key": list(key),
                    "countlocation_nos": [str(core.first_value(self.profiles[i],
                        ("countlocation_no", "obs_id", "code"), "")) for i in indices],
                    "source_groups": [str(self.profiles[i].get("source_group", "CSD2022")) for i in indices],
                    "roles": [str(self.profiles[i].get("role", "")).upper() for i in indices]})
        self.duplicate_scope_audit = {
            "schema": "R1_15A2_DUPLICATE_DIRECTED_COUNT_SCOPE_QA_V1",
            "policy": duplicate_scope_policy,
            "all_observations_retained": True,
            "objective_weights_unchanged": True,
            "conflicting_same_source_groups": len(conflicts),
            "excluded_conflicting_driver_indices": sorted(excluded_driver_indices),
            "same_source_duplicate_groups": same_source_groups,
            "overlapping_directed_link_groups": physical_overlap,
            "overlapping_directed_link_group_count": len(physical_overlap),
            "apply_approval": "REQUIRED_SEPARATELY; DIAGNOSTIC_MODE_NEVER_APPROVES_APPLY"
        }
        if conflicts and duplicate_scope_policy == "FAIL":
            raise SupplyContractError("CONFLICTING_DUPLICATE_COUNT")
        self.drivers = []
        duplicate_physical = set()
        for index, row in enumerate(self.profiles):
            if str(row.get("role", "")).upper() != "CALIBRATION":
                continue
            if index in excluded_driver_indices:
                continue
            obs = number(row["observed"]); model = number(row["model"])
            if obs <= 0 or abs(model-obs) < policy.min_residual or core.geh(model, obs) < policy.min_geh:
                continue
            physical_scope = (self.key_groups[index],
                              str(row.get("source_group", "CSD2022")))
            if physical_scope in duplicate_physical:
                continue
            duplicate_physical.add(physical_scope)
            self.drivers.append(index)
        self.drivers.sort(key=lambda i: (-core.geh(number(profiles[i]["model"]), number(profiles[i]["observed"])), self.keys[i]))
        self.drivers = self.drivers[:policy.max_driver_profiles]
        self.edge_contrast = {i: defaultdict(float) for i in self.drivers}
        self.support = {i: 0.0 for i in self.drivers}
        self.market_counts = {i: 0 for i in self.drivers}
        self.probe_only_counts = {i: 0 for i in self.drivers}
        self.batches = []
        self.edge_max_multiplicity = Counter()
        self.profile_index_by_key = defaultdict(list)
        for i, key_group in enumerate(self.key_groups):
            for key in key_group:
                self.profile_index_by_key[key].append(i)

    def consume(self, path_rows, pathlink_rows, dseg):
        code = core.norm_code(dseg["code"])
        if code in {r["dseg"] for r in self.batches}:
            raise SupplyContractError("DUPLICATE_DSEG_BATCH")
        paths = {}
        for row in path_rows:
            pk = (core.norm_code(row.get("dseg_code", code)),
                  integer(row.get("OrigZoneNo")), integer(row.get("DestZoneNo")), integer(row.get("Index")))
            vol = number(row.get("Vol(AP)"), "path volume")
            if pk[0] != code or pk in paths or vol < 0:
                raise SupplyContractError("INVALID_OR_DUPLICATE_SAVED_PATH")
            paths[pk] = {"volume": vol, "links": {}}
        for row in pathlink_rows:
            pk = (core.norm_code(row.get("dseg_code", code)), integer(row.get("OrigZoneNo")),
                  integer(row.get("DestZoneNo")), integer(row.get("PathIndex")))
            if pk not in paths:
                raise SupplyContractError("ORPHAN_SAVED_PATH_LINK")
            idx = integer(row.get("Index"), "link index")
            if idx in paths[pk]["links"]:
                raise SupplyContractError("DUPLICATE_SAVED_PATH_LINK_INDEX")
            paths[pk]["links"][idx] = edge_key(row)
        markets = defaultdict(list)
        covered_volume = 0.0; total_volume = 0.0; covered = 0; positive = 0
        batch_hasher = hashlib.sha256()
        for pk, rec in sorted(paths.items()):
            v = rec["volume"]
            if v == 0:
                continue
            positive += 1; total_volume += v
            seq = tuple(edge for _, edge in sorted(rec["links"].items()))
            if not seq:
                if pk[1] == pk[2]:
                    covered += 1; covered_volume += v
                    batch_hasher.update(json.dumps([pk, v, []], separators=(",", ":")).encode())
                continue
            if any(a[2] != b[1] for a, b in zip(seq, seq[1:])):
                raise SupplyContractError("DISCONNECTED_OFFICIAL_PATH_LINK_SEQUENCE")
            covered += 1; covered_volume += v
            occurrences = Counter(seq)
            for edge, n in occurrences.items():
                self.edge_max_multiplicity[edge] = max(self.edge_max_multiplicity[edge], n)
            for edge, multiplicity in occurrences.items():
                for i in self.profile_index_by_key.get(edge, ()):
                    self.flow[i] += v * multiplicity
            markets[pk[:3]].append((seq, occurrences, v))
            batch_hasher.update(json.dumps([pk, v, seq], separators=(",", ":")).encode())
        for market, routes in markets.items():
            for i in self.drivers:
                group = self.key_groups[i]
                on = [r for r in routes if any(k in r[1] for k in group)]
                if not on:
                    continue
                off = [r for r in routes if not any(k in r[1] for k in group)]
                on_volume = sum(r[2] for r in on)
                off_volume = sum(r[2] for r in off)
                self.support[i] += sum(r[2] * sum(r[1].get(k, 0) for k in group) for r in on)
                self.market_counts[i] += 1
                if not off:
                    self.probe_only_counts[i] += 1
                on_edges = defaultdict(float); off_edges = defaultdict(float)
                for seq, occurrences, v in on:
                    for edge, n in occurrences.items():
                        if edge in self.editable: on_edges[edge] += v*n
                for seq, occurrences, v in off:
                    for edge, n in occurrences.items():
                        if edge in self.editable: off_edges[edge] += v*n
                for edge in set(on_edges) | set(off_edges):
                    contrast = on_edges[edge] / on_volume
                    if off_volume:
                        contrast -= off_edges[edge] / off_volume
                    self.edge_contrast[i][edge] += on_volume * contrast
        stats = {"dseg": code, "positive_paths": positive, "covered_paths": covered,
                 "path_coverage": covered/max(1, positive),
                 "volume_coverage": covered_volume/max(1e-30, total_volume),
                 "total_volume": total_volume, "covered_volume": covered_volume,
                 "official_route_batch_hash": batch_hasher.hexdigest()}
        self.batches.append(stats)
        if stats["path_coverage"] < self.policy.min_path_coverage or stats["volume_coverage"] < self.policy.min_path_volume_coverage:
            raise SupplyContractError("INSUFFICIENT_OFFICIAL_PATH_COVERAGE")
        return stats

    def finish(self):
        if not self.batches:
            raise SupplyContractError("NO_OFFICIAL_ROUTE_BATCH")
        parity = []
        for i, row in enumerate(self.profiles):
            model = number(row["model"])
            diff = abs(self.flow[i]-model)
            tol = max(self.policy.parity_absolute_tolerance, self.policy.parity_relative_tolerance*abs(model))
            parity.append({"id": str(core.first_value(row, ("countlocation_no", "obs_id", "code"))),
                           "role": row["role"], "model": model, "actual_path_flow": self.flow[i],
                           "absolute_diff": diff, "passes": diff <= tol})
        # Flow parity is a technical export gate, never a validation-target loss.
        if not all(row["passes"] for row in parity):
            raise SupplyContractError("ALL_PASSENGER_PATH_TO_PROFILE_FLOW_PARITY")
        return {"parent_hash": self.parent_hash, "observation_authority_hash": self.authority_hash,
                "assignment_path_hash": canonical_hash(self.batches), "dseg_batches": self.batches,
                "profile_parity": parity, "driver_count": len(self.drivers),
                "uses_reconstructed_routes": False}


def addval_prior(values, baseline, policy):
    if set(values) != set(baseline):
        raise SupplyContractError("ADDVAL_BASELINE_KEYS_CHANGED")
    return policy.prior_lambda * sum(((number(values[k])-number(baseline[k]))/policy.prior_sigma)**2 for k in values)


def check_addval_change(key, old, new, baseline, link, policy):
    old = number(old); new = number(new); baseline = number(baseline)
    if not link.get("eligible", False):
        raise SupplyContractError("UNAUTHORIZED_LINK")
    if abs((new-baseline)/policy.lattice-round((new-baseline)/policy.lattice)) > 1e-10:
        raise SupplyContractError("BASELINE_RELATIVE_INTEGER_LATTICE")
    if abs(new-old) > policy.max_step+1e-12 or abs(new-baseline) > policy.max_cumulative+1e-12:
        raise SupplyContractError("ADDVAL_STEP_OR_CUMULATIVE_BOUND")
    if not policy.absolute_min <= new <= policy.absolute_max:
        raise SupplyContractError("ADDVAL_ABSOLUTE_BOUND")
    # TCUR is NOT used for this minimum: congestion cannot justify negative cost.
    if number(link["t0_c_seconds"]) + 10*new < policy.minimum_cost_seconds:
        raise SupplyContractError("NONPOSITIVE_MINIMUM_GENERALIZED_COST")
    return {"key": list(key), "expected_old": old, "new": new, "delta": new-old,
            "equivalent_seconds": 10*(new-old)}


def propose_supply(collector, links, baseline_values, policy):
    authority = collector.finish()
    candidates = []; rejected = []; seen = set()
    for i in collector.drivers:
        row = collector.profiles[i]
        model = number(row["model"]); obs = number(row["observed"])
        coverage = collector.support[i]/max(model, 1e-30)
        if coverage < policy.min_attribution_coverage:
            rejected.append({"profile": i, "reason": "LOW_ATTRIBUTION_COVERAGE", "coverage": coverage})
            continue
        sign = 1 if model > obs else -1
        contrasts = collector.edge_contrast[i]
        kinds = [("PROFILE_BUNDLE_DETRACT" if sign > 0 else "PROFILE_BUNDLE_ATTRACT", sign,
                  [(k, v) for k, v in contrasts.items() if v > 1e-10])]
        if sign < 0:
            kinds.append(("BYPASS_BUNDLE_DETRACT", 1, [(k, -v) for k, v in contrasts.items() if v < -1e-10]))
        for kind, direction, scored in kinds:
            ordered = sorted(scored, key=lambda kv: (-kv[1], kv[0]))
            legal = []
            limit = min(policy.max_edges, int(policy.max_bundle_equivalent_seconds//10))
            for key, score in ordered:
                if key not in links or key not in baseline_values:
                    raise SupplyContractError("PATH_LINK_NOT_IN_STATE")
                old = links[key]["addval1"]
                try:
                    change = check_addval_change(key, old, old+direction*policy.lattice,
                                                 baseline_values[key], links[key], policy)
                except SupplyContractError as exc:
                    rejected.append({"key": list(key), "profile": i, "reason": str(exc)})
                    continue
                change["contrast_flow"] = score
                change["maximum_path_multiplicity"] = max(1, collector.edge_max_multiplicity[key])
                cost_bound = sum(abs(x["equivalent_seconds"])*x["maximum_path_multiplicity"] for x in legal)
                if cost_bound + abs(change["equivalent_seconds"])*change["maximum_path_multiplicity"] > policy.max_bundle_equivalent_seconds + 1e-12:
                    continue
                legal.append(change)
                if len(legal) == limit:
                    break
            # Integer backtracking shrinks support, never manufactures a half-unit.
            sizes = sorted({len(legal), max(1, len(legal)//2), 1}, reverse=True) if legal else []
            for size in sizes:
                changes = legal[:size]
                signature = canonical_hash(sorted([(x["key"], x["new"]) for x in changes]))
                if signature in seen:
                    continue
                seen.add(signature)
                candidates.append({"candidate_id": kind + "_" + signature[:12], "kind": kind,
                    "parent_hash": collector.parent_hash, "assignment_path_hash": authority["assignment_path_hash"],
                    "driver_profile": str(core.first_value(row, ("countlocation_no", "obs_id", "code"))),
                    "changes": changes, "coverage": coverage, "market_count": collector.market_counts[i],
                    "no_saved_alternative_markets": collector.probe_only_counts[i],
                    "confidence": "EXACT_SAVED_ROUTE_CONTRAST" if not collector.probe_only_counts[i] else "ACTUAL_PATH_PROBE_REQUIRES_NEW_ASSIGNMENT",
                    "equivalent_impedance_budget_seconds": sum(abs(x["equivalent_seconds"])*x["maximum_path_multiplicity"] for x in changes)})
                if len(candidates) >= policy.max_candidates:
                    return {"candidates": candidates, "skipped": rejected, "authority": authority}
    return {"candidates": candidates, "skipped": rejected, "authority": authority}


def shared_ledger(cal_rows, component_loss, values, baseline_values, policy, reference, cfg):
    observation_identity(cal_rows, include_model=True)
    cal = core.csd_metrics(cal_rows, "CALIBRATION", True)
    cal_metric = core.csd_objective_metric(cfg)
    cal_key = core.csd_objective_key(cfg)
    raw_cal = number(core.csd_objective_value(cal, cfg))
    raw_idp = number(component_loss, "component loss")
    if raw_idp < 0:
        raise SupplyContractError("NEGATIVE_COMPONENT_LOSS")
    weights = cfg.get("shared_objective", {})
    cal_weight = number(weights.get("cal_weight", 1.0)); idp_weight = number(weights.get("idp_weight", 1.0))
    scale = number(reference["cal_scale"])
    if cal_weight <= 0 or idp_weight < 0 or scale <= 0:
        raise SupplyContractError("INVALID_OBJECTIVE_REFERENCE")
    terms = {"CSD_CAL": cal_weight*raw_cal/scale, "COMPONENT_IDP": idp_weight*raw_idp,
             "ADDVAL1_PRIOR": addval_prior(values, baseline_values, policy)}
    return {"raw_cal": raw_cal, "raw_component_idp": raw_idp, "terms": terms,
            "cal_objective_metric": cal_metric, "cal_objective_key": cal_key,
            "cal_metrics": cal,
            "total": sum(terms.values()), "reference_hash": canonical_hash(reference),
            "validation_used": False}
