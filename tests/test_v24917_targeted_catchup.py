"""V24917: zonal count fit, targeted design mode, envelope, evidence fix, config delta."""
from __future__ import annotations

import copy
import math
from types import SimpleNamespace

import numpy as np
import pytest

import r1_15a2_zonal_count_fit_v24917 as zf
import r1_15a2_targeted_generation_v24917 as tg

UP, DN = math.log(1.5), math.log(0.8)


# ----------------------------------------------------------------- fixtures
def synthetic_incidence(n_zones=12, seed=3, residual_factor=3.0, overloaded=()):
    """Zones 1..n on a line; profile k sits between zone k and k+1 (both directions merged)."""
    rng = np.random.default_rng(seed)
    variables, rows, cols, vals = [], [], [], []
    n_prof = n_zones - 1
    for fam in ("WORK", "SERVICE"):
        for o in range(1, n_zones + 1):
            for d in range(1, n_zones + 1):
                if o == d:
                    continue
                q = float(100.0 * math.exp(-0.4 * abs(o - d)) * (1.0 + rng.random()))
                vi = len(variables)
                variables.append({"family": fam, "origin": o, "destination": d, "q_current": q})
                lo, hi = sorted((o, d))
                for p in range(lo, hi):           # profile p between zones p and p+1
                    rows.append(p - 1); cols.append(vi); vals.append(q)
    op = SimpleNamespace(row_idx=np.array(rows), col_idx=np.array(cols), values=np.array(vals),
                         n_rows=n_prof, n_cols=len(variables))
    mutable = np.bincount(rows, weights=vals, minlength=n_prof)
    profiles = []
    for p in range(n_prof):
        model = float(mutable[p] * 1.5)              # one third fixed demand
        factor = 0.7 if p in overloaded else residual_factor
        profiles.append({"role": "CALIBRATION", "observed": model * factor, "model": model,
                         "profile_weight": 1.0, "countlocation_no": 900 + p})
    return {"profiles": profiles, "variables": variables,
            "projection_base_variables": variables, "incidence": op}, list(range(1, n_zones + 1))


def all_bounds(zones, lo=DN, hi=UP):
    return {(f, r, z): (lo, hi) for f in zf.FAMILIES for r in zf.ROLES for z in zones}


# --------------------------------------------------------------- zonal fit
def test_fit_raises_underloaded_zones_and_respects_bounds():
    inc, zones = synthetic_incidence()
    rows, summary, problem, sol = zf.fit(inc, zones, all_bounds(zones), {})
    assert sol["converged"]
    steps = np.array([r["log_step"] for r in rows])
    assert steps.max() <= UP + 1e-9 and steps.min() >= DN - 1e-9
    assert summary["positive_rows"] > 0
    lp = summary["linear_prediction"]
    assert lp["ratio_after"] > lp["ratio_before"] * 1.2
    assert lp["geh_mean_after"] < lp["geh_mean_before"]
    # doubly constrained effect model keeps P and A family totals balanced
    for fam in zf.FAMILIES:
        p = summary["margin_totals"][fam + "_PROD_delta"]
        a = summary["margin_totals"][fam + "_ATT_delta"]
        assert abs(p - a) / max(1.0, abs(p), abs(a)) < 0.05


def test_fit_is_targeted_unexposed_zone_stays_zero():
    inc, zones = synthetic_incidence()
    # zone 99 has demand but no OD crosses any profile
    inc["projection_base_variables"] = list(inc["variables"]) + [
        {"family": "WORK", "origin": 99, "destination": 99, "q_current": 500.0}]
    zones = zones + [99]
    rows, summary, problem, _ = zf.fit(inc, zones, all_bounds(zones), {})
    assert not [r for r in rows if r["zone_no"] == 99]


def test_fit_lowers_zones_feeding_only_overloaded_profile():
    inc, zones = synthetic_incidence(residual_factor=1.0, overloaded=(0,))
    rows, summary, _, _ = zf.fit(inc, zones, all_bounds(zones), {})
    z1 = [r["log_step"] for r in rows if r["zone_no"] == 1]
    assert z1 and max(z1) < 0.0          # zone 1 only loads the overloaded profile 0


def test_uniform_residual_gives_near_uniform_growth():
    inc, zones = synthetic_incidence(residual_factor=1.0)
    for p in inc["profiles"]:
        p["observed"] = p["model"] + 0.10 * p["model"] / 1.5   # +10 % of mutable flow
    rows, summary, problem, sol = zf.fit(inc, zones, all_bounds(zones), {"protected_geh": 0.0},
                                         {"ridge_relative": 1e-4})
    rel = (problem.G @ sol["x"]) / np.array([r["mutable_through_work"] + r["mutable_through_service"]
                                            for r in problem.profile_rows])
    assert np.allclose(rel, 0.10, atol=0.02)


def test_fit_without_actuators_or_rows_fails_closed():
    inc, zones = synthetic_incidence()
    with pytest.raises(ValueError, match="NO_ACTUATOR"):
        zf.fit(inc, zones, {}, {})
    for p in inc["profiles"]:
        p["role"] = "VALIDATION"
    with pytest.raises(ValueError, match="NO_CALIBRATION_ROWS"):
        zf.fit(inc, zones, all_bounds(zones), {})


# ---------------------------------------------------------- policy & phase
def test_policy_validation_and_phase(monkeypatch):
    monkeypatch.setenv("R1_TG_CATCHUP", "1")
    p = tg.validate_policy(tg.DEFAULT_POLICY)
    assert p["catchup_max_log_up"] == pytest.approx(UP)
    bad = copy.deepcopy(tg.DEFAULT_POLICY); bad["catchup_max_log_up"] = 1.0
    with pytest.raises(RuntimeError):
        tg.validate_policy(bad)
    bad = copy.deepcopy(tg.DEFAULT_POLICY); bad["envelope"]["domestic_hard"] = [1.2, 5.0]
    with pytest.raises(RuntimeError):
        tg.validate_policy(bad)
    rows = [{"role": "CALIBRATION", "observed": 100.0, "model": 26.0},
            {"role": "CALIBRATION", "observed": 0.0, "model": 50.0},
            {"role": "VALIDATION", "observed": 100.0, "model": 100.0}]
    assert tg.phase_for(rows, p) == ("CATCH_UP", pytest.approx(0.26))
    rows[0]["model"] = 85.0
    assert tg.phase_for(rows, p)[0] == "REFINE"
    rows[0]["model"] = 26.0
    monkeypatch.setenv("R1_TG_CATCHUP", "0")
    assert tg.phase_for(rows, p) == ("REFINE", pytest.approx(0.26))


def test_overlay_only_with_policy():
    cfg = {"max_add_log_up": 0.1, "max_add_log_down": 0.1}
    assert tg.overlay_cfg(cfg, "CATCH_UP") == cfg
    cfg[tg.POLICY_KEY] = tg.validate_policy(tg.DEFAULT_POLICY)
    out = tg.overlay_cfg(cfg, "CATCH_UP")
    assert out["max_add_log_up"] == pytest.approx(UP) and out["max_add_log_down"] == pytest.approx(-DN)
    assert out[tg.MODE_KEY] == tg.MODE and cfg["max_add_log_up"] == 0.1
    assert tg.overlay_cfg(cfg, "REFINE")["max_add_log_up"] == pytest.approx(math.log(1.25))


# --------------------------------------------------- multiblock integration
@pytest.fixture
def mb(monkeypatch):
    import r1_15a2_multiblock as mbm
    for name in ("_multiplicative_coefficient_bounds", "_soft_multiplier_bounds",
                 "_signed_generation_refinement"):
        monkeypatch.setattr(mbm, name, getattr(mbm, name))
    tg.patch_multiblock(mbm)
    return mbm


@pytest.fixture
def real_cfg():
    import r1_15a2_fresh0_shortroot_parent_v24916 as parent
    import r1_15a2_runtime_delta_v24917 as delta
    base = parent.load_config("FULL")
    cfg = delta.apply_active_runtime_delta(base)
    delta.validate_active_runtime_delta(cfg, base)
    return cfg


def test_envelope_bounds(mb, real_cfg):
    cfg = tg.overlay_cfg(real_cfg, "CATCH_UP")
    assert mb._multiplicative_coefficient_bounds("DOMESTIC", cfg, 1.9)[:2] == (0.75, 2.0)
    assert mb._multiplicative_coefficient_bounds("DOMESTIC", cfg, 6.0)[:2] == (0.75, 6.0)
    assert mb._multiplicative_coefficient_bounds("ZAHR", cfg, 3.0, 2.0)[:2] == (1.0, 20.0)
    assert mb._soft_multiplier_bounds("DOMESTIC", cfg, 1.9) == (0.75, 2.0)
    refine = tg.overlay_cfg(real_cfg, "REFINE")
    assert mb._soft_multiplier_bounds("DOMESTIC", refine, 1.9) == (0.75, 2.0)
    plain = {k: v for k, v in real_cfg.items() if k != tg.POLICY_KEY}
    assert mb._multiplicative_coefficient_bounds("DOMESTIC", plain, 1.0)[:2] == (0.5, 2.0)
    assert mb._salary_coefficient_bounds(cfg, 1.0)[:2] == (0.5, 2.0)


@pytest.mark.parametrize("attr,upper", [
    ("ADD_PROD_W", 3.0), ("ADD_PROD_S", 3.0),
    ("ADD_ATT_W", 5.0), ("ADD_ATT_S", 5.0),
])
@pytest.mark.parametrize("phase", ["CATCH_UP", "REFINE"])
def test_role_reference_reaches_byte_locked_multiblock_mapper(mb, real_cfg, attr, upper, phase):
    cfg = tg.overlay_cfg(real_cfg, phase)
    ref = mb._reference_coefficient(None, attr, 1, 1.0)
    assert isinstance(ref, float) and float(ref) == 1.0
    assert getattr(ref, "v24917_generation_role") in ("PROD", "ATT")
    cloned = copy.deepcopy(ref)
    assert float(cloned) == float(ref)
    assert cloned.v24917_generation_role == ref.v24917_generation_role
    hard = mb._multiplicative_coefficient_bounds(
        "DOMESTIC", cfg, current=1.0, reference=ref)
    soft = mb._soft_multiplier_bounds("DOMESTIC", cfg, 1.0, ref)
    assert hard[:2] == pytest.approx((0.75, upper))
    assert soft == pytest.approx((0.75, upper))
    # Generic / unrelated reference retains the prior scalar 2.0 band.
    unchanged_ref = mb._reference_coefficient(None, "ADD_SALARY", 1, 1.0)
    assert getattr(unchanged_ref, "v24917_generation_role", None) is None
    assert mb._multiplicative_coefficient_bounds(
        "DOMESTIC", cfg, current=1.0, reference=unchanged_ref)[:2] == (0.75, 2.0)
    assert mb._salary_coefficient_bounds(cfg, 1.0)[:2] == (0.5, 2.0)


def zone_rows(zones, value=1.9):
    out = []
    for z in zones:
        out.append({"zone_no": z, "ADD_PROD_W": value, "ADD_ATT_W": value, "ADD_PROD_S": value,
                    "ADD_ATT_S": value, "ADD_SALARY": 1.0, "AV_INCOME": 1500.0 + 10 * z,
                    "NOT_ZAHR": 1.0, "ZAHR_SUSED": 0.0, "POP_ZP": 1000.0,
                    "ZAHR_PROD_WORK": 0.0, "ZAHR_ATR_WORK": 0.0, "ZAHR_PROD_SERV": 0.0,
                    "ZAHR_ATR_SERV": 0.0})
    return out


@pytest.mark.parametrize("phase", ["CATCH_UP", "REFINE"])
def test_new_ws_3_5_headroom_survives_zonal_solver_bounds(mb, real_cfg, phase):
    """The old 2.5/4.0 ceiling must no longer clip eligible W/S candidates."""
    cfg = tg.overlay_cfg(real_cfg, phase)
    zr = zone_rows([1], value=2.8)
    zr[0]["ADD_ATT_W"] = zr[0]["ADD_ATT_S"] = 4.5
    bounds = tg.zone_bounds(mb, zr, cfg)
    for family in ("WORK", "SERVICE"):
        assert bounds[(family, "PROD", 1)][1] == pytest.approx(
            math.log(3.0 / 2.8))
    assert bounds[("SERVICE", "ATT", 1)][1] == pytest.approx(
        math.log(5.0 / 4.5))
    # WORK attractiveness retains the established salary-effect reserve.
    assert bounds[("WORK", "ATT", 1)][1] == pytest.approx(
        math.log(5.0 / 4.5) - tg.SALARY_DOMAIN_MARGIN)
    # No modeled coefficient or salary authority is changed in this test.


def test_end_to_end_design_targeted_coarse_and_gate_passes(mb, real_cfg):
    import R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1 as master
    inc, zones = synthetic_incidence(n_zones=12)
    cfg = tg.overlay_cfg(real_cfg, "CATCH_UP")
    zr = zone_rows(zones, value=1.9)            # within new W/S production 3.0; attraction 5.0
    bounds = tg.zone_bounds(mb, zr, cfg)
    # The new hard maximum is 3.0, but the existing +50% per-cycle cap
    # dominates at current=1.9 (1.9 * 1.5 = 2.85 < 3.0).
    max_prod_step = min(UP, math.log(3.0 / 1.9))
    assert bounds[("WORK", "PROD", 1)] == pytest.approx((DN, max_prod_step))
    assert bounds[("SERVICE", "PROD", 1)] == pytest.approx((DN, max_prod_step))
    assert bounds[("WORK", "ATT", 1)][1] == pytest.approx(UP)
    assert bounds[("SERVICE", "ATT", 1)][1] == pytest.approx(UP)
    rows, summary, _, _ = zf.fit(inc, zones, bounds, cfg, tg.DEFAULT_POLICY["fit"])
    design = mb.design_generation_candidates(rows, zr, cfg, scale=1.0)
    refine = design["summary"]["signed_generation_refinement"]
    assert refine["mode"] == "V24917_TARGETED_ZONE_DIRECT"
    proposed = {(r["zone_no"], r["attr"]): r["proposed"] for r in design["candidate_rows"]}
    assert any(value > 1.9 for value in proposed.values())
    # Direct P/Service A coefficients follow the +50% step cap.  WORK
    # attraction's independent ADD_SALARY co-effect can make its raw
    # ADD_ATT_W ratio slightly larger; its *implemented total log effect*
    # must still pass the same +50% cap (checked below).
    assert all(value <= 1.9 * 1.5 + 1e-9
               for (_z, attr), value in proposed.items()
               if attr in ("ADD_PROD_W", "ADD_PROD_S", "ADD_ATT_S"))
    assert all(value <= 3.0 + 1e-9 for (_z, attr), value in proposed.items()
               if attr in ("ADD_PROD_W", "ADD_PROD_S"))
    assert all(value <= 5.0 + 1e-9 for (_z, attr), value in proposed.items()
               if attr in ("ADD_ATT_W", "ADD_ATT_S"))
    assert all(value <= 2.0 + 1e-9 for (_z, attr), value in proposed.items()
               if attr == "ADD_SALARY")
    effects = [r["implemented_total_log_effect"] for r in design["effect_rows"]]
    assert max(effects) <= UP + 1e-9 and min(effects) >= DN - 1e-9   # +50 % / -20 % per cycle
    gate = master.generation_apply_gate(design, cfg)
    assert gate["passes"], gate
    # backtracking scale still applies exactly once
    half = mb.design_generation_candidates(rows, zr, cfg, scale=0.5)
    r_full = {k: math.log(v / 1.9) for k, v in proposed.items() if k[1] == "ADD_PROD_S"}
    r_half = {(r["zone_no"], r["attr"]): math.log(r["proposed"] / 1.9)
              for r in half["candidate_rows"] if r["attr"] == "ADD_PROD_S"}
    common = set(r_full) & set(r_half)
    assert common


def test_refine_phase_outside_aligned_band_cannot_move_further_out(mb, real_cfg):
    inc, zones = synthetic_incidence(n_zones=8)
    cfg = dict(tg.overlay_cfg(real_cfg, "REFINE"), max_add_log_up=0.06, max_add_log_down=0.06)
    zr = zone_rows(zones, value=5.5)             # outside both new P=3.0 and A=5.0 bands
    bounds = tg.zone_bounds(mb, zr, cfg)
    rows, _, _, _ = zf.fit(inc, zones, bounds, cfg, tg.DEFAULT_POLICY["fit"])
    design = mb.design_generation_candidates(rows, zr, cfg, scale=1.0)
    steps = [math.log(r["proposed"] / 5.5) for r in design["candidate_rows"] if r["attr"] != "ADD_SALARY"]
    assert all(step <= 1e-9 for step in steps)  # hold or inward only; no forced clamp


def test_inherited_mode_untouched_without_policy(mb, real_cfg):
    inc, zones = synthetic_incidence(n_zones=8)
    plain = {k: v for k, v in real_cfg.items() if k != tg.POLICY_KEY}
    rows, _, _, _ = zf.fit(inc, zones, all_bounds(zones, -0.05, 0.05), plain)
    design = mb.design_generation_candidates(rows, zone_rows(zones, 1.0), plain, scale=1.0)
    assert design["summary"]["signed_generation_refinement"]["mode"] == \
        "FAMILY_GLOBAL_PLUS_NONLINEAR_CENTERED_ZONE_LOG_EFFECT"


# --------------------------------------------------------- evidence fix
def test_v24916_publish_bug_is_real_and_fixed(monkeypatch, tmp_path):
    import r1_15a2_active_demand_evidence_v24916p2c as base
    import r1_15a2_active_demand_evidence_v24917 as fixed
    import inspect
    assert "skim_identity=dist," in inspect.getsource(base.ActiveDemandEvidenceBuilder.build)
    assert not hasattr(base, "dist")

    epoch = SimpleNamespace(summary=lambda: {"epoch_hash": "E1", "epoch": 3})
    published = {}

    class Manager:
        def get(self, identity):
            return None

        def publish(self, **kw):
            published.update(kw)
            return SimpleNamespace(as_dict=lambda: {"skim": kw["skim_identity"].as_dict()})

    def fake_build(self, diag, context, folder, snapshot):
        return self.manager.publish(identity="I", flowbundles={}, skim_identity=dist,
                                    target_payload={})

    monkeypatch.setattr(base.ActiveDemandEvidenceBuilder, "build", fake_build)
    b = fixed.ActiveDemandEvidenceBuilder.__new__(fixed.ActiveDemandEvidenceBuilder)
    b.manager = Manager()
    b._distance_epoch = lambda: epoch
    snap = b.build({}, {}, tmp_path, {})
    assert snap.as_dict() == {"skim": {"epoch_hash": "E1", "epoch": 3}}
    assert isinstance(published["skim_identity"], fixed.EpochSkimIdentity)
    assert isinstance(b.manager, Manager) and not hasattr(base, "dist")


# --------------------------------------------------------- config delta
def test_config_delta_only_adds_v24917_sections(real_cfg):
    import r1_15a2_fresh0_shortroot_parent_v24916 as parent
    import r1_15a2_profile488_gatefix_v24916p2c as gatefix
    import r1_15a2_runtime_delta_v24917 as delta
    base = parent.load_config("FULL")
    v16 = gatefix.apply_active_runtime_delta(base)
    import r1_15a2_profile_roster_v24917 as roster
    meta = roster.load_meta()
    assert set(real_cfg) - set(v16) == set(delta.V24917_KEYS) | {roster.CFG_KEY}
    gate = roster.gate_of(meta)
    assert all(real_cfg[k] == v16[k] for k in v16 if k not in gate and k != "matrix_scope_by_block")
    expected_scope = copy.deepcopy(v16["matrix_scope_by_block"])
    expected_scope["GENERATION"] = delta.long_generation_scope(expected_scope["GENERATION"])
    assert real_cfg["matrix_scope_by_block"] == expected_scope
    assert {k: real_cfg[k] for k in gate} == gate and gate["expected_12d_rows"] == meta["rows"] != 488
    assert {k: v16[k] for k in gate} == roster.GATE488
    tampered = copy.deepcopy(real_cfg)
    tampered["expected_12d_rows"] = 488
    with pytest.raises(RuntimeError):
        delta.validate_active_runtime_delta(tampered, base)
    tampered = copy.deepcopy(real_cfg)
    tampered["v24917_targeted_generation"]["catchup_max_log_up"] = 0.5
    with pytest.raises(RuntimeError):
        delta.validate_active_runtime_delta(tampered, base)
    tampered = copy.deepcopy(real_cfg)
    tampered["ridge_lambda"] = 0.0
    with pytest.raises(RuntimeError):
        delta.validate_active_runtime_delta(tampered, base)


# ------------------------------------------------------------- adapter level
def _adapter(monkeypatch, real_cfg, zones, zr, parent_context):
    import r1_15a2_trial_adapter_v24917 as a17
    import r1_15a2_supply_visum as sv
    seen = {}
    # Complete live FP authority, proportional to the actual ADD multipliers.
    import r1_15a2_mobility_guard_v24917 as mg
    for row in zr:
        for family, attr in mg.MULT_ATTR.items():
            for fp in mg.FP_ATTRS[family]:
                row.setdefault(fp, 10.0 * float(row.get(attr, 1.0)))
    monkeypatch.setattr(a17._V24916ActiveAdapter, "generation_design",
                        lambda self, diag, folder: dict(parent_context))
    monkeypatch.setattr(a17._V24916ActiveAdapter, "generation_preview",
                        lambda self, context, scale: seen.setdefault("preview", dict(self.cfg)) and {})
    monkeypatch.setattr(a17._V24916ActiveAdapter, "apply_generation",
                        lambda self, context, scale, folder: seen.setdefault("apply", dict(self.cfg)) and [])
    monkeypatch.setattr(sv.base, "zone_state_rows", lambda *a, **k: (zr, []))
    ad = a17.VisumAdapter.__new__(a17.VisumAdapter)
    ad.cfg = real_cfg; ad.zones = zones; ad.zone_write_index_by_no = {}
    ad.com_retry_policy = {}; ad.generation_reference_values = None; ad.visum = None
    ad.v24917_status = {"designs": 0, "fit_fallbacks": 0}
    return ad, seen


def test_adapter_replaces_proposal_and_overlays_preview_apply(monkeypatch, tmp_path, mb, real_cfg):
    monkeypatch.setenv("R1_TG_CATCHUP", "1")
    import r1_15a2_core as core
    inc, zones = synthetic_incidence(n_zones=10)
    parent = core.ProjectionResult(rows=[{"zone_no": 1, "family": "WORK", "role": "PROD", "log_step": 0.001}],
                                   family_summaries=[{"family": "WORK", "converged": True}], weighted_rmse=0.0)
    ad, seen = _adapter(monkeypatch, real_cfg, zones, zone_rows(zones, 1.0),
                        {"incidence": inc, "projection": parent})
    diag = {"d12": {"rows": inc["profiles"]}}
    ctx = ad.generation_design(diag, tmp_path)
    assert ctx["v24917"]["phase"] == "CATCH_UP" and ctx["v24917"]["overlay_phase"] == "CATCH_UP"
    assert ctx["projection"].rows and all(r["projection_method"] == zf.METHOD for r in ctx["projection"].rows)
    assert all(s["converged"] for s in ctx["projection"].family_summaries)
    assert (tmp_path / "V24917_TARGETED_GENERATION" / "V24917_FIT_SUMMARY.json").is_file()
    # GENFIX2 preview is pure and no longer invokes the inherited COM preview.
    preview = ad.generation_preview(ctx, 1.0)
    assert preview["genfix2_mobility"]["passes"] and preview["genfix2_prediction"]["available"]
    assert "preview" not in seen
    ad.apply_generation(ctx, 0.5, tmp_path)
    assert seen["apply"][tg.MODE_KEY] == tg.MODE
    assert seen["apply"]["max_add_log_up"] == pytest.approx(UP)
    assert ad.cfg is real_cfg                   # overlay restored


def test_adapter_fit_error_falls_back_to_parent_without_overlay(monkeypatch, tmp_path, mb, real_cfg):
    import r1_15a2_core as core
    inc, zones = synthetic_incidence(n_zones=6)
    parent = core.ProjectionResult(rows=[{"zone_no": 1, "family": "WORK", "role": "PROD", "log_step": 0.001}],
                                   family_summaries=[{"family": "WORK", "converged": True}], weighted_rmse=0.0)
    ad, seen = _adapter(monkeypatch, real_cfg, zones, [], {"incidence": inc, "projection": parent})
    ctx = ad.generation_design({"d12": {"rows": inc["profiles"]}}, tmp_path)   # no zone rows -> no actuators
    assert ctx["v24917"]["status"] == "BLOCKED_MOBILITY_DATA"
    assert not ctx["projection"].rows and not ctx["v24917"]["proposal_usable"]
    with pytest.raises(Exception, match="BLOCKED_DATA_NOT_A_PLATEAU"):
        ad.generation_preview(ctx, 1.0)
    assert "preview" not in seen and "apply" not in seen


# ------------------------------------------------------- PrT skim op type
class _Op:
    def __init__(self, t, a, skim=False):
        self.t, self.a = t, a
        if skim:
            self.PrTSkimMatrixParameters = object()

    def AttValue(self, name):
        return {"OPERATIONTYPE": self.t, "ACTIVE": self.a}.get(name, "")

    def __getattr__(self, name):
        raise AttributeError(name)


def _visum(ops):
    return SimpleNamespace(Procedures=SimpleNamespace(Operations=SimpleNamespace(GetAll=lambda: ops)))


def test_skim_type_detection(monkeypatch):
    import r1_15a2_skim_optype_v24917 as so
    import r1_15a2_com_compat as com
    import r1_15a2_dynamic_skim_v24916p2c as ds
    import r1_15a2_finecdf_bridge_v24916 as bm
    import r1_15a2_trial_adapter_v24916p2c_active as act16
    monkeypatch.setattr(ds, "active_native_skim_positions", ds.active_native_skim_positions)
    monkeypatch.setattr(act16, "active_native_skim_positions", act16.active_native_skim_positions)
    monkeypatch.setattr(bm.NoDirectMatrixWriteTDAdapter, "_dynamic_realization_plan",
                        bm.NoDirectMatrixWriteTDAdapter._dynamic_realization_plan)
    monkeypatch.setattr(com, "SKIMS_PRT", 103)
    monkeypatch.delenv(so.ENV, raising=False)
    base = [_Op(65, 1), _Op(75, 1)] + [_Op(101, 1)] * 4 + [_Op(75, 1)]
    # live R1 case: six active skims of an unexpected type, 8 inactive of the same type
    ops = base + [_Op(110, 0, True)] * 8 + [_Op(110, 1, True)] * 6
    r = so.apply(_visum(ops))
    assert r["code"] == 110 and r["method"] == "COM_SKIM_PARAMETER_OBJECT" and com.SKIMS_PRT == 110
    # constant already right
    monkeypatch.setattr(com, "SKIMS_PRT", 103)
    assert so.detect(_visum(base + [_Op(103, 1)] * 6))["method"] == "V24916_CONSTANT_CONFIRMED"
    # no parameter object exposed -> unique type with six active operations
    assert so.detect(_visum(base + [_Op(120, 1)] * 6))["code"] == 120
    # ambiguous -> fail closed with inventory
    with pytest.raises(RuntimeError, match="NOT_IDENTIFIABLE"):
        so.detect(_visum(base + [_Op(120, 1)] * 6 + [_Op(121, 1)] * 6))
    with pytest.raises(RuntimeError, match="NOT_IDENTIFIABLE"):
        so.detect(_visum(base + [_Op(120, 1)] * 5))
    monkeypatch.setenv(so.ENV, "121")
    assert so.detect(_visum(base + [_Op(120, 1)] * 6 + [_Op(121, 1)] * 6))["method"] == "ENV_OVERRIDE"
    monkeypatch.setenv(so.ENV, "120")
    with pytest.raises(RuntimeError, match="OVERRIDE"):
        so.detect(_visum(base + [_Op(120, 1)] * 5))


# ------------------------------------------------------ dynamic 11D files fix
def _write_static_11d(root, comps=("WORK_E_C",), edges=(0, 1, 5, 15, 40)):
    import r1_15a2_runtime_v1 as rt
    ws = root / "11D_STATIC" / "nested"
    ws.mkdir(parents=True)
    base, comp_rows, summ = [], [], []
    for c in comps:
        n = len(edges) - 1
        for i in range(n):
            base.append({"component": c, "family": "WORK", "matrix_no": 9101, "metric": "DIST_KM",
                         "bin_label": "b%d" % i, "bin_low": edges[i], "bin_high": edges[i + 1],
                         "volume": 10.0, "share_conditioned": 1.0 / n, "share_total": 1.0 / n})
            comp_rows.append({"component": c, "family": "WORK", "bin_label": "b%d" % i,
                              "bin_low": edges[i], "bin_high": edges[i + 1], "target_share": [0.1, 0.4, 0.4, 0.1][i]})
        summ.append({"component": c, "family": "WORK", "target_status": "ACTIVE_COMPONENT_DIST_TARGET",
                     "conditioned_volume": 40.0, "total_volume": 40.0, "mean_model_conditioned": 9.0})
    rt.write_csv(ws / (rt.D11_PREFIX + "component_model_dist_baseline.csv"), base)
    rt.write_csv(ws / (rt.D11_PREFIX + "component_model_dist_vs_idp.csv"), comp_rows)
    rt.write_csv(ws / (rt.D11_PREFIX + "component_model_dist_vs_idp_summary.csv"), summ)
    (root / "11D_STATIC" / "summary.json").write_text("{}")
    return root / "11D_STATIC" / "summary.json", summ


def test_dynamic_11d_stage_and_rewrite(monkeypatch, tmp_path):
    import r1_15a2_dynamic_11d_files_v24917 as fx
    import r1_15a2_finecdf_bridge_v24916 as bridge
    import r1_15a2_runtime_v1 as rt
    static_summary, summ = _write_static_11d(tmp_path)
    out = fx.dynamic_folder(tmp_path / "DIAG", "BASELINE")
    staged = fx.stage_static_files(static_summary, out)
    assert set(staged) == {"summary", "compare", "baseline"}
    with pytest.raises(RuntimeError, match="STATIC_11D_FILES_MISSING"):
        fx.stage_static_files(tmp_path / "nothing" / "x.json", tmp_path / "o2")

    targets = {"WORK_E_C": {"edges": [0, 1, 5, 15, 40], "matrix_nos": [9101]}}
    dyn = {"WORK_E_C": {"bin_volumes": [5.0, 20.0, 20.0, 5.0], "shares": [0.1, 0.4, 0.4, 0.1],
                        "total_volume_diagnostic": 50.0}}
    monkeypatch.setattr(bridge, "load_reference",
                        lambda root, cfg: (SimpleNamespace(TARGETS=targets), None, "sha"))

    class FakeMetrics:
        def __init__(self, *a): pass
        def evaluate(self, matrices): return dyn
    monkeypatch.setattr(bridge, "DynamicFamilyMetrics", FakeMetrics)
    epoch = SimpleNamespace(epoch=4, epoch_hash="EH")
    adapter = SimpleNamespace(
        v24916_dynamic_skims=SimpleNamespace(require_current=lambda: epoch),
        _v24916_package_root=tmp_path,
        visum=SimpleNamespace(Net=SimpleNamespace(Matrices=SimpleNamespace(
            ItemByKey=lambda no: SimpleNamespace(GetValues=lambda: [[1.0]])))))
    dyn_summary = [dict(summ[0], mean_model_conditioned=8.5, distance_authority="DYNAMIC_ASSIGNMENT_DIS_KM")]
    diag = {"d11": {"summary_path": str(out / "DYNAMIC_11D_SUMMARY.json"),
                    "summary": {"component_dist_summary_rows": dyn_summary}}}
    report = fx.publish_dynamic_files(adapter, diag, out, {"td": {}})
    assert report["component_bins"] == {"WORK_E_C": "DYNAMIC_BINS"}
    sig = diag["signals"]["WORK_E_C"]
    assert [b["model_share"] for b in sig["model_bins"]] == pytest.approx([0.1, 0.4, 0.4, 0.1])
    assert sig["l1_half"] == pytest.approx(0.0) and sig["authority_complete"]
    s = rt.read_csv_auto(out / (rt.D11_PREFIX + "component_model_dist_vs_idp_summary.csv"))
    assert s[0]["distance_authority"] == "DYNAMIC_ASSIGNMENT_DIS_KM"


def test_dynamic_baseline_keeps_static_bins_on_edge_mismatch():
    import r1_15a2_dynamic_11d_files_v24917 as fx
    rows = [{"component": "SERV_E_C", "bin_low": 0, "bin_high": 2, "share_conditioned": 0.5},
            {"component": "SERV_E_C", "bin_low": 2, "bin_high": "INF", "share_conditioned": 0.5}]
    out, audit = fx.dynamic_baseline_rows(rows, {"SERV_E_C": {"bin_volumes": [1, 1], "shares": [.5, .5]}},
                                          {"SERV_E_C": {"edges": [0, 2, 50]}})
    assert audit == {"SERV_E_C": "STATIC_BINS_RETAINED_EDGE_MISMATCH"} and out == rows


def test_adapter_dynamic_overlay_stages_then_publishes(monkeypatch, tmp_path):
    import r1_15a2_trial_adapter_v24917 as a17
    import r1_15a2_dynamic_11d_files_v24917 as fx
    static_summary, _ = _write_static_11d(tmp_path)
    calls = []

    def parent_overlay(self, diag, folder, label):
        out = fx.dynamic_folder(folder, label)
        import r1_15a2_runtime_v1 as rt
        assert rt.find_file_recursive(out, rt.D11_PREFIX + "component_model_dist_baseline.csv")
        calls.append("parent")
        return dict(diag, d11=dict(diag["d11"], summary_path=str(out / "DYNAMIC_11D_SUMMARY.json")))
    monkeypatch.setattr(a17._V24916ActiveAdapter, "_dynamic_11d_overlay", parent_overlay)
    monkeypatch.setattr(fx, "publish_dynamic_files", lambda ad, diag, out, cfg, **kw: calls.append("publish") or {"ok": 1})
    monkeypatch.setenv("R1_D11_SHORT_ROOT", str(tmp_path / "S"))
    ad = a17.VisumAdapter.__new__(a17.VisumAdapter)
    ad.v24916_dynamic_skims = object(); ad.cfg = {}
    long_folder = tmp_path / ("D" * 40) / "TRY_01" / "DIAGNOSTICS"
    diag = ad._dynamic_11d_overlay({"d11": {"summary_path": str(static_summary)}}, long_folder, "AFTER")
    rep = diag["v24917_dynamic_11d_files"]
    assert calls == ["parent", "publish"] and rep["ok"] == 1
    assert diag["d11"]["summary_path"].startswith(str(tmp_path / "S"))      # short working folder
    mirrored = fx.dynamic_folder(long_folder, "AFTER")
    assert not rep["evidence_mirror"]["errors"] and len(rep["evidence_mirror"]["copied"]) == 3
    assert (mirrored / (__import__("r1_15a2_runtime_v1").D11_PREFIX + "component_model_dist_baseline.csv")).is_file()


def test_find_long_returns_newest_match(tmp_path):
    import os, time
    import r1_15a2_dynamic_11d_files_v24917 as fx
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "f.csv").write_text("1")
    time.sleep(0.01)
    (tmp_path / "a" / "b" / "f.csv").write_text("2")
    os.utime(tmp_path / "a" / "b" / "f.csv", None)
    assert fx.find_long(tmp_path, "f.csv").read_text() == "2"
    assert fx.find_long(tmp_path / "missing", "f.csv") is None


# ------------------------------------------------- FineCDF gap read fix
def test_finecdf_gap_is_read_inside_active_plan(monkeypatch, tmp_path):
    import contextlib
    import r1_15a2_finecdf_bridge_v24916 as bridge
    import r1_15a2_finecdf_gapfix_v24917 as gapfix
    import r1_15a2_runtime_v1 as rt
    state = {"active": False}

    @contextlib.contextmanager
    def plan_ctx(visum, plan):
        state["active"] = True
        try:
            yield dict(plan)
        finally:
            state["active"] = False

    def gap():
        if not state["active"]:
            raise RuntimeError("QUALITY_OPERATION_NOT_ACTIVE_PRT")
        return 0.001

    monkeypatch.setattr(bridge.perf1, "activate_operation_plan", plan_ctx)
    monkeypatch.setattr(rt, "execute_procseq", lambda v, folder: None)
    epoch = SimpleNamespace(epoch=1, epoch_hash="E", assignment_epoch=3)
    outer = SimpleNamespace(gap=gap, readback_manager=None, last_gap_evidence=None,
                            v24916_dynamic_skims=SimpleNamespace(capture_after_execution=lambda *a: epoch),
                            _live_generation_matrices=lambda: {})
    monkeypatch.setattr(gapfix.td_numpy, 'read_skim_weights', lambda _outer: {})
    obj = bridge.NoDirectMatrixWriteTDAdapter.__new__(bridge.NoDirectMatrixWriteTDAdapter)
    obj.v = None; obj.root = tmp_path; obj.dynamic_eval_index = 0; obj.outer_adapter = outer
    obj._dynamic_realization_plan = lambda: {"dynamic_skim_operation_positions": [31]}
    obj.read_abc = lambda: {}
    with pytest.raises(RuntimeError, match="QUALITY_OPERATION_NOT_ACTIVE_PRT"):
        bridge.NoDirectMatrixWriteTDAdapter._execute_dynamic_realization(obj)   # V24916 defect
    monkeypatch.setattr(bridge.NoDirectMatrixWriteTDAdapter, "_execute_dynamic_realization",
                        bridge.NoDirectMatrixWriteTDAdapter._execute_dynamic_realization)
    assert gapfix.install()["installed"]
    obj.dynamic_eval_index = 0
    assert obj._execute_dynamic_realization() is epoch and obj.dynamic_skim_epoch is epoch


# ------------------------------------------------- TD skipped during catch-up
def test_td_every_n_skipped_during_catchup(monkeypatch, tmp_path, real_cfg):
    import r1_15a2_demand_policy_v1 as dp
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    monkeypatch.setenv("R1_TG_CATCHUP", "1")
    calls = []
    orig = lambda adapter, cfg, folder, control, state, diag, root, outer_cycle=None: (
        calls.append(outer_cycle) or (False, state, diag, {"inner": {"search_complete": True}}))
    policy = dp.DemandPolicy(dp.validate({}))
    policy.last_generation_changed = True
    policy.td_calls = 1                              # not the first cycle of the run
    td = dp.wrap_td(orig, policy, ctrl)
    low = {"d12": {"rows": [{"role": "CALIBRATION", "observed": 100.0, "model": 42.0}]}}
    high = {"d12": {"rows": [{"role": "CALIBRATION", "observed": 100.0, "model": 85.0}]}}
    st = {"state_hash": "S"}
    monkeypatch.setattr(ctrl, "diagnostic_hash", lambda d: "H")
    _, _, _, rec = td(None, real_cfg, tmp_path / "a", None, st, low, None, outer_cycle=5)
    assert calls == [] and rec["skip_policy_reason"].startswith("CATCH_UP_PHASE_MODEL_OBS_0.420")
    td(None, real_cfg, tmp_path / "b", None, st, high, None, outer_cycle=5)
    assert calls == [5]
    policy.last_generation_changed = False          # TG plateau still runs TD in catch-up
    td(None, real_cfg, tmp_path / "c", None, st, low, None, outer_cycle=6)
    assert calls == [5, 6]
    policy2 = dp.DemandPolicy(dp.validate({"td_during_catchup": True})); policy2.last_generation_changed = True; policy2.td_calls = 1
    dp.wrap_td(orig, policy2, ctrl)(None, real_cfg, tmp_path / "d", None, st, low, None, outer_cycle=10)
    assert calls == [5, 6, 10]


# ------------------------------------------------------------- profile roster
def _roster():
    import r1_15a2_profile_roster_v24917 as roster
    return roster, roster.load_meta()


def test_roster_is_subset_of_488_authority_with_identical_rows():
    import csv
    from pathlib import Path
    roster, meta = _roster()
    root = Path(roster.HERE)
    def rows(rel):
        with open(root / rel, encoding="utf-8-sig", newline="") as fh:
            return {r["countlocation_no"]: r for r in csv.DictReader(fh)}
    parent = rows("authorities/" + meta["parent_authority"]["csd"])
    parent.update(rows("authorities/" + meta["parent_authority"]["city"]))
    sub = rows(meta["csd_csv"]); sub.update(rows(meta["city_csv"]))
    assert len(sub) == meta["rows"] == 248 and meta["csd_rows"] == 196 and meta["city_rows"] == 52
    assert not {920061, 920062, 920081, 920082, 920147, 920148, 920267, 920268} & set(map(int, sub))
    moved = {str(e["countlocation_no"]): e for e in meta.get("edge_resync", [])}
    edge = ("current_link_no", "current_from_node_no", "current_to_node_no")
    for k, v in sub.items():
        if k in moved:      # documented network edit: only the live edge may differ
            assert [int(v[c]) for c in edge] == moved[k]["new_edge"]
            assert [int(parent[k][c]) for c in edge] == moved[k]["old_edge"]
            assert {c: x for c, x in v.items() if c not in edge} == \
                   {c: x for c, x in parent[k].items() if c not in edge}
        else:
            assert parent[k] == v


class _CL:
    def __init__(self, d):
        self.d = d
    def AttValue(self, k):
        return self.d[k]


def _fake_cls(meta, extra=True):
    import csv
    from pathlib import Path
    import r1_15a2_profile_roster_v24917 as roster
    out = {}
    for rel in (meta["csd_csv"], meta["city_csv"]):
        with open(Path(roster.HERE) / rel, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                no = int(r["countlocation_no"])
                out[no] = _CL({"NO": no, "R1_OBS_RPDI": float(r["observed_passenger_cars_O"]),
                               "LINKNO": int(r["current_link_no"]), "FROMNODENO": int(r["current_from_node_no"]),
                               "TONODENO": int(r["current_to_node_no"]), "R1_ACTIVE": 1})
    if extra:   # a CountLocation outside the roster still present in the model
        out[920444] = _CL({"NO": 920444, "R1_OBS_RPDI": 1.0, "LINKNO": 1, "FROMNODENO": 1, "TONODENO": 2, "R1_ACTIVE": 1})
    return out


def test_roster_preflight_patch_accepts_model_with_extra_countlocations(monkeypatch):
    from pathlib import Path
    import r1_15a2_fresh_baseline_live_preflight_v24916p2c as pf
    import r1_15a2_fresh0_shortroot_parent_v24916 as f0
    import r1_15a2_diagfast_v1 as df
    roster, meta = _roster()
    # in-memory patches are process-global: register originals so they are restored
    for mod, names in ((pf, ("PROFILE488_CSD_REL", "PROFILE488_CITY_REL", "PROFILE488_XLSX_REL",
                             "PROFILE488_CSD_SHA256", "PROFILE488_CITY_SHA256", "PROFILE488_XLSX_SHA256",
                             "_profile488_authority", "_live_profile488_compatibility")),
                       (f0, ("CURRENT_12D_HELPER", "CURRENT_CSD_AUTH_REL", "CURRENT_CITY_AUTH_REL",
                             "CURRENT_COUNTLOCATION_SOURCE_REL", "CURRENT_CSD_AUTH_SHA256",
                             "CURRENT_CITY_AUTH_SHA256", "CURRENT_COUNTLOCATION_SOURCE_SHA256",
                             "CURRENT_PROFILE_COUNT")),
                       (df, ("reference_namespace",))):
        for n in names:
            monkeypatch.setattr(mod, n, getattr(mod, n))
    monkeypatch.setitem(df.HELPERS, "12D", df.HELPERS["12D"])
    import r1_15a2_live_api_audit as audit
    monkeypatch.setattr(audit, "com", audit.com)
    monkeypatch.setenv("R1_PROFILE_ROSTER_AUTH_DIR", "")
    monkeypatch.setattr(roster, "_STATE", {})
    roster.install_static(print_fn=lambda *a: None)
    assert df.HELPERS["12D"] == "R1_12D_PROFILE_ROSTER_V24917.py"
    cls = _fake_cls(meta)
    visum = SimpleNamespace(Net=SimpleNamespace(CountLocations=SimpleNamespace(ItemByKey=lambda no: cls[no])))
    res = pf._live_profile488_compatibility(visum, Path(roster.HERE), {"com_resilience": {}})
    assert res["passes"] and res["checked_rows"] == 248
    assert pf._profile488_authority(Path(roster.HERE))["rows"] == 248
    obs = f0._load_current_profile_authority()
    assert len(obs) == 248 and f0.CURRENT_12D_HELPER == "R1_12D_PROFILE_ROSTER_V24917.py"
    cls[912001].d["R1_OBS_RPDI"] = 1.0
    with pytest.raises(RuntimeError, match="V24917_ROSTER_LIVE_MODEL_INCOMPATIBLE"):
        pf._live_profile488_compatibility(visum, Path(roster.HERE), {"com_resilience": {}})


def test_roster_helper_reads_only_roster_and_loads_manifest(monkeypatch):
    import ast
    from pathlib import Path
    roster, meta = _roster()
    monkeypatch.setenv("R1_PROFILE_ROSTER_AUTH_DIR", str(Path(roster.HERE) / "authorities"))
    path = Path(roster.HERE) / meta["helper"]
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    assert isinstance(tree.body[-1], ast.Try)          # autostart main() removed for the test
    tree.body.pop()
    env = {"__name__": "_roster_helper_test", "__file__": "/nonexistent/" + path.name}
    exec(compile(tree, str(path), "exec"), env, env)
    manifest = env["load_manifest"]()
    assert len(manifest) == 248
    cls = _fake_cls(meta)
    visum = SimpleNamespace(Net=SimpleNamespace(CountLocations=SimpleNamespace(GetAll=list(cls.values()))))
    env["collection_items"] = lambda coll: list(coll.GetAll)
    got = env["read_countlocations"](visum)
    assert sorted(o.d["NO"] for o in got) == sorted(meta["countlocation_nos"])


def test_roster_gate_wrapper():
    roster, meta = _roster()
    seen = {}
    def inner(m, d12, cfg):
        seen["gate"] = d12["row_gate"]; seen["exp"] = cfg["expected_12d_rows"]
        return {"failures": [], "notices": ["PROFILE488_12D_GATE_488_488_0_VALIDATED"], "passes": True}
    w = roster._assess_wrapper(inner, meta)
    cfg = dict(roster.gate_of(meta))
    ok = w({}, {"row_gate": {"rows": 248, "calibration": 248, "validation": 0}}, cfg)
    assert ok["passes"] and seen == {"gate": {"rows": 488, "calibration": 488, "validation": 0}, "exp": 488}
    assert ok["notices"] == ["V24917_ROSTER_12D_GATE_248_248_0_VALIDATED"]
    bad = w({}, {"row_gate": {"rows": 488, "calibration": 488, "validation": 0}}, cfg)
    assert not bad["passes"] and any("V24917_ROSTER_12D_ACTIVE_AUTHORITY_NOT_PROVEN" in f for f in bad["failures"])


# ------------------------------------------------------------- TD count blend
class _FakeLink:
    def __init__(self, vol):
        self.vol = vol
    def AttValue(self, k):
        return self.vol if k == "VOLVEH_DSEG(NATIVE_CW,AP)" else 0.0


def _blend_fixture():
    import r1_15a2_core as core
    n = 3
    zone_order = [1, 2, 3]
    links = {(10, 11): _FakeLink(100.0), (11, 10): _FakeLink(50.0), (20, 21): _FakeLink(400.0)}
    visum = SimpleNamespace(Net=SimpleNamespace(Links=SimpleNamespace(ItemByKey=lambda a, b: links[(a, b)])))
    cfg = {"api_approved_observations": [
        {"no": 1, "observed": 300.0, "weight": 1.0, "edge_key": [5, 10, 11], "direction": "BOTH", "role": "CALIBRATION"},
        {"no": 2, "observed": 500.0, "weight": 1.0, "edge_key": [6, 20, 21], "direction": "DIRECTIONAL", "role": "CALIBRATION"}]}
    T = np.array([[50.0, 10.0, 0.0], [10.0, 50.0, 5.0], [0.0, 5.0, 50.0]])
    mats = {9101: T.copy(), 9106: T.copy()}
    live = {9201: 0.8 * T, 9206: 0.7 * T, 9221: 0.8 * T, 9222: 0.7 * T, 9225: np.zeros((n, n)),
            9217: np.ones((n, n)), 9226: 0.8 * T}
    for no in list(range(9202, 9206)) + list(range(9207, 9211)):
        live[no] = np.zeros((n, n))
    # profile 1 carries all WORK vehicles of OD (1,2) (8 veh = 0.8*10)
    variables = [{"family": "WORK", "origin": 1, "destination": 2, "dseg_code": "NATIVE_CW", "q_current": 8.0}]
    op = SimpleNamespace(row_idx=[0], col_idx=[0], values=[8.0])
    inc = {"profiles": [{"countlocation_no": 1}], "variables": variables, "incidence": op}
    return visum, cfg, zone_order, mats, live, inc, links


def test_td_count_model_linear_map_and_blend():
    import r1_15a2_td_count_blend_v24917 as tb
    visum, cfg, zo, mats, live, inc, links = _blend_fixture()
    m = tb.CountModel(visum, cfg, zo, inc)
    M0 = m.read_live()
    assert list(M0) == [150.0, 400.0]
    m.set_reference(M0, mats, lambda no: live[no])
    assert m.kappa[9101] == pytest.approx(0.8) and m.band[9101] == pytest.approx(1.0)
    T2 = mats[9101].copy(); T2[0, 1] += 10.0          # +10 person trips 1->2
    dm = m.delta_for([9101], {9101: T2})
    # symmetrize: +5 veh-equivalent per direction * kappa 0.8 -> 4 veh on OD(1,2) of 8 -> profile +4
    assert dm[0] == pytest.approx(8.0 * (0.8 * 5.0) / 8.0) and dm[1] == 0.0
    assert m.Q(M0) > m.Q(M0 + np.array([150.0, 100.0]))


def test_td_blend_apply_normalises_and_prefers_count_improvement(monkeypatch):
    import r1_15a2_td_count_blend_v24917 as tb
    visum, cfg, zo, mats, live, inc, links = _blend_fixture()
    monkeypatch.setattr(tb, "options", lambda: {"w_cnt": 0.65, "w_idp": 0.35, "inner_mode": "FROZEN_PATHS",
                                               "tg_max_trials": 3, "td_realization_max_trials": 3,
                                               "td_inner_max_evaluations": 60})
    ref = SimpleNamespace(CONFIG={"max_fine_cdf_rmse_degradation": 0.01, "max_mean_error_degradation": 0.02},
                          TARGETS={"WORK_E_C": {"matrix_nos": [9101]}, "SERV_E_C": {"matrix_nos": [9106]}})
    import tempfile
    outer = SimpleNamespace(cfg=cfg, v24917_last_incidence=inc)
    bridge = SimpleNamespace(v=visum, outer_adapter=outer, zone_order=zo, root=tempfile.mkdtemp(),
                             read_matrix=lambda no: live[no], _v24917_frozen=True)
    b = tb.Blend(bridge, ref, tb.options())
    assert ref.CONFIG["max_fine_cdf_rmse_degradation"] == 0.03
    def metrics(j1, j2):
        return {"WORK_E_C": {"objective": j1, "residual": np.array([math.sqrt(j1)])},
                "SERV_E_C": {"objective": j2, "residual": np.array([math.sqrt(j2)])}}
    base = b.apply(metrics(0.04, 0.06), mats)
    assert sum(v["objective"] for v in base.values()) == pytest.approx(0.35 + 2 * 0.65)
    T2 = mats[9101].copy(); T2[0, 1] += 100.0          # more WORK through under-loaded profile 1
    better_counts = b.apply(metrics(0.044, 0.06), {9101: T2, 9106: mats[9106]})
    assert better_counts["WORK_E_C"]["objective"] < base["WORK_E_C"]["objective"]
    assert better_counts["SERV_E_C"]["objective"] == pytest.approx(base["SERV_E_C"]["objective"])


def test_td_outer_decision_blend(monkeypatch):
    import r1_15a2_td_count_blend_v24917 as tb
    import r1_15a2_multiblock as mbm
    monkeypatch.setattr(tb, "options", lambda: {"w_cnt": 0.65, "w_idp": 0.35})
    def d12(model):
        return {"rows": [{"role": "CALIBRATION", "observed": 1000.0, "model": model, "profile_weight": 1.0}]}
    monkeypatch.setattr(mbm, "td_component_metrics",
                        lambda sig, comps, cfg: {"weighted_objective": sig["X"]["o"]})
    before = {"d12": d12(500.0), "signals": {"X": {"o": 0.20}}}
    after = {"d12": d12(700.0), "signals": {"X": {"o": 0.22}}}
    parent = {"accepted": False, "reasons": ["SELECTED_TD_OBJECTIVE_NOT_IMPROVED", "CAL_CSD_DEGRADED_TOO_MUCH"]}
    ok = tb.outer_decision(parent, before, after, {})
    assert ok["accepted"] and ok["v24917_td_blend"]["F"] < 1.0
    hard = dict(parent, reasons=parent["reasons"] + ["NEW_SEVERE_GEH_PROFILE"])
    assert not tb.outer_decision(hard, before, after, {})["accepted"]
    worse = {"d12": d12(480.0), "signals": {"X": {"o": 0.19}}}
    assert not tb.outer_decision(parent, before, worse, {})["accepted"]
    survey_broken = {"d12": d12(900.0), "signals": {"X": {"o": 0.30}}}
    r = tb.outer_decision(parent, before, survey_broken, {})
    assert "V24917_TD_SURVEY_DEGRADED_BEYOND_25PCT" in r["reasons"]


def test_run_options_td_blend_and_refine_relax(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options(tmp_path, environ={})
    assert o["td_count_weight"] == 0.60 and o["td_inner_mode"] == "FROZEN_PATHS" and o["tg_max_trials"] == 3
    with pytest.raises(RuntimeError):
        dp.validate({"td_count_weight": 1.5})
    with pytest.raises(RuntimeError):
        dp.validate({"td_inner_mode": "FAST"})
    p = tg.validate_policy(tg.DEFAULT_POLICY)
    out = tg.overlay_cfg({tg.POLICY_KEY: p, "max_add_log_up": 0.03, "max_add_log_down": 0.03}, "REFINE")
    assert out["max_add_log_up"] == pytest.approx(math.log(1.25))
    assert out["max_add_log_down"] == pytest.approx(-math.log(0.8))


def test_td_frozen_inner_execute_runs_td_only(monkeypatch):
    import r1_15a2_td_count_blend_v24917 as tb
    import r1_15a2_finecdf_bridge_v24916 as bm
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    for obj, name in ((bm.DynamicFamilyMetrics, "evaluate"), (bm.NoDirectMatrixWriteTDAdapter, "execute"),
                      (ctrl, "_generation_counts_cfg"), (ctrl, "_td_realization_scales"),
                      (ctrl, "_finecdf_budget_for_cycle")):
        monkeypatch.setattr(obj, name, getattr(obj, name))
    monkeypatch.setattr(tb, "_STATE", {})
    monkeypatch.setattr(tb, "options", lambda: {"w_cnt": 0.65, "w_idp": 0.35, "inner_mode": "FROZEN_PATHS",
                                               "tg_max_trials": 2, "td_realization_max_trials": 3,
                                               "td_inner_max_evaluations": 40})
    tb.install(print_fn=lambda *a: None)
    calls = []
    b = bm.NoDirectMatrixWriteTDAdapter.__new__(bm.NoDirectMatrixWriteTDAdapter)
    epoch = SimpleNamespace(epoch=7)
    b.outer_adapter = SimpleNamespace(v24916_dynamic_skims=SimpleNamespace(current=epoch))
    b.dynamic_skim_enabled = True
    b.dynamic_skim_epoch = None
    b.v = SimpleNamespace(Procedures=SimpleNamespace(Execute=lambda: calls.append("TD")))
    b.assert_isolated = lambda: calls.append("ISOLATED")
    b.read_outputs = lambda: {9101: np.ones((2, 2))}
    b.guard_protected = lambda full=False: calls.append("GUARD")
    monkeypatch.setattr(bm.NoDirectMatrixWriteTDAdapter, "_execute_dynamic_realization",
                        lambda self: calls.append("ASSIGNMENT"))
    out = b.execute()
    assert calls == ["ISOLATED", "TD", "GUARD"] and b.dynamic_skim_epoch is epoch and 9101 in out
    assert ctrl._td_realization_scales({"coupled_demand": {"finecdf_td": {
        "realization_backtracking_scales": [1.0, 0.5, 0.25, 0.125]}}}) == [1.0, 0.5, 0.25]
    stage = ctrl._finecdf_budget_for_cycle({"coupled_demand": {"finecdf_td": {"progressive_schedule": [
        {"through_outer_cycle": 100, "max_iterations": 35, "max_td_evaluations": 180,
         "allow_progress_continue": False}]}}}, 7)
    assert stage["max_td_evaluations"] == 40 and stage["max_iterations"] == 8 and stage["allow_progress_continue"]


# ------------------------------------------------------------- LONG / SCHOOL generation
class _LSVisum:
    def __init__(self, n, attrs, mats, links):
        nos = list(range(1, n + 1))
        self._a = dict(attrs, NO=[float(z) for z in nos])
        self.Net = SimpleNamespace(
            Zones=SimpleNamespace(GetMultiAttValues=self._gmav),
            Matrices=SimpleNamespace(ItemByKey=lambda no: SimpleNamespace(
                GetValues=lambda m=mats[int(no)]: tuple(map(tuple, m)))),
            Links=SimpleNamespace(ItemByKey=lambda a, b: links[(a, b)]))
    def _gmav(self, code, flag=False):
        if code not in self._a:
            raise RuntimeError("missing " + code)
        return tuple((i + 1, v) for i, v in enumerate(self._a[code]))


def test_long_school_design_and_rows(mb):
    import r1_15a2_long_school_generation_v24917 as ls
    inc, zones = synthetic_incidence(n_zones=6)
    n = len(zones)
    rows, summary, problem, sol = zf.fit(inc, zones, all_bounds(zones, -0.05, 0.05), {})
    attrs = {"ADD_PROD_L": [0.2] * n, "ADD_ATT_L": [1.0] * n, "ADD_PROD_SCH": [1.0] * n, "ADD_ATT_SCH": [1.0] * n}
    for a in ("FP_3_LONG_E_noC", "FP_3_LONG_noE_C", "FP_3_LONG_noE_noC", "FP_3_LONG_stud"):
        attrs[a] = [0.0] * n
    attrs["FP_3_LONG_E_C"] = [50.0 / n] * n          # 50 of 60 LONG trips scale with ADD_PROD_L
    one = np.ones((n, n))
    mats = {9225: 0.2 * one, 9226: one, 9111: 60.0 * one / n / n, 9112: 0 * one, 9113: 0 * one,
            9114: 0 * one, 9115: 0 * one}
    class L:
        def __init__(self, v): self.v = v
        def AttValue(self, k): return self.v
    links = {(10 + p, 11 + p): L(500.0) for p in range(n - 1)}
    cfg = {"max_add_log_up": math.log(1.25), "max_add_log_down": -math.log(0.8),
           "api_approved_observations": [{"no": 900 + p, "edge_key": [1, 10 + p, 11 + p], "direction": "DIRECTED"}
                                         for p in range(n - 1)]}
    visum = _LSVisum(n, attrs, mats, links)
    assert ls.available(visum)
    out = ls.design(visum, cfg, zones, inc, problem, sol, {"ADD_PROD_L": {str(z): 0.2 for z in zones}},
                    fit_cfg={"longguard1_allow_long": True})
    s = out["summary"]
    assert s["status"] == "OK"
    assert "long_scaled_share" not in s
    assert s["long_generation_permitted"] is False
    assert s["long_search_status"] == "LONG_SEARCH_INCOMPLETE"
    assert s["long_deferred_reason"] == "LONG_ZONE_PROFILE_INCIDENCE_UNIDENTIFIED"
    assert s["school_zones_changed"] > 0
    rs = ls.rows_at_scale(out, 0.5)
    longs = [r for r in rs if r["attr"] == "ADD_PROD_L"]
    assert longs == []
    assert all(0.75 - 1e-9 <= r["proposed"] <= 2.0 + 1e-9 for r in rs if r["attr"].endswith("_SCH"))
    assert s["sensitivity"]["ls_ridge_relative"] == 0.05
    assert not ls.available(_LSVisum(n, {}, mats, links))


def test_adapter_writes_long_school_rows_with_the_trial(monkeypatch, tmp_path, mb, real_cfg):
    import r1_15a2_trial_adapter_v24917 as a17
    import r1_15a2_runtime_v1 as rtm
    ad, seen = _adapter(monkeypatch, real_cfg, [1, 2], [], {})
    ad.zone_readback_tolerance = 1e-7
    written = []
    monkeypatch.setattr(rtm, "apply_add_candidate", lambda v, rows, zones, **k: written.extend(rows) or
                        [{"status": "OK"} for _ in rows])
    ls = {"steps": {"ADD_PROD_L": {1: 0.1, 2: 0.1}, "ADD_ATT_L": {}, "ADD_PROD_SCH": {2: -0.1}, "ADD_ATT_SCH": {}},
          "current": {"ADD_PROD_L": {1: 0.2, 2: 0.2}, "ADD_ATT_L": {1: 1.0, 2: 1.0},
                      "ADD_PROD_SCH": {1: 1.0, 2: 1.0}, "ADD_ATT_SCH": {1: 1.0, 2: 1.0}},
          "summary": {"status": "OK"}}
    import r1_15a2_mobility_guard_v24917 as mg
    zr = zone_rows([1, 2], 1.0)
    for row in zr:
        for family, attr in mg.MULT_ATTR.items():
            for fp in mg.FP_ATTRS[family]:
                row[fp] = 10.0 * float(row[attr])
    import r1_15a2_core as core
    ctx = {"v24917_ls": ls,
           "projection": core.ProjectionResult(rows=[], family_summaries=[], weighted_rmse=0.0),
           "_genfix2_mobility": {"zone_rows": zr, "zone_attributes": [],
                                  "options": {"enabled": True, "lo": .75, "hi": 1.25}}}
    rows = ad.apply_generation(ctx, 0.5, tmp_path)
    assert len(rows) == 1 and len(written) == 1
    assert {r["attr"] for r in written} == {"ADD_PROD_SCH"}
    assert (tmp_path / "V24917_LONG_SCHOOL_ROWS.json").is_file()
    prev = ad.generation_preview(ctx, 1.0)
    assert prev["v24917_long_school_rows"] == 1


def test_ls_options_validation(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options(tmp_path, environ={"R1_LS_SCHOOL_ENVELOPE": "0.8;1.25"})
    assert o["ls_school_envelope"] == [0.8, 1.25] and o["ls_max_step_up"] == 0.10
    with pytest.raises(RuntimeError):
        dp.validate({"ls_long_envelope_ref": [1.2, 2.0]})
    with pytest.raises(RuntimeError):
        dp.validate({"ls_max_step_down": 0.9})


def test_roster_live_api_audit_sees_only_roster_countlocations(monkeypatch):
    import r1_15a2_live_api_audit as audit
    import r1_15a2_com_compat as com
    roster, meta = _roster()
    monkeypatch.setattr(audit, "com", audit.com)
    roster._patch_live_api_audit(meta)
    cls = _fake_cls(meta)                      # 248 roster + 920444 outside the roster
    coll = SimpleNamespace(GetAll=list(cls.values()))
    seen = [int(o.AttValue("NO")) for o in audit.com.collection_items(coll, "CountLocations")]
    assert sorted(seen) == sorted(meta["countlocation_nos"]) and 920444 not in seen
    other = audit.com.collection_items(SimpleNamespace(GetAll=[1, 2]), "Links")
    assert list(other) == [1, 2]
    assert audit.com.exact_int is com.exact_int and com.collection_items is not audit.com.collection_items


# ------------------------------------------------------------- BLENDFIX1 (live run 20261025_162648)
def _install_blend_with_fake_eval(monkeypatch, fake_eval):
    import r1_15a2_td_count_blend_v24917 as tb
    import r1_15a2_finecdf_bridge_v24916 as bm
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    for obj, name in ((bm.NoDirectMatrixWriteTDAdapter, "execute"), (ctrl, "_generation_counts_cfg"),
                      (ctrl, "_td_realization_scales"), (ctrl, "_finecdf_budget_for_cycle")):
        monkeypatch.setattr(obj, name, getattr(obj, name))
    monkeypatch.setattr(bm.DynamicFamilyMetrics, "evaluate", fake_eval)
    monkeypatch.setattr(tb, "_STATE", {})
    monkeypatch.setattr(tb, "options", lambda: {"w_cnt": 0.65, "w_idp": 0.35, "inner_mode": "FROZEN_PATHS",
                                               "tg_max_trials": 3, "td_realization_max_trials": 3,
                                               "td_inner_max_evaluations": 60})
    tb.install(print_fn=lambda *a: None)
    return tb, bm


def test_blendfix_11d_overlay_simplenamespace_bridge_keeps_pure_survey_metric(monkeypatch):
    """Exact live failure: _dynamic_11d_overlay builds DynamicFamilyMetrics(SimpleNamespace(epoch), ref)."""
    pure = {"WORK_E_C": {"objective": 0.04, "residual": np.array([0.2])}}
    tb, bm = _install_blend_with_fake_eval(
        monkeypatch, lambda self, m: {k: dict(v) for k, v in pure.items()})
    ref = SimpleNamespace(CONFIG={}, TARGETS={"WORK_E_C": {"matrix_nos": [9101]}})
    out = bm.DynamicFamilyMetrics(SimpleNamespace(dynamic_skim_epoch=object()), ref).evaluate({})
    assert out["WORK_E_C"]["objective"] == 0.04
    assert "v24917_count_term" not in out["WORK_E_C"] and ref.CONFIG == {}
    assert not tb.is_td_inner_bridge(SimpleNamespace(dynamic_skim_epoch=1))


def test_blendfix_blend_init_failure_fails_open_for_whole_stage(monkeypatch):
    pure = {"WORK_E_C": {"objective": 0.04, "residual": np.array([0.2])}}
    tb, bm = _install_blend_with_fake_eval(
        monkeypatch, lambda self, m: {k: dict(v) for k, v in pure.items()})
    calls = []

    class Boom:
        def __init__(self, *a, **k):
            calls.append(1)
            raise RuntimeError("no incidence")
    monkeypatch.setattr(tb, "Blend", Boom)
    import tempfile
    bridge = SimpleNamespace(outer_adapter=SimpleNamespace(cfg={}), read_matrix=lambda no: None,
                             zone_order=[1], root=tempfile.mkdtemp(), dynamic_skim_epoch=1)
    assert tb.is_td_inner_bridge(bridge)
    metrics = bm.DynamicFamilyMetrics(bridge, SimpleNamespace(CONFIG={}, TARGETS={}))
    assert metrics.evaluate({})["WORK_E_C"]["objective"] == 0.04
    assert metrics.evaluate({})["WORK_E_C"]["objective"] == 0.04
    assert calls == [1] and tb._STATE["blend_init_failures"] == 1


def test_blendfix_outer_blend_failure_rejects_parent_decision(monkeypatch):
    import r1_15a2_td_count_blend_v24917 as tb
    import r1_15a2_trial_adapter_v24917 as a17
    parent = {"accepted": False, "reasons": ["X"]}
    monkeypatch.setattr(a17.VisumAdapter.__mro__[1], "block_gate", lambda self, *a: dict(parent))
    monkeypatch.setattr(tb, "outer_decision", lambda *a: (_ for _ in ()).throw(KeyError("d12")))
    ad = a17.VisumAdapter.__new__(a17.VisumAdapter)
    ad.cfg, ad.v24917_status = {}, {}
    out = ad.block_gate("TD_FINECDF_SOFT_REFERENCE", {}, {}, [1])
    assert out["accepted"] is False and out["reasons"] == ["X", "V24917_TD_SHARED_OBJECTIVE_UNAVAILABLE"] and "v24917_td_blend_error" in out
    assert ad.v24917_status["td_blend_outer_failures"] == 1


def test_blendfix_preload_loads_lazy_module_by_absolute_path(tmp_path, monkeypatch):
    import sys as _sys
    import r1_15a2_v24917_runtime as r17
    (tmp_path / "r1_15a2_zz_lazy_probe.py").write_text("VALUE = 42\n", encoding="utf-8")
    monkeypatch.setattr(_sys, "path", [p for p in _sys.path if p != str(tmp_path)])
    monkeypatch.delitem(_sys.modules, "r1_15a2_zz_lazy_probe", raising=False)
    # simulate the live failure: package root is NOT importable via sys.path
    import importlib
    real_import = importlib.import_module
    def no_path_import(name, *a, **k):
        if name == "r1_15a2_zz_lazy_probe":
            raise ModuleNotFoundError("No module named %r" % name, name=name)
        return real_import(name, *a, **k)
    monkeypatch.setattr(importlib, "import_module", no_path_import)
    rep = r17.preload_modules(("r1_15a2_zz_lazy_probe",), root=tmp_path)
    assert rep["modules"]["r1_15a2_zz_lazy_probe"] == "LOADED_BY_ABSOLUTE_PATH"
    import r1_15a2_zz_lazy_probe as probe       # now served from sys.modules
    assert probe.VALUE == 42
    monkeypatch.delitem(_sys.modules, "r1_15a2_zz_lazy_probe", raising=False)


def test_blendfix_preload_real_diagfast_modules():
    import r1_15a2_v24917_runtime as r17
    rep = r17.preload_modules()
    assert set(rep["modules"]) == set(r17.LAZY_RUNTIME_MODULES)


def test_skimfix2_more_than_six_active_skims(monkeypatch):
    """Live 25. 10. 17:43: 13 active PrT skim operations (C + EXOG_EE_* + six native)."""
    import r1_15a2_skim_optype_v24917 as so
    import r1_15a2_com_compat as com
    import r1_15a2_dynamic_skim_v24916p2c as ds
    import r1_15a2_finecdf_bridge_v24916 as bm
    import r1_15a2_trial_adapter_v24916p2c_active as act16
    monkeypatch.setattr(ds, "active_native_skim_positions", ds.active_native_skim_positions)
    monkeypatch.setattr(act16, "active_native_skim_positions", act16.active_native_skim_positions)
    monkeypatch.setattr(bm.NoDirectMatrixWriteTDAdapter, "_dynamic_realization_plan",
                        bm.NoDirectMatrixWriteTDAdapter._dynamic_realization_plan)
    monkeypatch.delattr(ds, "_v24917_original_active_positions", raising=False)
    monkeypatch.setattr(com, "SKIMS_PRT", 103)
    monkeypatch.delenv(so.ENV, raising=False)
    base = [_Op(65, 1), _Op(75, 1)] + [_Op(101, 1)] * 4 + [_Op(75, 1)]
    ops = base + [_Op(103, 0)] + [_Op(103, 1)] * 13
    r = so.apply(_visum(ops))
    assert r["method"] == "V24916_CONSTANT_CONFIRMED" and r["active_count"] == 13
    assert act16.active_native_skim_positions is so.active_skim_positions_at_least_6
    rows = [{"no": i + 1, "type": t, "active": a} for i, (t, a) in enumerate(
        [(46, 1), (101, 1)] + [(103, 1)] * 13)]
    monkeypatch.setattr(com, "operation_rows", lambda v: rows)
    skim, groups = ds.active_native_skim_positions(None)
    assert len(skim) == 13
    monkeypatch.setattr(com, "operation_rows", lambda v: rows[:7])
    with pytest.raises(RuntimeError, match="AT_LEAST_6"):
        ds.active_native_skim_positions(None)
    # realization plan of the TD bridge keeps all 13 skims
    br = bm.NoDirectMatrixWriteTDAdapter.__new__(bm.NoDirectMatrixWriteTDAdapter)
    br.dynamic_skim_enabled = True
    br.td_index = 1
    br.inventory = [{"index": 1, "type": 46, "active": 1}, {"index": 2, "type": com.ASSIGNMENT_PRT, "active": 1}] + \
        [{"index": 3 + k, "type": 103, "active": 1} for k in range(13)]
    br.outer_adapter = SimpleNamespace(cfg={"supply": {"assignment_operations": [{"no": 2}]}})
    plan = br._dynamic_realization_plan()
    assert plan["dynamic_skim_operation_positions"] == list(range(3, 16))
    assert set(range(1, 16)) <= set(plan["selected_operation_positions"])
    assert all(r["active"] == 1 for r in br.inventory)


# ----------------------------------------------------------- BALANCE1 (hard P/A balance)
def test_hard_balance_exact_and_soft_mode_selectable():
    """Live 26.10.: soft penalty gave P +64k / A -2.4k; HARD keeps sum P u = sum A v exactly."""
    inc, zones = synthetic_incidence(n_zones=12, residual_factor=3.0)
    bounds = all_bounds(zones, DN, math.log(1.5))
    p = zf.build_problem(inc, zones, bounds, {})
    hard = zf.solve(p, {})
    soft = zf.solve(p, {"balance_mode": "SOFT", "balance_weight_relative": 0.01})
    assert hard["balance_mode"] == "HARD"
    for fam, rec in hard["balance"].items():
        assert abs(rec["linear_pa_gap"]) <= 1e-6 * rec["margin_total"]
        x = hard["x"]
        assert np.all(x >= p.lower - 1e-12) and np.all(x <= p.upper + 1e-12)
    assert soft["balance_mode"] == "SOFT"
    assert hard["objective_final"] < hard["objective_initial"]


def test_projection_box_hyperplane():
    rng = np.random.default_rng(5)
    for _ in range(20):
        n = 30
        v = np.r_[rng.random(15) * 10, -rng.random(15) * 10]
        lo, hi = -rng.random(n), rng.random(n)
        z = rng.normal(size=n) * 2
        x = zf.project_box_hyperplanes(z, lo, hi, [v])
        assert abs(v @ x) <= 1e-8 * np.abs(v).sum()
        assert np.all(x >= lo - 1e-12) and np.all(x <= hi + 1e-12)


def test_hard_balance_design_passes_gate_without_attenuation(mb, real_cfg):
    import R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1 as master
    inc, zones = synthetic_incidence(n_zones=12, residual_factor=3.0)
    cfg = tg.overlay_cfg(real_cfg, "CATCH_UP")
    zr = zone_rows(zones, value=1.0)
    rows, summary, _, sol = zf.fit(inc, zones, tg.zone_bounds(mb, zr, cfg), cfg, tg.DEFAULT_POLICY["fit"])
    mt = summary["margin_totals"]
    for fam in ("WORK", "SERVICE"):
        assert mt["%s_PROD_delta" % fam] > 0 and mt["%s_ATT_delta" % fam] > 0
    design = mb.design_generation_candidates(rows, zr, cfg, scale=0.85)
    assert master.generation_apply_gate(design, cfg)["passes"]
    reb = design["summary"]["bound_constrained_projection"]["role_rebalance"]
    assert all(v.get("scale", 1.0) > 0.8 for v in reb.values()), reb


@pytest.mark.parametrize('phase', ['CATCH_UP', 'REFINE'])
@pytest.mark.parametrize('reference', [1.0, 8.0])
@pytest.mark.parametrize('current_ratio', [2.0, 9.5])
def test_zahr_four_coefficients_reach_new_band_with_fixed_reference_and_step_caps(mb, real_cfg, phase, reference, current_ratio):
    cfg = tg.overlay_cfg(real_cfg, phase)
    attrs = ('ZAHR_PROD_WORK', 'ZAHR_ATR_WORK', 'ZAHR_PROD_SERV', 'ZAHR_ATR_SERV')
    current = reference * current_ratio
    zone = {'zone_no': 1, 'NOT_ZAHR': 0., 'ZAHR_SUSED': 1., 'POP_ZP': 1000.,
            **{a: current for a in attrs}}
    zeros = dict(zone, zone_no=2, **{a: 0. for a in attrs})
    references = {a: {'1': reference, '2': 0.} for a in attrs}
    bounds = tg.zone_bounds(mb, [zone, zeros], cfg, references)
    expected_step = min(cfg['max_add_log_up'], math.log(10. / current_ratio))
    assert len(bounds) == 4  # the structural-zero zone remains unavailable
    for b in bounds.values():
        assert b[1] == pytest.approx(expected_step)
    projection = [{'zone_no': 1, 'family': f, 'role': role,
                   'log_step': 1., 'base_margin_volume': 1000.}
                  for f in ('WORK', 'SERVICE') for role in ('PROD', 'ATT')]
    result = mb.design_generation_candidates(projection, [zone, zeros], cfg,
                                              reference_values=references, scale=1.)
    candidates = result['candidate_rows']
    assert {r['attr'] for r in candidates} == set(attrs)
    for row in candidates:
        assert row['proposed'] == pytest.approx(current * math.exp(expected_step))
        assert .5 * reference <= row['proposed'] <= 10. * reference + 1.e-10
        assert math.log(row['proposed'] / current) <= cfg['max_add_log_up'] + 1.e-10


@pytest.mark.parametrize('phase', ['CATCH_UP', 'REFINE'])
def test_zahr_lower_bound_and_out_of_band_hold_or_recover_survive(mb, real_cfg, phase):
    cfg = tg.overlay_cfg(real_cfg, phase)
    for current in (.51, 12.):
        zone = {'zone_no': 1, 'NOT_ZAHR': 0., 'ZAHR_SUSED': 1., 'POP_ZP': 1000.,
                **{a: current for a in ('ZAHR_PROD_WORK', 'ZAHR_ATR_WORK', 'ZAHR_PROD_SERV', 'ZAHR_ATR_SERV')}}
        refs = {a: {'1': 1.} for a in zone if a.startswith('ZAHR_') and a != 'ZAHR_SUSED'}
        bounds = tg.zone_bounds(mb, [zone], cfg, refs)
        for low, high in bounds.values():
            assert low >= math.log(.5/current) - 1.e-10
            if current > 10.:
                assert high == pytest.approx(0.)
