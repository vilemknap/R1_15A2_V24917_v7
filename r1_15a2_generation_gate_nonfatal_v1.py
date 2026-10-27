# -*- coding: utf-8 -*-
"""TG pre-apply gate: reject the candidate instead of failing the whole run.

Cycle 19 of RUN_R261023_152240_581567 stopped with
    V245_GENERATION_TRIAL_ERROR_NOT_A_PLATEAU:GENERATION_GATE:GENERATION_PA_GAP_WORK
at backtracking trial 5 (scale 0.125). ``generation_apply_gate`` runs BEFORE any
zone write in ``apply_generation``; ``_evaluate_candidate`` still performs and
verifies the rollback and returns ``(None, rolled_diag, error)``. The coupled
controller treated every such error as fatal.

This hotfix (in memory, protected files unchanged) converts ONLY errors whose
text starts with ``GENERATION_GATE:`` in block GENERATION into an ineligible
attempt (status REJECTED, reason ``PRE_APPLY_GATE:<reasons>``). The controller
then tries the remaining scales; if none is eligible the block ends as
CONFIGURED_GENERATION_SEARCH_EXHAUSTED (a normal TG plateau) and TD continues.
The 2 % threshold itself is unchanged unless R1_MAX_GENERATION_PA_GAP is set.

Every other error (rollback, readback, COM, solver, data) stays fatal exactly
as before. The controller still verifies the rolled-back diagnostic hash and the
unchanged parent state before the next trial.
"""
from __future__ import annotations

import functools
import math
import os

GATE_PREFIX = 'GENERATION_GATE:'
GAP_ENV = 'R1_MAX_GENERATION_PA_GAP'
RELEASE = 'R1_15A2_GENERATION_GATE_NONFATAL_V1_20261025'
_ACTIVE = {}


def gap_override():
    raw = os.environ.get(GAP_ENV, '').strip()
    if not raw:
        return None
    try:
        value = float(raw.replace(',', '.'))
    except ValueError:
        raise RuntimeError('INVALID_%s:%r' % (GAP_ENV, raw))
    if not math.isfinite(value) or not (0.0 < value <= 0.5):
        raise RuntimeError('INVALID_%s_RANGE_(0,0.5]:%r' % (GAP_ENV, raw))
    return value


def wrap_evaluate(original, events):
    @functools.wraps(original)
    def evaluate(adapter, cfg, policy, block, candidate, rows, context,
                 before, baseline_diag, baseline_value, *args, **kwargs):
        ev, rolled_diag, error = original(adapter, cfg, policy, block, candidate, rows, context,
                                          before, baseline_diag, baseline_value, *args, **kwargs)
        if ev is None and block == 'GENERATION' and str(error or '').startswith(GATE_PREFIX):
            reasons = [r for r in str(error)[len(GATE_PREFIX):].split(';') if r]
            decision = {'accepted': False,
                        'reasons': ['PRE_APPLY_GATE:' + r for r in reasons],
                        'pre_apply_generation_gate_rejected': True,
                        'original_error': str(error),
                        'hotfix': RELEASE}
            ev = {'eligible': False, 'decision': decision,
                  'after_value': baseline_value, 'candidate': candidate,
                  'rows': [], 'gap': None, 'pre_apply_gate_rejected': True}
            events.append({'candidate': candidate, 'error': str(error)})
        return ev, rolled_diag, error
    evaluate.__r1_generation_gate_nonfatal__ = True
    return evaluate


def activate(launcher):
    """Patch the coupled controller used by the prepared parent launcher."""
    controller = getattr(launcher, 'coupled_runtime', None)
    if controller is None:
        import r1_15a2_overnight_controller_coupled_v24915p2_force100 as controller
    if getattr(controller._evaluate_candidate, '__r1_generation_gate_nonfatal__', False):
        return _ACTIVE.get(id(controller))
    events = []
    controller._evaluate_candidate = wrap_evaluate(controller._evaluate_candidate, events)
    override = gap_override()
    original_prepare = launcher.prepare_runtime_config

    @functools.wraps(original_prepare)
    def prepare(*args, **kwargs):
        result = original_prepare(*args, **kwargs)
        cfg = result[0]
        note = {'release': RELEASE,
                'pre_apply_generation_gate': 'REJECT_CANDIDATE_NOT_FAIL_RUN',
                'max_generation_pa_relative_gap_default': cfg.get('max_generation_pa_relative_gap', 0.02),
                'max_generation_pa_relative_gap_override': override}
        if override is not None:
            cfg['max_generation_pa_relative_gap'] = override
        cfg.setdefault('aggressive_tuning', {})['generation_gate_nonfatal'] = note
        return result
    launcher.prepare_runtime_config = prepare
    state = {'controller': controller.__name__, 'events': events, 'gap_override': override}
    _ACTIVE[id(controller)] = state
    return state
