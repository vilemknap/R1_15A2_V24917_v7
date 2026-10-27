# -*- coding: utf-8 -*-
"""Run-time demand policy: sparse TD, early stop on stationarity, scaled TG envelope.

Activated by R1_15A2_AGGRESSIVE_TGTD_V1_FIX1_COMBUSY_TD09C16_DIAGFAST_V2_DIRECT.py.
Protected files stay unchanged; the coupled controller and r1_15a2_multiblock
are patched in memory only (same pattern as the TG gate hotfix).

1. TD (FineCDF b/c re-calibration) no longer runs in every outer cycle.
   td_policy = ALWAYS   -> previous behaviour
               EVERY_N  -> TD in cycles N, 2N, 3N ... (default N = 5) and,
                           if td_when_generation_plateau, in every cycle in
                           which TG accepted no change
               OFF      -> TD never runs
   A skipped TD returns the unchanged accepted state with
   ``progress_continue=True``; the controller records the cycle as
   PROGRESS_CONTINUE_DEMAND (never as stationarity) and continues with TG.

2. Early stop. FRESH100 forces all 100 outer cycles even after the demand
   search is stationary. With stop_when_stationary_cycles = K > 0 the run ends
   (cooperative stop, last accepted state, normal final verification) after K
   consecutive cycles in which TG accepted nothing AND TD actually ran,
   completed its search and accepted nothing.

3. generation_envelope_scale = s (written by R1_DEMAND_UPLIFT_TO_TARGET.py).
   The demand uplift multiplies ADD_PROD/ADD_ATT by s. The domestic hard
   envelope [0.5, 2.0] and soft band [0.8, 1.25] of these coefficients are
   absolute, so they are multiplied by the same s. ZAHR envelopes are already
   relative to the run-start values; salary is not scaled.

3b. td_first_cycle = true (default): TD always runs in the first demand cycle of a
   run (new start or restart), also during CATCH_UP.
4. td_during_catchup = false (default): the periodic EVERY_N TD is skipped
   while the V24917 Generation phase is CATCH_UP (model/observed < 0.80);
   TD still runs on a TG plateau.  TD only redistributes trip lengths, and in
   the dynamic-skim mode every FineCDF evaluation is a full assignment.

6. TD objective blend (r1_15a2_td_count_blend_v24917): td_count_weight (0.65 =
   65 % counts / 35 % survey), td_inner_mode FROZEN_PATHS|DYNAMIC,
   tg_max_trials, td_realization_max_trials, td_inner_max_evaluations.
5. tg_catchup_enabled = false: the V24917 Generation never enters CATCH_UP
   (no +50 %/cycle volume growth); it always runs REFINE with stage caps.
   Use when the total demand volume is already right.

Options: R1_RUN_OPTIONS.json next to this file, overridden by environment
variables R1_TD_POLICY, R1_TD_EVERY_N, R1_TD_ON_TG_PLATEAU,
R1_STOP_WHEN_STATIONARY, R1_GENERATION_ENVELOPE_SCALE.
"""
from __future__ import annotations

import copy
import functools
import json
import math
import os
from pathlib import Path

RELEASE = 'R1_15A2_DEMAND_POLICY_V1_20261025'
HERE = Path(__file__).resolve().parent
OPTIONS_FILE = 'R1_RUN_OPTIONS.json'
DEFAULTS = {
    'td_policy': 'EVERY_N',
    'td_every_n_cycles': 5,
    'td_when_generation_plateau': True,
    'stop_when_stationary_cycles': 2,
    'generation_envelope_scale': 1.0,
    'td_during_catchup': False,
    'td_first_cycle': True,
    'tg_catchup_enabled': True,
    'td_count_weight': 0.65,
    'td_inner_mode': 'FROZEN_PATHS',
    'td_joint_enabled': False,
    'td_joint_outer_isolates': False,
    'td_joint_max_isolates': 2,
    'tg_max_trials': 3,
    'td_realization_max_trials': 3,
    'td_inner_max_evaluations': 60,
    'ls_max_step_up': 0.10,
    'ls_max_step_down': 0.10,
    'ls_school_envelope': [0.67, 1.5],
    'ls_long_envelope_ref': [0.5, 1.5],
    'ls_ridge_relative': 0.05,
    'iz_enabled': True,
    'iz_matrix_no': 9002,
    'iz_min_share_select': 0.70,
    'iz_min_production_select': 5000.0,
    'iz_zones': [],
    'iz_exclude_zones': [],
    'iz_max_penalty_min': 15.0,
    'iz_max_step_min': 5.0,
    'iz_probe_min': 2.0,
    'iz_min_intrazonal_share': 0.40,
    'iz_max_iterations': 3,
    'iz_ridge_relative': 0.05,
    'iz_max_cycle_change_min': 2.5,
    'iz_split_realization': True,
    'ic_enabled': True,
    'ic_mode': 'RATIO',
    'ic_skim_dseg': 'NATIVE_CW',
    'ic_start_model_obs_ratio': 0.80,
    'ic_start_cycle': 0,
    'ic_lambda': 0.5,
    'ic_ratio_max': 4.0,
    'ic_min_rel_change': 0.002,
    'fa_enabled': True,
    'fa_skip_positions': [1, 15, 17, 18, 19],
    'fa_blocks': ['GENERATION'],
    'ts_enabled': True,
    'ts_robust_margin': 0.15,
    'ts_min_scale': 0.05,
    'ts_max_scale': 1.0,
    'ts_grid_points': 20,
    'perf3_enabled': True,
    'cb_max_wait_seconds': 900.0,
    'cb_block_retries': 3,
    'bd_enabled': True,
    'bd_zones': list(range(650, 681)),
    'sp_enabled': True,
    'sp_every_n_cycles': 1,
    'sp_start_cycle': 1,
    'sp_max_trials': 2,
    'sp_step_units': [8, 4],
    'sp_max_groups': 12,
    'sp_max_edges': 120,
    'sp_min_driver_geh': 10.0,
    'sp_drivers': 'AUTO',
    'sp_cold_reset_position': 15,
    'sp_min_attribution_coverage': 0.5,
    'sev_max_single_profile_geh_increase': 25.0,
    'sev_max_high_geh_increase': 15.0,
    'sev_extend_early_horizon': True,
    'sev_protected_after_hard_geh': 0.0,
    'rb_tolerant_diagnostics': True,
    'rb_roster_reuse_proof': True,
    'td_max_survey_degradation': 1.25,
    'mg_enabled': True,
    'mg_min_ratio': 0.75,
    'mg_max_ratio': 1.25,
}
ENV = {
    'td_policy': 'R1_TD_POLICY',
    'td_every_n_cycles': 'R1_TD_EVERY_N',
    'td_when_generation_plateau': 'R1_TD_ON_TG_PLATEAU',
    'stop_when_stationary_cycles': 'R1_STOP_WHEN_STATIONARY',
    'generation_envelope_scale': 'R1_GENERATION_ENVELOPE_SCALE',
    'td_during_catchup': 'R1_TD_DURING_CATCHUP',
    'td_first_cycle': 'R1_TD_FIRST_CYCLE',
    'tg_catchup_enabled': 'R1_TG_CATCHUP',
    'td_count_weight': 'R1_TD_COUNT_WEIGHT',
    'td_inner_mode': 'R1_TD_INNER_MODE',
    'td_joint_enabled': 'R1_TD_JOINT_ENABLED',
    'td_joint_outer_isolates': 'R1_TD_JOINT_OUTER_ISOLATES',
    'td_joint_max_isolates': 'R1_TD_JOINT_MAX_ISOLATES',
    'tg_max_trials': 'R1_TG_MAX_TRIALS',
    'td_realization_max_trials': 'R1_TD_REALIZATION_MAX_TRIALS',
    'td_inner_max_evaluations': 'R1_TD_INNER_MAX_EVALS',
    'ls_max_step_up': 'R1_LS_MAX_STEP_UP',
    'ls_max_step_down': 'R1_LS_MAX_STEP_DOWN',
    'ls_school_envelope': 'R1_LS_SCHOOL_ENVELOPE',
    'ls_long_envelope_ref': 'R1_LS_LONG_ENVELOPE_REF',
    'ls_ridge_relative': 'R1_LS_RIDGE',
    'iz_enabled': 'R1_IZ_ENABLED',
    'iz_matrix_no': 'R1_IZ_MATRIX_NO',
    'iz_min_share_select': 'R1_IZ_MIN_SHARE_SELECT',
    'iz_min_production_select': 'R1_IZ_MIN_PRODUCTION_SELECT',
    'iz_zones': 'R1_IZ_ZONES',
    'iz_exclude_zones': 'R1_IZ_EXCLUDE_ZONES',
    'iz_max_penalty_min': 'R1_IZ_MAX_PENALTY_MIN',
    'iz_max_step_min': 'R1_IZ_MAX_STEP_MIN',
    'iz_probe_min': 'R1_IZ_PROBE_MIN',
    'iz_min_intrazonal_share': 'R1_IZ_MIN_INTRAZONAL_SHARE',
    'iz_max_iterations': 'R1_IZ_MAX_ITERATIONS',
    'iz_ridge_relative': 'R1_IZ_RIDGE',
    'iz_max_cycle_change_min': 'R1_IZ_MAX_CYCLE_CHANGE_MIN',
    'iz_split_realization': 'R1_IZ_SPLIT_REALIZATION',
    'ic_enabled': 'R1_IC_ENABLED',
    'ic_mode': 'R1_IC_MODE',
    'ic_skim_dseg': 'R1_IC_SKIM_DSEG',
    'ic_start_model_obs_ratio': 'R1_IC_START_RATIO',
    'ic_start_cycle': 'R1_IC_START_CYCLE',
    'ic_lambda': 'R1_IC_LAMBDA',
    'ic_ratio_max': 'R1_IC_RATIO_MAX',
    'ic_min_rel_change': 'R1_IC_MIN_REL_CHANGE',
    'fa_enabled': 'R1_FA_ENABLED',
    'fa_skip_positions': 'R1_FA_SKIP_POSITIONS',
    'fa_blocks': 'R1_FA_BLOCKS',
    'ts_enabled': 'R1_TS_ENABLED',
    'ts_robust_margin': 'R1_TS_ROBUST_MARGIN',
    'ts_min_scale': 'R1_TS_MIN_SCALE',
    'ts_max_scale': 'R1_TS_MAX_SCALE',
    'ts_grid_points': 'R1_TS_GRID_POINTS',
    'perf3_enabled': 'R1_PERF3_ENABLED',
    'cb_max_wait_seconds': 'R1_CB_MAX_WAIT_SECONDS',
    'cb_block_retries': 'R1_CB_BLOCK_RETRIES',
    'bd_enabled': 'R1_BD_ENABLED',
    'bd_zones': 'R1_BD_ZONES',
    'sp_enabled': 'R1_SP_ENABLED',
    'sp_every_n_cycles': 'R1_SP_EVERY_N',
    'sp_start_cycle': 'R1_SP_START_CYCLE',
    'sp_max_trials': 'R1_SP_MAX_TRIALS',
    'sp_step_units': 'R1_SP_STEP_UNITS',
    'sp_max_groups': 'R1_SP_MAX_GROUPS',
    'sp_max_edges': 'R1_SP_MAX_EDGES',
    'sp_min_driver_geh': 'R1_SP_MIN_DRIVER_GEH',
    'sp_drivers': 'R1_SP_DRIVERS',
    'sp_cold_reset_position': 'R1_SP_COLD_RESET_POSITION',
    'sp_min_attribution_coverage': 'R1_SP_MIN_ATTRIBUTION_COVERAGE',
    'sev_max_single_profile_geh_increase': 'R1_SEV_MAX_SINGLE_PROFILE_GEH_INCREASE',
    'sev_max_high_geh_increase': 'R1_SEV_MAX_HIGH_GEH_INCREASE',
    'sev_extend_early_horizon': 'R1_SEV_EXTEND_EARLY_HORIZON',
    'sev_protected_after_hard_geh': 'R1_SEV_PROTECTED_AFTER_HARD_GEH',
    'rb_tolerant_diagnostics': 'R1_RB_TOLERANT_DIAGNOSTICS',
    'rb_roster_reuse_proof': 'R1_RB_ROSTER_REUSE_PROOF',
    'td_max_survey_degradation': 'R1_TD_MAX_SURVEY_DEGRADATION',
    'mg_enabled': 'R1_MG_ENABLED',
    'mg_min_ratio': 'R1_MG_MIN_RATIO',
    'mg_max_ratio': 'R1_MG_MAX_RATIO',
}
SKIP_REASON = 'TD_SKIPPED_BY_RUN_POLICY'
_ACTIVE = {}


def _bool(value, name):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'ano', 'on'):
        return True
    if text in ('0', 'false', 'no', 'ne', 'off'):
        return False
    raise RuntimeError('R1_RUN_OPTION_INVALID_BOOL:%s=%r' % (name, value))


def validate(raw):
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in raw and raw[key] is not None:
            out[key] = raw[key]
    policy = str(out['td_policy']).strip().upper()
    if policy not in ('ALWAYS', 'EVERY_N', 'OFF'):
        raise RuntimeError('R1_RUN_OPTION_INVALID:td_policy=%r' % out['td_policy'])
    out['td_policy'] = policy
    try:
        n = int(str(out['td_every_n_cycles']).strip())
    except ValueError:
        raise RuntimeError('R1_RUN_OPTION_INVALID:td_every_n_cycles=%r' % out['td_every_n_cycles'])
    if not 1 <= n <= 100:
        raise RuntimeError('R1_RUN_OPTION_RANGE:td_every_n_cycles must be 1..100')
    out['td_every_n_cycles'] = n
    out['td_when_generation_plateau'] = _bool(out['td_when_generation_plateau'],
                                              'td_when_generation_plateau')
    out['td_during_catchup'] = _bool(out['td_during_catchup'], 'td_during_catchup')
    out['td_first_cycle'] = _bool(out['td_first_cycle'], 'td_first_cycle')
    out['tg_catchup_enabled'] = _bool(out['tg_catchup_enabled'], 'tg_catchup_enabled')
    try:
        w = float(str(out['td_count_weight']).strip().replace(',', '.'))
    except ValueError:
        raise RuntimeError('R1_RUN_OPTION_INVALID:td_count_weight=%r' % out['td_count_weight'])
    if not math.isfinite(w) or not 0.0 <= w <= 1.0:
        raise RuntimeError('R1_RUN_OPTION_RANGE:td_count_weight must be 0..1')
    out['td_count_weight'] = w
    mode = str(out['td_inner_mode']).strip().upper()
    if mode not in ('FROZEN_PATHS', 'DYNAMIC'):
        raise RuntimeError('R1_RUN_OPTION_INVALID:td_inner_mode=%r' % out['td_inner_mode'])
    out['td_inner_mode'] = mode
    for key in ('td_joint_enabled', 'td_joint_outer_isolates'):
        out[key] = _bool(out[key], key)
    value = out['td_joint_max_isolates']
    try:
        value = int(str(value).strip())
    except (TypeError, ValueError):
        raise RuntimeError('R1_RUN_OPTION_INVALID:td_joint_max_isolates')
    if not 0 <= value <= 2:
        raise RuntimeError('R1_RUN_OPTION_RANGE:td_joint_max_isolates must be 0..2')
    out['td_joint_max_isolates'] = value
    for key, lo, hi in (('tg_max_trials', 1, 6), ('td_realization_max_trials', 1, 7),
                        ('td_inner_max_evaluations', 5, 400)):
        try:
            v = int(str(out[key]).strip())
        except ValueError:
            raise RuntimeError('R1_RUN_OPTION_INVALID:%s=%r' % (key, out[key]))
        if not lo <= v <= hi:
            raise RuntimeError('R1_RUN_OPTION_RANGE:%s must be %d..%d' % (key, lo, hi))
        out[key] = v
    for key, lo, hi in (('ls_max_step_up', 0.0, 1.0), ('ls_max_step_down', 0.0, 0.5),
                        ('ls_ridge_relative', 1e-6, 10.0)):
        try:
            v = float(str(out[key]).strip().replace(',', '.'))
        except ValueError:
            raise RuntimeError('R1_RUN_OPTION_INVALID:%s=%r' % (key, out[key]))
        if not (math.isfinite(v) and lo <= v <= hi):
            raise RuntimeError('R1_RUN_OPTION_RANGE:%s must be %g..%g' % (key, lo, hi))
        out[key] = v
    for key in ('ls_school_envelope', 'ls_long_envelope_ref'):
        raw = out[key]
        if isinstance(raw, str):
            raw = [x for x in raw.replace(';', ',').split(',') if x.strip()]
        try:
            lo, hi = (float(str(x).strip()) for x in raw)
        except Exception:
            raise RuntimeError('R1_RUN_OPTION_INVALID:%s=%r' % (key, out[key]))
        if not (0.0 < lo < 1.0 < hi <= 20.0):
            raise RuntimeError('R1_RUN_OPTION_RANGE:%s must be [lo<1<hi]' % key)
        out[key] = [lo, hi]
    out.update(_validate_iz(out))
    try:
        k = int(str(out['stop_when_stationary_cycles']).strip())
    except ValueError:
        raise RuntimeError('R1_RUN_OPTION_INVALID:stop_when_stationary_cycles=%r'
                           % out['stop_when_stationary_cycles'])
    if not 0 <= k <= 100:
        raise RuntimeError('R1_RUN_OPTION_RANGE:stop_when_stationary_cycles must be 0..100')
    out['stop_when_stationary_cycles'] = k
    try:
        s = float(str(out['generation_envelope_scale']).strip().replace(',', '.'))
    except ValueError:
        raise RuntimeError('R1_RUN_OPTION_INVALID:generation_envelope_scale=%r'
                           % out['generation_envelope_scale'])
    if not math.isfinite(s) or not 0.2 <= s <= 20.0:
        raise RuntimeError('R1_RUN_OPTION_RANGE:generation_envelope_scale must be 0.2..20')
    out['generation_envelope_scale'] = s
    return out


def _float_opt(out, key, lo, hi):
    try:
        v = float(str(out[key]).strip().replace(',', '.'))
    except ValueError:
        raise RuntimeError('R1_RUN_OPTION_INVALID:%s=%r' % (key, out[key]))
    if not (math.isfinite(v) and lo <= v <= hi):
        raise RuntimeError('R1_RUN_OPTION_RANGE:%s must be %g..%g' % (key, lo, hi))
    return v


def _zone_list(raw, key):
    if raw in (None, ''):
        return []
    if isinstance(raw, str):
        raw = [x for x in raw.replace(';', ',').split(',') if x.strip()]
    try:
        zones = set()
        for x in raw:
            t = str(x).strip()
            if '-' in t.lstrip('-')[0:] and not t.startswith('-'):
                a, b = (int(float(v)) for v in t.split('-', 1))   # range "650-680"
                if b < a or b - a > 5000:
                    raise ValueError(t)
                zones.update(range(a, b + 1))
            else:
                zones.add(int(float(t)))
        zones = sorted(zones)
    except Exception:
        raise RuntimeError('R1_RUN_OPTION_INVALID:%s=%r' % (key, raw))
    if any(z <= 0 for z in zones):
        raise RuntimeError('R1_RUN_OPTION_RANGE:%s zone numbers must be positive' % key)
    return zones


def _validate_iz(out):
    """IZPEN1 intrazonal impedance lever options."""
    v = {'iz_enabled': _bool(out['iz_enabled'], 'iz_enabled')}
    try:
        no = int(float(str(out['iz_matrix_no']).strip()))
    except ValueError:
        raise RuntimeError('R1_RUN_OPTION_INVALID:iz_matrix_no=%r' % out['iz_matrix_no'])
    if no <= 0 or no in (9001, 9697, 9116) or 9101 <= no <= 9299:
        raise RuntimeError('R1_RUN_OPTION_RANGE:iz_matrix_no must be a free matrix (not 9001/9697/9116/91xx/92xx)')
    v['iz_matrix_no'] = no
    v['iz_min_share_select'] = _float_opt(out, 'iz_min_share_select', 0.0, 1.0)
    v['iz_min_production_select'] = _float_opt(out, 'iz_min_production_select', 0.0, 1e9)
    v['iz_zones'] = _zone_list(out['iz_zones'], 'iz_zones')
    v['iz_exclude_zones'] = _zone_list(out['iz_exclude_zones'], 'iz_exclude_zones')
    v['iz_max_penalty_min'] = _float_opt(out, 'iz_max_penalty_min', 0.5, 120.0)
    v['iz_max_step_min'] = _float_opt(out, 'iz_max_step_min', 0.1, 60.0)
    v['iz_probe_min'] = _float_opt(out, 'iz_probe_min', 0.05, 30.0)
    if v['iz_probe_min'] > v['iz_max_penalty_min']:
        raise RuntimeError('R1_RUN_OPTION_RANGE:iz_probe_min must be <= iz_max_penalty_min')
    v['iz_min_intrazonal_share'] = _float_opt(out, 'iz_min_intrazonal_share', 0.0, 0.95)
    try:
        it = int(str(out['iz_max_iterations']).strip())
    except ValueError:
        raise RuntimeError('R1_RUN_OPTION_INVALID:iz_max_iterations=%r' % out['iz_max_iterations'])
    if not 0 <= it <= 20:
        raise RuntimeError('R1_RUN_OPTION_RANGE:iz_max_iterations must be 0..20')
    v['iz_max_iterations'] = it
    v['iz_ridge_relative'] = _float_opt(out, 'iz_ridge_relative', 1e-6, 10.0)
    v['iz_max_cycle_change_min'] = _float_opt(out, 'iz_max_cycle_change_min', 0.0, 120.0)   # 0 = no cap
    v['iz_split_realization'] = _bool(out['iz_split_realization'], 'iz_split_realization')
    # ICONG1: congested TD impedance in the late phase
    v['ic_enabled'] = _bool(out['ic_enabled'], 'ic_enabled')
    mode = str(out['ic_mode']).strip().upper()
    if mode not in ('RATIO', 'ABSOLUTE'):
        raise RuntimeError('R1_RUN_OPTION_INVALID:ic_mode=%r (RATIO|ABSOLUTE)' % out['ic_mode'])
    v['ic_mode'] = mode
    dseg = str(out['ic_skim_dseg']).strip().upper()
    if not dseg:
        raise RuntimeError('R1_RUN_OPTION_INVALID:ic_skim_dseg')
    v['ic_skim_dseg'] = dseg
    v['ic_start_model_obs_ratio'] = _float_opt(out, 'ic_start_model_obs_ratio', 0.0, 2.0)
    try:
        c = int(str(out['ic_start_cycle']).strip())
    except ValueError:
        raise RuntimeError('R1_RUN_OPTION_INVALID:ic_start_cycle=%r' % out['ic_start_cycle'])
    if not 0 <= c <= 100:
        raise RuntimeError('R1_RUN_OPTION_RANGE:ic_start_cycle must be 0..100 (0 = ratio only)')
    v['ic_start_cycle'] = c
    v['ic_lambda'] = _float_opt(out, 'ic_lambda', 0.05, 1.0)
    v['ic_ratio_max'] = _float_opt(out, 'ic_ratio_max', 1.05, 20.0)
    v['ic_min_rel_change'] = _float_opt(out, 'ic_min_rel_change', 0.0, 0.5)
    # FASTASSIGN1: warm-start Generation trial assignment
    v['fa_enabled'] = _bool(out['fa_enabled'], 'fa_enabled')
    v['fa_skip_positions'] = _zone_list(out['fa_skip_positions'], 'fa_skip_positions')
    raw = out['fa_blocks']
    if isinstance(raw, str):
        raw = [x for x in raw.replace(';', ',').split(',') if x.strip()]
    blocks = sorted({str(x).strip().upper() for x in (raw or [])})
    if any(b not in ('GENERATION',) for b in blocks):
        raise RuntimeError('R1_RUN_OPTION_INVALID:fa_blocks=%r (only GENERATION is supported)' % out['fa_blocks'])
    v['fa_blocks'] = blocks
    # STEP1: computed Generation step, eligible trial kept in place
    v['ts_enabled'] = _bool(out['ts_enabled'], 'ts_enabled')
    v['ts_robust_margin'] = _float_opt(out, 'ts_robust_margin', 0.0, 1.0)
    v['ts_min_scale'] = _float_opt(out, 'ts_min_scale', 0.01, 1.0)
    v['ts_max_scale'] = _float_opt(out, 'ts_max_scale', 0.05, 1.0)
    if v['ts_min_scale'] >= v['ts_max_scale']:
        raise RuntimeError('R1_RUN_OPTION_RANGE:ts_min_scale must be < ts_max_scale')
    try:
        g = int(str(out['ts_grid_points']).strip())
    except ValueError:
        raise RuntimeError('R1_RUN_OPTION_INVALID:ts_grid_points=%r' % out['ts_grid_points'])
    if not 4 <= g <= 200:
        raise RuntimeError('R1_RUN_OPTION_RANGE:ts_grid_points must be 4..200')
    v['ts_grid_points'] = g
    v['perf3_enabled'] = _bool(out['perf3_enabled'], 'perf3_enabled')
    # COMBUSY2: rejected Visum calls
    v['cb_max_wait_seconds'] = _float_opt(out, 'cb_max_wait_seconds', 5.0, 7200.0)
    try:
        r = int(str(out['cb_block_retries']).strip())
    except ValueError:
        raise RuntimeError('R1_RUN_OPTION_INVALID:cb_block_retries=%r' % out['cb_block_retries'])
    if not 0 <= r <= 20:
        raise RuntimeError('R1_RUN_OPTION_RANGE:cb_block_retries must be 0..20')
    v['cb_block_retries'] = r
    # BNDGEN1: border-crossing synthetic P/A lever
    v['bd_enabled'] = _bool(out['bd_enabled'], 'bd_enabled')
    v['bd_zones'] = _zone_list(out['bd_zones'], 'bd_zones')
    # SUPPLYMIX1: ADDVAL1 route-choice lever inside the demand cycles
    v['sp_enabled'] = _bool(out['sp_enabled'], 'sp_enabled')
    for key, lo, hi in (('sp_every_n_cycles', 1, 100), ('sp_start_cycle', 1, 1000),
                        ('sp_max_trials', 1, 5), ('sp_max_groups', 1, 80),
                        ('sp_max_edges', 1, 2000), ('sp_cold_reset_position', 1, 10000)):
        try:
            iv = int(str(out[key]).strip())
        except ValueError:
            raise RuntimeError('R1_RUN_OPTION_INVALID:%s=%r' % (key, out[key]))
        if not lo <= iv <= hi:
            raise RuntimeError('R1_RUN_OPTION_RANGE:%s must be %d..%d' % (key, lo, hi))
        v[key] = iv
    raw_units = out['sp_step_units']
    if isinstance(raw_units, str):
        raw_units = [x for x in raw_units.replace(';', ',').split(',') if x.strip()]
    try:
        units = [int(float(str(x).strip())) for x in raw_units]
    except Exception:
        raise RuntimeError('R1_RUN_OPTION_INVALID:sp_step_units=%r' % out['sp_step_units'])
    if not units or any(u < 1 or u > 16 for u in units) or units != sorted(set(units), reverse=True):
        raise RuntimeError('R1_RUN_OPTION_RANGE:sp_step_units must be distinct, descending, 1..16 '
                           '(units of the 0.5 ADDVAL1 lattice = 5 s)')
    v['sp_step_units'] = units
    v['sp_min_driver_geh'] = _float_opt(out, 'sp_min_driver_geh', 0.0, 500.0)
    mode = str(out['sp_drivers']).strip().upper()
    if mode not in ('AUTO', 'OVERLOADED', 'BOTH'):
        raise RuntimeError('R1_RUN_OPTION_INVALID:sp_drivers=%r (AUTO|OVERLOADED|BOTH)' % out['sp_drivers'])
    v['sp_drivers'] = mode
    v['sp_min_attribution_coverage'] = _float_opt(out, 'sp_min_attribution_coverage', 0.05, 1.0)
    # SEVRELAX1: baseline-relative severity budgets (only ever relax the sealed values)
    v['sev_max_single_profile_geh_increase'] = _float_opt(out, 'sev_max_single_profile_geh_increase', 0.0, 200.0)
    v['sev_max_high_geh_increase'] = _float_opt(out, 'sev_max_high_geh_increase', 0.0, 200.0)
    v['sev_extend_early_horizon'] = _bool(out['sev_extend_early_horizon'], 'sev_extend_early_horizon')
    v['sev_protected_after_hard_geh'] = _float_opt(out, 'sev_protected_after_hard_geh', 0.0, 200.0)
    # RBCONS1: rollback verification
    v['rb_tolerant_diagnostics'] = _bool(out['rb_tolerant_diagnostics'], 'rb_tolerant_diagnostics')
    v['rb_roster_reuse_proof'] = _bool(out['rb_roster_reuse_proof'], 'rb_roster_reuse_proof')
    # LONGTRIP1: cap of the TD survey (IDP) objective ratio after/before a TD step
    v['td_max_survey_degradation'] = _float_opt(out, 'td_max_survey_degradation', 1.0, 3.0)
    # MOBILITY1: aggregate trip rate / survey trip rate band
    v['mg_enabled'] = _bool(out['mg_enabled'], 'mg_enabled')
    v['mg_min_ratio'] = _float_opt(out, 'mg_min_ratio', 0.1, 1.0)
    v['mg_max_ratio'] = _float_opt(out, 'mg_max_ratio', 1.0, 5.0)
    return v


def load_options(root=None, environ=None):
    root = Path(root) if root is not None else HERE
    environ = os.environ if environ is None else environ
    raw, sources = {}, {}
    path = root / OPTIONS_FILE
    if path.is_file():
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise RuntimeError('R1_RUN_OPTIONS_NOT_AN_OBJECT:%s' % path)
        for key in DEFAULTS:
            if key in data:
                raw[key] = data[key]
                sources[key] = OPTIONS_FILE
    for key, name in ENV.items():
        value = str(environ.get(name, '')).strip()
        if value:
            raw[key] = value
            sources[key] = 'ENV:' + name
    out = validate(raw)
    out['_sources'] = {k: sources.get(k, 'DEFAULT') for k in DEFAULTS}
    out['_options_file'] = str(path)
    return out


class DemandPolicy:
    """Decides TD per cycle and tracks the stationarity streak."""

    def __init__(self, options):
        self.options = options
        self.records = []
        self.streak = 0
        self.last_generation_changed = None
        self.td_calls = 0

    def td_due(self, outer_cycle, generation_changed):
        o = self.options
        if o['td_policy'] == 'ALWAYS':
            return True, 'ALWAYS'
        if o.get('td_first_cycle', True) and self.td_calls == 0 and o['td_policy'] != 'OFF':
            # first demand cycle of this run (new start or restart): the network/impedance
            # state may have changed since the last TD fit (e.g. edited VD functions)
            return True, 'FIRST_CYCLE_OF_RUN'
        if generation_changed is None:
            # Resumed partial cycle (TD pending) or no TG call in this run yet.
            return True, 'NO_GENERATION_RESULT_THIS_RUN'
        if o['td_policy'] == 'OFF':
            return False, 'OFF'
        if outer_cycle is not None and int(outer_cycle) % o['td_every_n_cycles'] == 0:
            return True, 'EVERY_%d' % o['td_every_n_cycles']
        if o['td_when_generation_plateau'] and generation_changed is False:
            return True, 'GENERATION_PLATEAU'
        return False, 'NOT_DUE'

    def note_generation(self, changed, rec):
        self.last_generation_changed = bool(changed)
        record = rec or {}
        self.last_generation_complete = bool(record.get('search_complete') and
            (record.get('stationarity_confirmed') is True if 'stationarity_confirmed' in record else True))

    def note_td(self, outer_cycle, ran, changed, rec):
        self.td_calls += 1
        inner = (rec or {}).get('inner', {}) or {}
        complete = bool(ran and inner.get('search_complete') is True
                        and inner.get('progress_continue') is not True)
        stationary = bool(ran and complete and not changed
                          and self.last_generation_changed is False
                          and getattr(self, 'last_generation_complete', False))
        self.streak = self.streak + 1 if stationary else 0
        self.records.append({'cycle': outer_cycle, 'td_ran': bool(ran),
                             'td_changed': bool(changed), 'td_search_complete': complete,
                             'generation_changed': self.last_generation_changed,
                             'stationary': stationary, 'streak': self.streak})

    def stop_due(self):
        k = self.options['stop_when_stationary_cycles']
        return k > 0 and self.streak >= k


def wrap_generation(original, policy, controller):
    @functools.wraps(original)
    def generation(adapter, cfg, folder, control, state, diag, anchors, reference, policy_arg,
                   outer_cycle=None):
        if policy.stop_due():
            raise controller.UserStopRequested(
                'R1_DEMAND_STATIONARY_EARLY_STOP_AFTER_%d_CYCLES' % policy.streak)
        result = original(adapter, cfg, folder, control, state, diag, anchors, reference,
                          policy_arg, outer_cycle=outer_cycle)
        # SAFETYFIX1: a deferred LONG/SCHOOL search cannot certify an outer
        # fixed point.  Preserve any valid W/S step; next TD wrapper will mark
        # a recoverable progress continuation instead of terminating the run.
        if getattr(adapter, "v24917_status", {}).get("ls_incomplete_current_cycle", False):
            rec = dict(result[4])
            rec.update(search_complete=False, stationarity_confirmed=False,
                       ls_search_incomplete=True,
                       ls_recovery="CONTINUE_OUTER_LOOP_WITHOUT_CLAIMING_STATIONARITY")
            result = result[:4] + (rec,)
            try:
                controller.atomic_json(Path(folder) / 'GENERATION_BLOCK_RESULT.json', rec)
            except Exception:
                # The result remains in the caller's block record, which is
                # also persisted by the outer controller.
                pass
        policy.note_generation(result[0], result[4])
        if getattr(adapter, "v24917_status", {}).get("ls_incomplete_current_cycle", False):
            policy.last_generation_complete = False
            policy.streak = 0
        return result
    generation.__r1_demand_policy__ = True
    return generation


def skipped_td_record(state, diag, outer_cycle, reason, controller):
    return {
        'status': SKIP_REASON,
        'td_realization_complete': True,
        'changed_rows': [], 'target_changed_rows': [],
        'inner': {'stop_reason': SKIP_REASON, 'progress_continue': True,
                  'search_complete': False, 'changed_rows': [],
                  'skip_policy_reason': reason},
        'state_hash': state['state_hash'],
        'diagnostic_hash': controller.diagnostic_hash(diag),
        'skip_policy_reason': reason, 'outer_cycle': outer_cycle,
        'demand_policy_release': RELEASE,
    }


def catchup_phase(cfg, diag):
    """(phase, ratio) from the V24917 targeted-generation policy, else None."""
    try:
        import r1_15a2_targeted_generation_v24917 as tg
    except ImportError:
        return None
    gen_policy = tg.policy_of(cfg or {})
    if gen_policy is None:
        return None
    try:
        return tg.phase_for(((diag or {}).get('d12') or {}).get('rows') or [], gen_policy)
    except Exception:
        return None


def wrap_td(original, policy, controller):
    @functools.wraps(original)
    def td(adapter, cfg, folder, control, state, diag, package_root, outer_cycle=None):
        due, reason = policy.td_due(outer_cycle, policy.last_generation_changed)
        if due and reason.startswith('EVERY_') and not policy.options.get('td_during_catchup', False):
            phase = catchup_phase(cfg, diag)
            if phase is not None and phase[0] == 'CATCH_UP':
                due, reason = False, 'CATCH_UP_PHASE_MODEL_OBS_%.3f' % phase[1]
        if not due:
            rec = skipped_td_record(state, diag, outer_cycle, reason, controller)
            try:
                Path(folder).mkdir(parents=True, exist_ok=True)
                controller.atomic_json(Path(folder) / 'TD_FINECDF_BLOCK_RESULT.json', rec)
            except Exception:
                pass
            policy.note_td(outer_cycle, False, False, rec)
            return False, state, diag, rec
        if hasattr(adapter, 'v24917_status'):
            adapter.v24917_status['td_outer_incomplete_cycle'] = False
        changed, state2, diag2, rec = original(adapter, cfg, folder, control, state, diag,
                                               package_root, outer_cycle=outer_cycle)
        rec = dict(rec)
        rec['td_run_policy_reason'] = reason
        incomplete = []
        if getattr(adapter, 'v24917_status', {}).get('td_outer_incomplete_cycle', False):
            incomplete.append('TD_SHARED_OBJECTIVE_UNAVAILABLE')
        if getattr(adapter, 'v24917_status', {}).get('ls_incomplete_current_cycle', False):
            incomplete.append('LONG_SCHOOL_DESIGN_UNVERIFIED')
        if incomplete:
            # Recoverable candidate evidence failures must not certify a joint
            # fixed point.  TD rejection has already passed verified rollback;
            # W/S can continue independently when LONG/SCHOOL was deferred.
            inner = dict(rec.get('inner') or {})
            inner.update(progress_continue=True, search_complete=False,
                         stationarity_confirmed=False, stop_reason=incomplete[0])
            rec['inner'] = inner
            rec['incomplete_search_reasons'] = incomplete
            rec['td_outer_evidence_complete'] = 'TD_SHARED_OBJECTIVE_UNAVAILABLE' not in incomplete
            try:
                controller.atomic_json(Path(folder) / 'TD_FINECDF_BLOCK_RESULT.json', rec)
            except Exception as exc:
                # Do not hide an impossible diagnostic publication as success.
                rec['td_evidence_write_error'] = repr(exc)
        policy.note_td(outer_cycle, True, changed, rec)
        return changed, state2, diag2, rec
    td.__r1_demand_policy__ = True
    return td


def patch_envelope(mb, scale):
    """Multiply the absolute domestic ADD envelope and soft band by ``scale``."""
    if abs(scale - 1.0) < 1.0e-12:
        return False
    if getattr(mb._multiplicative_coefficient_bounds, '__r1_envelope_scale__', None) is not None:
        if mb._multiplicative_coefficient_bounds.__r1_envelope_scale__ != scale:
            raise RuntimeError('R1_ENVELOPE_SCALE_ALREADY_PATCHED_WITH_OTHER_VALUE')
        return True
    orig_hard = mb._multiplicative_coefficient_bounds
    orig_soft = mb._soft_multiplier_bounds

    @functools.wraps(orig_hard)
    def hard(branch, cfg, current=None, reference=None):
        low, high, name = orig_hard(branch, cfg, None, reference)
        if name == 'AMDY_LIKE_DOMESTIC_ABSOLUTE_ENVELOPE':
            low, high = low * scale, high * scale
        else:
            return orig_hard(branch, cfg, current, reference)
        if current is not None and math.isfinite(float(current)):
            low = min(low, float(current))
            high = max(high, float(current))
        return low, high, name
    hard.__r1_envelope_scale__ = scale

    @functools.wraps(orig_soft)
    def soft(branch, cfg, current, reference=None):
        low, high = orig_soft(branch, cfg, current, reference)
        if (str(branch).upper() != 'ZAHR' and mb._signed_generation_policy(cfg)
                and math.isfinite(low) and math.isfinite(high)):
            return low * scale, high * scale
        return low, high
    soft.__r1_envelope_scale__ = scale
    mb._multiplicative_coefficient_bounds = hard
    mb._soft_multiplier_bounds = soft
    return True


def activate(launcher, options=None, print_fn=print):
    controller = getattr(launcher, 'coupled_runtime', None)
    if controller is None:
        import r1_15a2_overnight_controller_coupled_v24915p2_force100 as controller
    key = id(controller)
    if key in _ACTIVE:
        return _ACTIVE[key]
    options = load_options() if options is None else options
    policy = DemandPolicy(options)
    controller._generation_update_once = wrap_generation(
        controller._generation_update_once, policy, controller)
    controller._finecdf_td_once = wrap_td(controller._finecdf_td_once, policy, controller)
    import r1_15a2_multiblock as mb
    envelope = patch_envelope(mb, options['generation_envelope_scale'])
    note = {'release': RELEASE,
            'options': {k: options[k] for k in DEFAULTS},
            'option_sources': options.get('_sources', {}),
            'envelope_patched': envelope}
    original_prepare = getattr(launcher, 'prepare_runtime_config', None)
    if original_prepare is not None:
        @functools.wraps(original_prepare)
        def prepare(*args, **kwargs):
            result = original_prepare(*args, **kwargs)
            result[0].setdefault('aggressive_tuning', {})['demand_policy'] = copy.deepcopy(note)
            return result
        launcher.prepare_runtime_config = prepare
    state = {'policy': policy, 'note': note, 'controller': controller.__name__}
    _ACTIVE[key] = state
    print_fn('R1 DEMAND POLICY: td=%s every=%d on_tg_plateau=%s stop_stationary=%d envelope_scale=%g tg_catchup=%s'
             % (options['td_policy'], options['td_every_n_cycles'],
                options['td_when_generation_plateau'], options['stop_when_stationary_cycles'],
                options['generation_envelope_scale'], options['tg_catchup_enabled']))
    return state
