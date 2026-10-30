# -*- coding: utf-8 -*-
"""SUPPLYMIX1: ADDVAL1 route-choice lever inside the demand cycles.

Method (user, 2026-10-25): profiles that stay overloaded with a high GEH are a
route-choice problem, not a demand problem.  Paths that lead over the overloaded
counted section get a positive ADDVAL1 (slower, 1 ADDVAL1 = 10 generalized
seconds), the alternative paths that bypass it get a negative ADDVAL1 (more
attractive).  For an underloaded profile the signs are reversed.

The proposal machinery is the reviewed V2.4.9.13 sequence design
(``adapter.supply_design`` -> ``propose_sequence_supply``): per driver profile
the ON sequences (saved actual paths through the profile) and the OFF sequences
(the diverging/rejoining alternatives) are exact contiguous link runs of the
saved Visum paths.  SUPPLYMIX1 adds:

* the block runs after the Generation block of a demand cycle (every
  ``sp_every_n_cycles``), on the accepted parent of that cycle;
* one merged candidate per trial: the best branch of each selected driver
  profile (highest GEH first, one branch per profile, no link overlap) at one
  step of the lattice ladder; drivers = overloaded only while the Generation is
  in CATCH_UP (global volume is the Generation's job), both signs afterwards
  (``sp_drivers`` AUTO|OVERLOADED|BOTH);
* the trial assignment is the cold AMDY chain from the reset operation
  (``sp_cold_reset_position``, op 15) through the joint assignment (op 20),
  followed by the dynamic skims - demand matrices are untouched, the rollback
  recompute is therefore deterministic (hash-equal diagnostics);
* acceptance = the reviewed Supply route-choice policy (block gate scope
  SUPPLY_ADDVAL1 + shared counts objective must improve); the eligible trial is
  kept in place (no re-apply), a rejected one is retried once at a smaller step
  without the branches whose driver profile got worse, then rolled back;
* fail-safe: any error before a write -> recorded, demand cycle continues; any
  error after a write -> verified rollback, demand cycle continues; a rollback
  that restores the parameters but not the hash-identical diagnostics ->
  full-sequence recompute from the restored parameters (new verified parent).
"""
from __future__ import annotations

import copy
import functools
import math
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RELEASE = "R1_15A2_V24917_SUPPLYMIX_COSTFIX1_TG_COMPLETION_ISOLATION_20261030"
BLOCK = "SUPPLY_ADDVAL1"
RESET_TYPE = 9
GROUP_TYPE = 75

_STATE: Dict[str, Any] = {"installed": False, "blocks": 0, "trials": 0, "accepted": 0,
                          "errors": 0, "skipped": 0, "recovered": 0, "plans": 0,
                          "plan_fallbacks": 0, "events": []}


# ------------------------------------------------------------------ options
def options() -> Dict[str, Any]:
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options()
    return {
        "enabled": bool(o.get("sp_enabled", True)),
        "every_n": int(o.get("sp_every_n_cycles", 1)),
        "start_cycle": int(o.get("sp_start_cycle", 1)),
        "max_trials": int(o.get("sp_max_trials", 2)),
        "step_units": [int(x) for x in o.get("sp_step_units", [8, 4])],
        "max_groups": int(o.get("sp_max_groups", 12)),
        "max_edges": int(o.get("sp_max_edges", 120)),
        "min_driver_geh": float(o.get("sp_min_driver_geh", 10.0)),
        "drivers": str(o.get("sp_drivers", "AUTO")).upper(),
        "reset_position": int(o.get("sp_cold_reset_position", 15)),
        "min_attribution_coverage": float(o.get("sp_min_attribution_coverage", 0.5)),
    }


def _event(kind: str, **kw) -> None:
    _STATE["events"].append(dict(kind=kind, t=round(time.time(), 1), **kw))
    del _STATE["events"][:-100]


def due(outer_cycle: Optional[int], opts: Mapping[str, Any]) -> Tuple[bool, str]:
    if not opts.get("enabled"):
        return False, "DISABLED"
    if outer_cycle is None:
        return False, "NO_OUTER_CYCLE"
    c = int(outer_cycle)
    if c < int(opts["start_cycle"]):
        return False, "BEFORE_START_CYCLE"
    if (c - int(opts["start_cycle"])) % int(opts["every_n"]) != 0:
        return False, "NOT_DUE"
    return True, "EVERY_%d" % int(opts["every_n"])


# --------------------------------------------------------------- pure parts
def _f(v, default=0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if x == x else default


def _geh(m: float, o: float) -> float:
    s = m + o
    return 0.0 if s <= 0 else (2.0 * (m - o) ** 2 / s) ** 0.5


def _pid(row: Mapping[str, Any]) -> str:
    for k in ("countlocation_no", "obs_id", "code"):
        v = row.get(k)
        if v not in (None, ""):
            try:
                return str(int(float(v)))
            except (TypeError, ValueError):
                return str(v)
    return ""


def profile_table(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, float]]:
    out = {}
    for r in rows or []:
        if str(r.get("role", "CALIBRATION")).upper() != "CALIBRATION":
            continue
        obs = _f(r.get("observed"))
        if obs <= 0:
            continue
        m = _f(r.get("model"))
        out[_pid(r)] = {"model": m, "observed": obs, "geh": _geh(m, obs),
                        "sign": 1 if m > obs else -1, "weight": _f(r.get("profile_weight"), 1.0)}
    return out


def driver_mode(opts: Mapping[str, Any], phase: Optional[str]) -> str:
    mode = str(opts.get("drivers", "AUTO")).upper()
    if mode == "AUTO":
        return "OVERLOADED" if str(phase or "").upper() == "CATCH_UP" else "BOTH"
    return mode


def select_groups(design: Mapping[str, Any], table: Mapping[str, Mapping[str, float]],
                  opts: Mapping[str, Any], mode: str, excluded_profiles=()) -> List[Dict[str, Any]]:
    """One branch ladder per driver profile, highest GEH first, disjoint links."""
    by_group: Dict[str, List[Mapping[str, Any]]] = {}
    for c in design.get("candidates", []) or []:
        by_group.setdefault(str(c.get("backtracking_group_id")), []).append(c)
    rows = []
    excluded = {str(x) for x in excluded_profiles}
    for gid, ladder in by_group.items():
        pid = str(ladder[0].get("driver_profile"))
        try:
            pid = str(int(float(pid)))
        except (TypeError, ValueError):
            pass
        prof = table.get(pid)
        if prof is None or pid in excluded:
            continue
        if prof["geh"] < float(opts["min_driver_geh"]):
            continue
        if mode == "OVERLOADED" and prof["sign"] <= 0:
            continue
        keys = {tuple(int(x) for x in ch["key"]) for ch in ladder[0].get("changes", [])}
        rank = min(int(c.get("backtracking_group_rank", 10 ** 6)) for c in ladder)
        rows.append({"group_id": gid, "driver_profile": pid, "geh": prof["geh"],
                     "sign": prof["sign"], "rank": rank, "keys": keys,
                     "ladder": sorted(ladder, key=lambda c: -int(c.get("step_units", 0)))})
    rows.sort(key=lambda r: (-r["geh"] * 1.0, r["rank"], r["group_id"]))
    chosen, used, profiles, edges = [], set(), set(), 0
    for r in rows:
        if len(chosen) >= int(opts["max_groups"]):
            break
        if r["driver_profile"] in profiles or (r["keys"] & used):
            continue
        if edges + len(r["keys"]) > int(opts["max_edges"]):
            continue
        chosen.append(r)
        used |= r["keys"]
        profiles.add(r["driver_profile"])
        edges += len(r["keys"])
    return chosen


def addval_integer(adapter) -> Dict[str, Any]:
    """Visum value type of Link ADDVAL1 (1 = integer, 2 = double).

    INTADDVAL1 (live 26.10. cycles 2-10): every SUPPLYMIX trial failed ADDVAL1_READBACK_FAILED -
    the sealed supply lattice is 0.5 ADDVAL (5 s) but Visum stores network AddValue as an
    integer (Zones.ADDVAL1 ValueType 1 in COM_API_PREFLIGHT.json), so a 0.5 step reads back
    rounded.  Unknown type -> integer (integer values are valid for both types).
    """
    try:
        vt = int(adapter.visum.Net.Links.Attributes.ItemByKey("ADDVAL1").ValueType)
        return {"value_type": vt, "integer": vt != 2, "source": "COM_ATTRIBUTE_VALUETYPE"}
    except Exception as exc:
        return {"value_type": None, "integer": True, "source": "FALLBACK_INTEGER",
                "error": "%s:%s" % (type(exc).__name__, str(exc)[:200])}


def snap_integer(candidate: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Round every ADDVAL1 change away from zero to a whole ADDVAL unit (0.5 -> 1, 2.5 -> 3)."""
    if candidate is None:
        return None
    from r1_15a2_supply import canonical_hash
    rows = []
    for r in candidate["changes"]:
        old = float(r["expected_old"])
        d = float(r["new"]) - old
        if abs(d) < 1e-12:
            continue
        step = math.copysign(max(1.0, math.ceil(abs(d) - 1e-9)), d)
        new = float(round(old)) + step if abs(old - round(old)) < 1e-9 else old + step
        rows.append(dict(r, new=new, delta=new - old, equivalent_seconds=10.0 * (new - old),
                         v24917_integer_snap_from=float(r["new"])))
    if not rows:
        return None
    out = dict(candidate, changes=rows)
    sig = canonical_hash([(r["key"], r["new"]) for r in rows])
    out["candidate_id"] = "SUPPLYMIX_" + sig[:12]
    out["positive_edges"] = sum(1 for r in rows if r["delta"] > 0)
    out["negative_edges"] = sum(1 for r in rows if r["delta"] < 0)
    out["v24917_addval_integer_snap"] = True
    return out


def merged_candidate(groups: Sequence[Mapping[str, Any]], unit: int, design: Mapping[str, Any],
                     parent_hash: str) -> Optional[Dict[str, Any]]:
    """Merge the ladder member at ``unit`` (or the largest smaller step) of every group."""
    from r1_15a2_supply import canonical_hash
    changes, members = {}, []
    for g in groups:
        pick = None
        for c in g["ladder"]:
            if int(c.get("step_units", 0)) <= int(unit):
                pick = c
                break
        if pick is None:
            continue
        for ch in pick.get("changes", []):
            k = tuple(int(x) for x in ch["key"])
            if k in changes:
                raise RuntimeError("V24917_SUPPLYMIX_INTERNAL_OVERLAP")
            changes[k] = {"key": list(k), "expected_old": float(ch["expected_old"]),
                          "new": float(ch["new"]), "delta": float(ch["new"]) - float(ch["expected_old"]),
                          "equivalent_seconds": 10.0 * (float(ch["new"]) - float(ch["expected_old"]))}
        members.append({"group_id": g["group_id"], "driver_profile": g["driver_profile"],
                        "driver_geh": round(g["geh"], 3), "driver_sign": g["sign"],
                        "candidate_id": pick.get("candidate_id"), "step_units": int(pick.get("step_units", 0)),
                        "edges": len(pick.get("changes", []))})
    if not changes:
        return None
    rows = [changes[k] for k in sorted(changes)]
    sig = canonical_hash([(r["key"], r["new"]) for r in rows])
    return {"candidate_id": "SUPPLYMIX_" + sig[:12], "kind": "V24917_SUPPLYMIX_MERGED_BRANCHES",
            "parent_hash": parent_hash,
            "assignment_path_hash": (design.get("authority") or {}).get("assignment_path_hash"),
            "changes": rows, "members": members, "step_units": int(unit),
            "positive_edges": sum(1 for r in rows if r["delta"] > 0),
            "negative_edges": sum(1 for r in rows if r["delta"] < 0)}



def cost_safe_merged_candidate(design: Mapping[str, Any],
                               table: Mapping[str, Mapping[str, float]],
                               opts: Mapping[str, Any], mode: str, unit: int,
                               parent_hash: str, links: Mapping, baseline: Mapping,
                               supply_policy: Any, integer_addval: bool,
                               excluded_profiles=()) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Choose whole, proven sequence branches whose FINAL ADDVAL1 is legal.

    The exact saved-route design may contain a -0.5 ADDVAL1 proposal that is
    legal for a 7-second t0 link.  Integer Visum ADDVAL1 would write -1, making
    its generalized cost negative.  Do not round a designed half-unit AWAY from
    zero: it is a different physical intervention, not an approved backtrack.

    Prefer a smaller *already designed* step or another proved branch for the
    same profile (e.g. penalize the OFF bypass instead of discounting a very
    short ON link). Never invent a path, split its contiguous sequence, or
    compensate by adding an unrelated negative cost somewhere else.
    """
    from r1_15a2_supply import SupplyContractError, check_addval_change

    by_group: Dict[str, List[Mapping[str, Any]]] = {}
    for candidate in design.get("candidates", []) or []:
        by_group.setdefault(str(candidate.get("backtracking_group_id")), []).append(candidate)
    excluded = {str(p) for p in excluded_profiles}
    pool = []
    for gid, ladder in by_group.items():
        pid = str(ladder[0].get("driver_profile"))
        try:
            pid = str(int(float(pid)))
        except (ValueError, TypeError):
            pass
        prof = table.get(pid)
        if not prof or pid in excluded or prof["geh"] < float(opts["min_driver_geh"]):
            continue
        if mode == "OVERLOADED" and prof["sign"] <= 0:
            continue
        rank = min(int(row.get("backtracking_group_rank", 10**6)) for row in ladder)
        pool.append((pid, gid, prof, rank,
                     sorted(ladder, key=lambda row: -int(row.get("step_units", 0)))))
    pool.sort(key=lambda r: (-r[2]["geh"], r[3], r[1]))

    rejected: Dict[str, int] = {}
    examples: List[Dict[str, Any]] = []

    def reject(reason, pid, gid, member=None, key=None, t0=None, new=None):
        rejected[reason] = rejected.get(reason, 0) + 1
        if len(examples) < 24:
            record = {"profile": pid, "group_id": gid, "reason": reason}
            if member is not None:
                record["step_units"] = int(member.get("step_units", 0))
            if key is not None:
                record["key"] = list(key)
            if t0 is not None:
                record["t0_c_seconds"] = t0
            if new is not None:
                record["proposed_addval1"] = new
            examples.append(record)

    chosen, used, profiles = [], set(), set()
    max_groups, max_edges = int(opts["max_groups"]), int(opts["max_edges"])
    for pid, gid, prof, rank, ladder in pool:
        if len(chosen) >= max_groups:
            break
        if pid in profiles:
            continue
        for member in ladder:
            step = int(member.get("step_units", 0))
            if step > int(unit) or step <= 0:
                continue
            changes = member.get("changes") or []
            if not changes:
                reject("EMPTY_PROVED_BRANCH", pid, gid, member)
                continue
            keys = [tuple(int(v) for v in row["key"]) for row in changes]
            if len(set(keys)) != len(keys):
                reject("DUPLICATE_PROVED_LINK", pid, gid, member)
                continue
            if set(keys) & used or len(used) + len(keys) > max_edges:
                reject("PROVED_BRANCH_OVERLAP_OR_BUDGET", pid, gid, member)
                continue
            violation = False
            for key, change in zip(keys, changes):
                link = links.get(key)
                if link is None or key not in baseline:
                    reject("MISSING_PARENT_LINK_OR_BASELINE", pid, gid, member, key)
                    violation = True
                    break
                old = float(change["expected_old"])
                new = float(change["new"])
                if abs(float(link["addval1"]) - old) > 1e-9:
                    reject("STALE_PROVED_ADDVAL1", pid, gid, member, key)
                    violation = True
                    break
                # Integer quantization is a METHOD constraint, not a license to
                # increase the proposed discount beyond its proved amplitude.
                if integer_addval and (abs(new - round(new)) > 1e-9 or
                                       abs(old - round(old)) > 1e-9):
                    reject("INTEGER_ADDVAL1_FRACTIONAL_STEP", pid, gid, member, key,
                           link.get("t0_c_seconds"), new)
                    violation = True
                    break
                try:
                    check_addval_change(key, old, new, baseline[key], link, supply_policy)
                except SupplyContractError as exc:
                    reject(str(exc), pid, gid, member, key, link.get("t0_c_seconds"), new)
                    violation = True
                    break
            if violation:
                continue
            chosen.append({"group_id": gid, "driver_profile": pid, "geh": prof["geh"],
                           "sign": prof["sign"], "rank": rank, "keys": set(keys),
                           "ladder": [member]})
            used.update(keys)
            profiles.add(pid)
            break

    candidate = merged_candidate(chosen, int(unit), design, parent_hash)
    # This is an invariant: the changes are the exact safe rows from complete
    # source branches. No floor correction or silent edge deletion is permitted.
    if candidate is not None and integer_addval:
        if any(abs(float(row["new"]) - round(float(row["new"]))) > 1e-9
               for row in candidate["changes"]):
            raise SupplyContractError("COSTFIX1_NONINTEGER_SELECTED_SUPPLY_CANDIDATE")
        candidate = snap_integer(candidate)
    audit = {"release": RELEASE, "step_limit_units": int(unit),
             "candidate_groups_examined": len(pool), "candidate_groups_selected": len(chosen),
             "selected_profiles": [row["driver_profile"] for row in chosen],
             "selected_steps": [{"profile": row["driver_profile"], "group_id": row["group_id"],
                                 "step_units": int(row["ladder"][0]["step_units"])} for row in chosen],
             "rejected_reasons": rejected, "rejected_examples": examples,
             "full_proved_branches_only": True, "integer_snapping_beyond_proved_step": False,
             "positive_generalized_link_cost_guard": True}
    return candidate, audit


def worsened_profiles(members, before: Mapping[str, Mapping[str, float]],
                      after: Mapping[str, Mapping[str, float]]) -> List[str]:
    out = []
    for m in members:
        p = m["driver_profile"]
        b, a = before.get(p), after.get(p)
        if b is None or a is None:
            continue
        # wrong direction = the driver got worse on the SAME side; an overshoot (sign flip) is
        # a too-large step and is exactly what the smaller next step corrects
        if a["geh"] > b["geh"] + 1e-9 and a["sign"] == b["sign"]:
            out.append(p)
    return out


def cold_supply_plan(base_plan: Mapping[str, Any], cfg: Mapping[str, Any], reset_position: int) -> Dict[str, Any]:
    """SUPPLY plan = reset op .. joint assignment (all originally active) + groups."""
    inventory = list(base_plan.get("inventory") or [])
    by_pos = {int(r["no"]): r for r in inventory}
    active = {int(r["no"]) for r in inventory if int(r.get("active", 0))}
    reasons = []
    approved = [int(v) for v in (base_plan.get("approved_assignment_positions") or [])]
    if not approved:
        approved = [int(op.get("no")) for op in ((cfg.get("supply") or {}).get("assignment_operations") or [])
                    if op.get("no") is not None]
    if not approved:
        reasons.append("NO_APPROVED_ASSIGNMENT")
    reset = by_pos.get(int(reset_position))
    if reset is None:
        reasons.append("RESET_OPERATION_MISSING:%d" % reset_position)
    elif int(reset.get("type", -1)) != RESET_TYPE:
        reasons.append("RESET_OPERATION_TYPE:%s" % reset.get("type"))
    elif int(reset_position) not in active:
        reasons.append("RESET_OPERATION_INACTIVE")
    last = max(approved) if approved else None
    if last is not None and reset is not None and last <= int(reset_position):
        reasons.append("RESET_NOT_BEFORE_ASSIGNMENT")
    if last is not None and last not in active:
        reasons.append("APPROVED_ASSIGNMENT_INACTIVE")
    if reasons:
        out = dict(base_plan)
        out["v24917_supplymix_plan"] = {"applied": False, "reasons": reasons, "release": RELEASE}
        return out
    groups = {p for p in active if int(by_pos[p].get("type", -1)) == GROUP_TYPE}
    selected = {p for p in active if int(reset_position) <= p <= last} | groups
    out = dict(base_plan)
    out.update({
        "mode": "V24917_SUPPLYMIX_COLD_ASSIGNMENT_CHAIN",
        "optimized": True,
        "fallback_reason": None,
        "selected_operation_positions": sorted(selected),
        "original_active_operation_positions": sorted(active),
        "skipped_originally_active_positions": sorted(active - selected),
        "approved_assignment_positions": sorted(approved),
        "v24917_supplymix_plan": {"applied": True, "release": RELEASE, "reset_position": int(reset_position),
                                  "joint_assignment": last,
                                  "reason": "COLD_CHAIN_MAKES_ROLLBACK_RECOMPUTE_DETERMINISTIC"},
    })
    return out


def _wrap_plan(orig):
    @functools.wraps(orig)
    def phase_recompute_plan(visum, cfg, block):
        plan = orig(visum, cfg, block)
        if str(block).upper() != BLOCK:
            return plan
        opts = options()
        if not opts["enabled"]:
            return plan
        if not plan.get("inventory"):
            try:
                import r1_15a2_com_compat as com
                plan = dict(plan)
                plan["inventory"] = [{k: v for k, v in r.items() if k != "object"}
                                     for r in com.operation_rows(visum)]
            except Exception as exc:
                _event("PLAN_INVENTORY_FAILED", error=str(exc)[:200])
                raise
        out = cold_supply_plan(plan, cfg, opts["reset_position"])
        info = out.get("v24917_supplymix_plan", {})
        if info.get("applied"):
            _STATE["plans"] += 1
        else:
            # never run a warm op-20-only supply recompute: the rollback would not be exact
            _STATE["plan_fallbacks"] += 1
            from r1_15a2_supply import SupplyContractError
            raise SupplyContractError("V24917_SUPPLYMIX_COLD_PLAN_UNAVAILABLE:" + ";".join(info.get("reasons", [])))
        return out
    phase_recompute_plan.__r1_supplymix__ = True
    return phase_recompute_plan


# --------------------------------------------------------------- the block
def _supply_block_impl(ctrl, base, tx, adapter, cfg, folder, control, state, diag, anchors, reference,
                 policy, outer_cycle, opts) -> Tuple[bool, Dict, Dict, Dict, Dict]:
    """Return a verified state or raise. Stops and I/O errors propagate after recovery."""
    from r1_15a2_supply import SupplyContractError
    import r1_15a2_perf_v24917 as perf
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    sup_cfg = ctrl._generation_counts_cfg(cfg, outer_cycle=outer_cycle)
    sup_cfg["runtime_acceptance_scope"] = BLOCK
    sup_cfg["runtime_acceptance_supply_cycle"] = int(outer_cycle)
    rec: Dict[str, Any] = {"release": RELEASE, "outer_cycle": outer_cycle, "status": "DESIGNING",
                           "attempts": [], "options": dict(opts), "search_complete": False}
    baseline_value = base.ledger(diag, state, anchors, policy, reference, sup_cfg)
    rec["objective_before"] = baseline_value
    try:
        import r1_15a2_demand_policy_v1 as dp
        ph = dp.catchup_phase(cfg, diag)
    except Exception:
        ph = None
    phase = ph[0] if ph else None
    mode = driver_mode(opts, phase)
    rec.update(generation_phase=phase, driver_mode=mode)
    before_table = profile_table(diag["d12"]["rows"])
    baseline_diag_hash = base.diagnostic_hash(diag)
    applied = None
    recovery_candidate = None
    recovery_in_progress = False

    def own(candidate):
        nonlocal recovery_candidate
        changes = {tuple(r["key"]): dict(r) for r in (recovery_candidate or {}).get("changes", [])}
        for row in candidate.get("changes", []):
            changes.setdefault(tuple(row["key"]), dict(row))
        recovery_candidate = dict(candidate, changes=list(changes.values()))

    def safe_save(primary):
        try:
            save()
        except Exception as io_exc:
            rec.setdefault("evidence_write_errors", []).append(repr(io_exc))
            if hasattr(primary, "add_note"):
                primary.add_note("SUPPLYMIX_EVIDENCE_WRITE_FAILED:" + repr(io_exc))


    def save():
        rec["elapsed_s"] = round(time.time() - t0, 1)
        base.atomic_json(folder / "SUPPLYMIX_BLOCK_RESULT.json", rec)

    try:
        with ctrl.adapter_config_scope(adapter, sup_cfg):
            try:
                control.checkpoint("V24917_SUPPLYMIX_DESIGN", force=True)
                # The path epoch is frozen while the Generation keeps adding demand, so the
                # saved-path support of a profile lags its live volume (coverage = support /
                # live model).  Inside the demand loop the proposal accepts a lower coverage;
                # every candidate is still judged by a fresh Visum assignment.
                old_policy = getattr(adapter, "policy", None)
                cov = float(opts.get("min_attribution_coverage", 0.5))
                # max_candidates counts ladder members (up to 5 steps per branch): the reviewed
                # 40 leaves only ~8 branches, so one block could never see sp_max_groups profiles.
                if old_policy is not None and hasattr(old_policy, "min_attribution_coverage"):
                    import dataclasses
                    repl = {}
                    if cov < float(old_policy.min_attribution_coverage):
                        repl["min_attribution_coverage"] = cov
                    want = min(200, 5 * int(opts.get("max_groups", 12)))
                    if int(getattr(old_policy, "max_candidates", want)) < want:
                        repl["max_candidates"] = want
                    if repl:
                        adapter.policy = dataclasses.replace(old_policy, **repl)
                        rec["design_policy_override"] = repl
                try:
                    design = adapter.supply_design(diag, folder / "DESIGN", state)
                finally:
                    if old_policy is not None:
                        adapter.policy = old_policy
                # CostFix1: read the SAME live link t0/ADDVAL1 values which the
                # adapter's apply_supply contract will use. This is before any
                # writes, so unsafe proposals can be skipped without rollback.
                link_cost_basis = adapter.read_links()
                baseline_addval = getattr(adapter, "baseline_addval", None)
                supply_policy = getattr(adapter, "policy", None)
                if baseline_addval is None or supply_policy is None:
                    raise SupplyContractError("COSTFIX1_LINK_COST_AUTHORITY_MISSING")
                if adapter.snapshot() != state:
                    raise SupplyContractError("COSTFIX1_LINK_READ_CHANGED_PARENT")
                skipped = {}
                for row in design.get("skipped", []) or []:
                    skipped[str(row.get("reason"))] = skipped.get(str(row.get("reason")), 0) + 1
                rec["design_skipped_reasons"] = skipped
            except BaseException as exc:
                if not isinstance(exc, Exception) or isinstance(exc, (base.UserStopRequested, base.TimeBudgetReached)):
                    raise
                if adapter.snapshot() != state:
                    raise SupplyContractError("V24917_SUPPLYMIX_DESIGN_CHANGED_MODEL") from exc
                rec.update(status="DESIGN_FAILED_NO_WRITE", error=str(exc)[:2000],
                           traceback=traceback.format_exc()[-4000:])
                _STATE["errors"] += 1
                save()
                return False, state, diag, baseline_value, rec
            groups = select_groups(design, before_table, opts, mode)
            rec["design_candidates"] = len(design.get("candidates", []) or [])
            rec["selected_groups"] = [{k: v for k, v in g.items() if k not in ("keys", "ladder")} for g in groups]
            if not groups:
                rec["status"] = "NO_DRIVER_BRANCH"
                rec["search_complete"] = True
                _STATE["skipped"] += 1
                save()
                return False, state, diag, baseline_value, rec
            excluded: set = set()
            av_type = addval_integer(adapter)
            rec["addval1_value_type"] = av_type
            rec["costfix1"] = {"enabled": True, "trials": [],
                               "basis": "LIVE_T0_C_PLUS_FINAL_INTEGER_ADDVAL1",
                               "alternate_proved_branches_allowed": True}
            units = list(opts["step_units"])[: int(opts["max_trials"])]
            attempted_candidate_ids = set()
            for ordinal, unit in enumerate(units, start=1):
                cand, cost_audit = cost_safe_merged_candidate(
                    design, before_table, opts, mode, unit, state["state_hash"],
                    link_cost_basis, baseline_addval, supply_policy, av_type["integer"],
                    excluded_profiles=excluded)
                rec["costfix1"]["trials"].append(cost_audit)
                if cand is None:
                    rec["stop_reason"] = "NO_COST_SAFE_PROVED_BRANCH"
                    break
                if cand["candidate_id"] in attempted_candidate_ids:
                    rec["stop_reason"] = "DUPLICATE_COST_SAFE_CANDIDATE"
                    break
                attempted_candidate_ids.add(cand["candidate_id"])
                tfolder = folder / ("TRY_%02d" % ordinal)
                tfolder.mkdir(parents=True, exist_ok=True)
                base.atomic_json(tfolder / "SUPPLYMIX_CANDIDATE.json", cand)
                attempt = {"trial": ordinal, "step_units": unit, "addval1_step": unit * 0.5,
                           "generalized_seconds_step": unit * 5.0, "candidate_id": cand["candidate_id"],
                           "edges": len(cand["changes"]), "positive_edges": cand["positive_edges"],
                           "negative_edges": cand["negative_edges"], "members": cand["members"]}
                try:
                    if applied is not None:
                        tx.restore_supply_parameters(adapter, state, applied["changes"], tfolder / "RESTORE_PARENT")
                        applied = None
                    if adapter.snapshot() != state:
                        raise SupplyContractError("V24917_SUPPLYMIX_PARENT_CHANGED")
                    # the path proof is bound to the parent; reapply it after a parameter restore
                    adapter.supply_path_proof = dict(adapter.supply_path_proof or {},
                                                     parent_hash=state["state_hash"])
                    signature = base._candidate_signature(BLOCK, cand, [])
                    if hasattr(adapter, "begin_candidate_readback_context"):
                        adapter.begin_candidate_readback_context(
                            state["state_hash"], BLOCK, signature, parameter_evidence={"candidate": cand})
                    control.checkpoint("TRIAL_APPLY", block=BLOCK, candidate=signature)
                    own(cand)                           # retained after parameter-only restoration
                    applied = cand                      # rollback scope even for a half-written candidate
                    adapter.apply_supply(cand, state, tfolder)
                    control.checkpoint("TRIAL_ASSIGNMENT", block=BLOCK)
                    gap = base._assign_candidate(adapter, tfolder / "ASSIGNMENT", BLOCK)
                    after = adapter.snapshot()
                    base.assert_freeze(state, after, BLOCK, rows=[], candidate=cand, cfg=sup_cfg)
                    control.checkpoint("TRIAL_DIAGNOSTICS", block=BLOCK)
                    with perf.deferred_archives() as deferred:
                        after_diag = adapter.diagnostics(tfolder / "DIAGNOSTICS", "AFTER")
                        if adapter.snapshot() != after:
                            raise SupplyContractError("TRIAL_DIAGNOSTICS_CHANGED_MODEL")
                        after_value = base.ledger(after_diag, after, anchors, policy, reference, sup_cfg)
                        decision = adapter.block_gate(BLOCK, diag, after_diag, [])
                        improvement = baseline_value["total"] - after_value["total"]
                        decision["shared_ledger_before"] = baseline_value
                        decision["shared_ledger_after"] = after_value
                        decision["shared_objective_improvement"] = improvement
                        minimum = base.number(sup_cfg.get("shared_objective", {}).get("minimum_improvement", 1e-8))
                        if improvement <= minimum:
                            decision["accepted"] = False
                            decision.setdefault("reasons", []).append("SHARED_OBJECTIVE_NOT_IMPROVED")
                        base._write_acceptance(tfolder / "ACCEPTANCE.json", decision)
                        deferred.keep = bool(decision.get("accepted"))
                except BaseException as exc:
                    attempt.update(status="FAILED", error=str(exc)[:2000])
                    rec["attempts"].append(attempt)
                    safe_save(exc)
                    _STATE["errors"] += 1
                    if recovery_candidate is not None:
                        recovery_in_progress = True
                        return _rollback_or_recover(ctrl, base, tx, adapter, sup_cfg, folder, control, state, diag,
                                                    baseline_value, baseline_diag_hash, recovery_candidate, anchors, reference,
                                                    policy, rec, exc, save)
                    if not isinstance(exc, Exception) or isinstance(exc, (base.UserStopRequested, base.TimeBudgetReached)):
                        raise
                    rec.update(status="TRIAL_FAILED_BEFORE_WRITE", error=str(exc)[:2000])
                    save()
                    return False, state, diag, baseline_value, rec
                _STATE["trials"] += 1
                after_table = profile_table(after_diag["d12"]["rows"])
                drivers = []
                for m in cand["members"]:
                    p = m["driver_profile"]
                    b, a = before_table.get(p, {}), after_table.get(p, {})
                    drivers.append({"profile": p, "geh_before": round(b.get("geh", 0.0), 3),
                                    "geh_after": round(a.get("geh", 0.0), 3),
                                    "model_before": round(b.get("model", 0.0), 1),
                                    "model_after": round(a.get("model", 0.0), 1),
                                    "observed": round(b.get("observed", 0.0), 1)})
                attempt.update(status="ELIGIBLE" if decision.get("accepted") else "REJECTED", gap=gap,
                               decision_reasons=list(decision.get("reasons", [])),
                               objective_after=after_value, drivers=drivers)
                rec["attempts"].append(attempt)
                save()
                if decision.get("accepted"):
                    transition = None
                    if hasattr(adapter, "accepted_state_changed"):
                        transition = adapter.accepted_state_changed(
                            after, after_diag, reason="V24917_SUPPLYMIX_ACCEPTED_ADDVAL1_STATE", phase="SUPPLY")
                    rec.update(status="ACCEPTED", accepted_trial=ordinal, adopted_in_place=True,
                               objective_after=after_value, path_epoch_transition=transition, search_complete=True,
                               addval1_changes=len(cand["changes"]))
                    save()
                    _event("ACCEPTED", cycle=outer_cycle, trial=ordinal, edges=len(cand["changes"]))
                    recovery_candidate = None
                    _STATE["accepted"] += 1
                    return True, after, after_diag, after_value, rec
                excluded |= set(worsened_profiles(cand["members"], before_table, after_table))
                attempt["excluded_after_trial"] = sorted(excluded)
            # nothing accepted: back to the exact parent
            if recovery_candidate is not None:
                try:
                    with base.recovery_scope(control, "V24917_SUPPLYMIX_ROLLBACK"):
                        rb, rolled = base._rollback_candidate(adapter, BLOCK, state, baseline_diag_hash,
                                                              folder / "ROLLBACK", [], recovery_candidate, diag)
                    import r1_15a2_parent_equivalence_v24917 as eq
                    live_state = adapter.snapshot()
                    proof = eq.verify_parent(adapter, state, live_state, diag, rolled)
                    if not proof["passes"]:
                        raise SupplyContractError("GENFIX2_SUPPLYMIX_ROLLBACK_NOT_EQUIVALENT")
                    eq.rebind_verified_parent(adapter, live_state, rolled)
                    diag = rolled
                    state = live_state
                    baseline_value = base.ledger(diag, state, anchors, policy, reference, sup_cfg)
                    recovery_candidate = None
                    base.atomic_json(folder / "ROLLBACK_SUMMARY.json", dict(rb, genfix2_proof=proof))
                except BaseException as exc:
                    if recovery_candidate is None:
                        raise
                    recovery_in_progress = True
                    return _rollback_or_recover(ctrl, base, tx, adapter, sup_cfg, folder, control, state, diag,
                                                baseline_value, baseline_diag_hash, recovery_candidate, anchors, reference,
                                                policy, rec, exc, save, already_tried=True)
            rec["status"] = ("NO_COST_SAFE_CANDIDATE" if
                             rec.get("stop_reason") == "NO_COST_SAFE_PROVED_BRANCH" and
                             not rec["attempts"] else "NO_ACCEPTED_TRIAL")
            # Exhausting this particular legal lattice is not a proof of global
            # stationarity or permission to change the impedance floor.
            rec["search_complete"] = False if rec["status"] == "NO_COST_SAFE_CANDIDATE" else True
            rec["stationarity_confirmed"] = False if not rec["search_complete"] else rec.get("stationarity_confirmed", False)
            save()
            return False, state, diag, baseline_value, rec

    except BaseException as exc:
        rec.update(status="FAILED", error=str(exc)[:2000], search_complete=False,
                   stationarity_confirmed=False)
        safe_save(exc)
        if recovery_candidate is not None and not recovery_in_progress:
            recovery_in_progress = True
            _rollback_or_recover(ctrl, base, tx, adapter, sup_cfg, folder, control, state, diag,
                                 baseline_value, baseline_diag_hash, recovery_candidate, anchors, reference,
                                 policy, rec, exc, save)
        raise


def supply_block(ctrl, base, tx, adapter, cfg, folder, control, state, diag, anchors, reference,
                 policy, outer_cycle, opts):
    import r1_15a2_parent_equivalence_v24917 as eq
    with eq.parent_scope(adapter, state, folder):
        return _supply_block_impl(ctrl, base, tx, adapter, cfg, folder, control, state, diag,
                                 anchors, reference, policy, outer_cycle, opts)


def _rollback_or_recover(ctrl, base, tx, adapter, sup_cfg, folder, control, state, diag, baseline_value,
                         baseline_diag_hash, applied, anchors, reference, policy, rec, exc, save,
                         already_tried=False):
    """Restore and prove the parent. Recovery is NEVER an acceptance path."""
    from r1_15a2_supply import SupplyContractError
    import r1_15a2_parent_equivalence_v24917 as eq
    stop = (not isinstance(exc, Exception)) or isinstance(exc, (base.UserStopRequested, base.TimeBudgetReached))
    rb_error = exc if already_tried else None
    if not already_tried:
        try:
            with base.recovery_scope(control, "V24917_SUPPLYMIX_ROLLBACK_AFTER_ERROR"):
                rb, rolled = base._rollback_candidate(adapter, BLOCK, state, baseline_diag_hash,
                                                     folder / "ROLLBACK_AFTER_ERROR", [], applied, diag)
                live = adapter.snapshot()
                if rolled is diag:
                    rolled = adapter.diagnostics(folder / "ROLLBACK_LIVE_PROOF", "ROLLBACK")
                proof = eq.verify_parent(adapter, state, live, diag, rolled)
                if adapter.snapshot() != live or not proof["passes"]:
                    raise SupplyContractError("GENFIX2_SUPPLYMIX_ROLLBACK_NOT_EQUIVALENT")
        except BaseException as e2:
            rb_error = e2
        else:
            eq.rebind_verified_parent(adapter, live, rolled)
            value = base.ledger(rolled, live, anchors, policy, reference, sup_cfg)
            rec.update(status="TRIAL_FAILED_ROLLBACK_VERIFIED", error=str(exc)[:2000],
                       parent_equivalence=proof, objective_after=value, search_complete=False,
                       stationarity_confirmed=False)
            # All model work is complete before fallible logging. An I/O failure
            # must not trigger a second assignment or hide the primary exception.
            try:
                base.atomic_json(folder / "ROLLBACK_SUMMARY.json", rb)
                save()
            except Exception as io_exc:
                if hasattr(exc, "add_note"):
                    exc.add_note("ROLLBACK_LOG_WRITE_FAILED:" + repr(io_exc))
                raise exc
            if stop or isinstance(exc, OSError):
                raise exc
            return False, state if live == state else live, rolled, value, rec
    rec["rollback_error"] = str(rb_error)[:2000]
    with base.recovery_scope(control, "V24917_SUPPLYMIX_FULL_RECOVERY"):
        live = adapter.snapshot()
        changes = [{"key": [int(x) for x in k.split("|")]} for k, v in state["addval1"].items()
                   if live.get("addval1", {}).get(k) != v]
        if changes:
            tx.restore_supply_parameters(adapter, state, changes, folder / "RECOVERY_RESTORE")
        live = adapter.snapshot()
        for name in set(state) | set(live):
            if name in ("matrices", "matrix_hash", "state_hash"):
                continue
            if live.get(name) != state.get(name):
                raise SupplyContractError("GENFIX2_SUPPLYMIX_RECOVERY_PARAMETER_MISMATCH:" + name) from rb_error
        gap = base._assign_candidate(adapter, folder / "RECOVERY_FULL_RECOMPUTE", "GENERATION")
        new_state = adapter.snapshot()
        new_diag = adapter.diagnostics(folder / "RECOVERY_DIAGNOSTICS", "RECOVERY")
        proof = eq.verify_parent(adapter, state, new_state, diag, new_diag)
        if adapter.snapshot() != new_state:
            proof["passes"] = False
            proof["diagnostics_changed_model"] = True
        rec["parent_equivalence"] = proof
        if not proof["passes"]:
            rec.update(status="RECOVERY_FAILED_MANUAL_REOPEN_LATEST_ACCEPTED", search_complete=False,
                       stationarity_confirmed=False, recovery_accepted=False)
            try:
                save()
            except Exception:
                pass
            raise SupplyContractError("GENFIX2_SUPPLYMIX_RECOVERY_NOT_EQUIVALENT_MANUAL_REOPEN") from rb_error
        new_value = base.ledger(new_diag, new_state, anchors, policy, reference, sup_cfg)
    # No accepted_state_changed call and no changed=True. This is the same parent.
    eq.rebind_verified_parent(adapter, new_state, new_diag)
    _STATE["recovered"] += 1
    rec.update(status="RECOVERED_FULL_RECOMPUTE_FROM_PARENT_PARAMETERS", recovery_gap=gap,
               objective_after=new_value, error=str(exc)[:2000], recovery_accepted=False,
               search_complete=False, stationarity_confirmed=False)
    try:
        save()
    except Exception as io_exc:
        if hasattr(exc, "add_note"):
            exc.add_note("RECOVERY_LOG_WRITE_FAILED:" + repr(io_exc))
        raise exc
    if stop or isinstance(exc, OSError):
        raise exc
    return False, new_state, new_diag, new_value, rec


# ------------------------------------------------------------------ install
def _wrap_generation(orig, ctrl, base, tx):
    @functools.wraps(orig)
    def _generation_update_once(adapter, cfg, folder, control, state, diag, anchors, reference, policy,
                                outer_cycle=None):
        result = orig(adapter, cfg, folder, control, state, diag, anchors, reference, policy,
                      outer_cycle=outer_cycle)
        opts = options()
        ok, why = due(outer_cycle, opts)
        changed, st, dg, value, rec = result
        if not ok:
            return result
        _STATE["blocks"] += 1
        text = str(folder) if folder is not None else "SUPPLYMIX"
        sfolder = Path(text[:-len("_GENERATION")] + "_SUPPLYMIX" if text.endswith("_GENERATION")
                       else text + "_SUPPLYMIX")
        s_changed, st2, dg2, value2, srec = supply_block(
            ctrl, base, tx, adapter, cfg, sfolder, control, st, dg, anchors, reference, policy,
            outer_cycle, opts)
        rec = dict(rec or {})
        rec["v24917_supplymix"] = {k: v for k, v in srec.items() if k not in ("traceback",)}
        rec["v24917_supplymix"]["folder"] = str(sfolder)
        if s_changed:
            rec["stationarity_confirmed"] = False
            rec["v24917_supplymix_changed"] = True
            try:
                import r1_15a2_demand_policy_v1 as dp
                for item in dp._ACTIVE.values():
                    pol = item.get("policy")
                    if pol is not None:
                        pol.last_generation_complete = False   # no stationary streak while supply moves
            except Exception:
                pass
            return True, st2, dg2, value2, rec
        if srec.get("search_complete") is False:
            # SUPPLYMIX is a separate, optional ADDVAL route-choice search
            # wrapped OUTSIDE DemandPolicy.note_generation. A legal-branch
            # exhaustion / verified no-write failure is not proof of SUPPLY
            # stationarity, but it also must NOT convert an otherwise complete
            # Generation search into DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED.
            #
            # Keep the original TG search_complete value unchanged. Block
            # joint stationarity for this cycle and retain the SupplyMix reason
            # in its own namespace. A genuine TG failure (original
            # search_complete=False) still propagates unchanged.
            rec["stationarity_confirmed"] = False
            rec["v24917_supplymix_search_incomplete"] = True
            rec["v24917_supplymix_incomplete_reason"] = (
                srec.get("stop_reason") or srec.get("status") or "UNKNOWN")
            rec["v24917_supplymix_tg_completion_preserved"] = True
            # This wrapper runs outside DemandPolicy.note_generation. Clear its
            # earlier stationary claim; a SupplyMix incomplete search cannot
            # certify a complete JOINT fixed point.
            import r1_15a2_demand_policy_v1 as dp
            for item in dp._ACTIVE.values():
                pol = item.get("policy")
                if pol is not None:
                    pol.last_generation_complete = False
        return changed, st2, dg2, value2, rec
    _generation_update_once.__r1_supplymix__ = True
    return _generation_update_once


def install(print_fn=print) -> Dict[str, Any]:
    if _STATE["installed"]:
        return status()
    # Validate before patching functions or publishing installed=True. A bad
    # configuration must leave installation retryable, with no partial wiring.
    o = options()
    import r1_15a2_acceleration_v24915p1 as perf1
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_inplace_transaction_v24915p2 as tx
    for name in ("ledger", "diagnostic_hash", "assert_freeze", "atomic_json", "_write_acceptance",
                 "_candidate_signature", "_assign_candidate", "_rollback_candidate", "recovery_scope",
                 "number", "UserStopRequested", "TimeBudgetReached"):
        if not hasattr(base, name):
            raise RuntimeError("V24917_SUPPLYMIX_BASE_SYMBOL_MISSING:" + name)
    for name in ("_generation_counts_cfg", "adapter_config_scope", "_generation_update_once"):
        if not hasattr(ctrl, name):
            raise RuntimeError("V24917_SUPPLYMIX_CONTROLLER_SYMBOL_MISSING:" + name)
    if not hasattr(tx, "restore_supply_parameters"):
        raise RuntimeError("V24917_SUPPLYMIX_TX_SYMBOL_MISSING:restore_supply_parameters")
    if not getattr(perf1.phase_recompute_plan, "__r1_supplymix__", False):
        perf1.phase_recompute_plan = _wrap_plan(perf1.phase_recompute_plan)
    if not getattr(ctrl._generation_update_once, "__r1_supplymix__", False):
        ctrl._generation_update_once = _wrap_generation(ctrl._generation_update_once, ctrl, base, tx)
    _STATE["installed"] = True
    _STATE["options"] = o
    print_fn("V24917 SUPPLYMIX_COSTFIX1: %s; ADDVAL1 route choice every %d cycle(s) after Generation, steps %s x0.5, "
             "drivers %s (GEH>=%.0f), cold op%d..assignment"
             % ("ON" if o["enabled"] else "OFF", o["every_n"], o["step_units"], o["drivers"],
                o["min_driver_geh"], o["reset_position"]))
    return status()


def status() -> Dict[str, Any]:
    return {k: (list(v) if isinstance(v, list) else v) for k, v in _STATE.items()}


__all__ = ["RELEASE", "install", "status", "options", "due", "select_groups", "merged_candidate",
           "cold_supply_plan", "profile_table", "driver_mode", "worsened_profiles",
           "cost_safe_merged_candidate", "supply_block"]
