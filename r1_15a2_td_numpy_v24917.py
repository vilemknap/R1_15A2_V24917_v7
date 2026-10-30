"""TD NumPy/COM reuse with unchanged source hashes and FineCDF arithmetic.

Installed on the sealed classes in memory. Grid preparation lives for exactly
one evaluate() call; all six native DIS matrices remain authoritative.
"""
from __future__ import annotations

import functools
import math
from contextlib import contextmanager
from contextvars import ContextVar
import numpy as np

import r1_15a2_dynamic_skim_v24916p2c as dyn
import r1_15a2_finecdf_bridge_v24916 as bridge
import r1_15a2_runtime_v1 as rt
from r1_15a2_path_incidence_v24917 import matrix_values_hash
from r1_15a2_supply import SupplyContractError

RELEASE = 'R1_V24917_TD_NUMPY_REUSE_20261030'
SKIM_WEIGHT_DSEGS = dyn.REQUIRED_NATIVE_DSEGS[:4]
SKIM_WEIGHT_SCOPE = ContextVar('v24917_skim_weight_scope', default=None)


@contextmanager
def skim_weight_scope(adapter):
    token = SKIM_WEIGHT_SCOPE.set(adapter)
    try:
        yield
    finally:
        SKIM_WEIGHT_SCOPE.reset(token)


def read_skim_weights(adapter):
    """Read only the four demand weights used by native family distance blends.

    Full Generation/path-cache readers retain their original public contract.
    Selection is by normalized exact DSeg identity, not matrix-number guesses.
    """
    cfg = adapter.cfg
    codes = [rt.norm_code(x) for x in cfg.get('path_export_dsegs', ())]
    if not set(SKIM_WEIGHT_DSEGS) <= set(codes) or len(codes) != len(set(codes)):
        raise SupplyContractError('TD_PERF_SKIM_WEIGHT_DSEG_SCOPE')
    rows = rt.selected_passenger_dsegs(adapter.visum, dict(cfg, path_export_dsegs=list(SKIM_WEIGHT_DSEGS)))
    by = {r['norm_code']: r for r in rows}
    if set(by) != set(SKIM_WEIGHT_DSEGS) or len(rows) != len(by):
        raise SupplyContractError('TD_PERF_SKIM_WEIGHT_DSEG_BINDING')
    n = int(cfg['expected_zones'])
    out = {}
    for code in SKIM_WEIGHT_DSEGS:
        a = np.asarray(by[code]['object'].ODMatrix.GetValues(), dtype=float)
        if a.shape != (n, n) or not np.isfinite(a).all() or np.any(a < -1.e-10):
            raise SupplyContractError('PATH_EPOCH_INVALID_LIVE_OD_MATRIX:' + code)
        out[code] = a
    return out


def read_epoch(self, assignment_token, operation_positions, live_matrices):
    """Original skim read/weight protocol, with exact blocked hashes.

    LONG and FOREIGN are owned exact copies of their native DIS arrays, so
    their already computed source hashes are valid within this same read.
    """
    zones = tuple(int(z) for z in self.adapter.zones)
    n = len(zones)
    zhash = dyn.ordered_zone_hash(zones)
    rows = dyn._native_dis_rows(self.adapter)
    matrices, meta = {}, {}
    for dseg in dyn.REQUIRED_NATIVE_DSEGS:
        row = rows[dseg]
        no = int(row['matrix_no_int'])
        values = dyn._matrix_values(self.adapter, no, n, 'DIS:' + dseg)
        matrices[dseg] = values
        meta[dseg] = {
            'matrix_no': no, 'matrix_code': str(row.get('matrix_code', 'DIS')),
            'dseg_code': str(row.get('dseg_code', dseg)), 'canonical_dseg': dseg,
            'values_sha256': matrix_values_hash(values), 'shape': [n, n], 'unit': 'km',
        }

    def flow(code):
        matches = None
        for raw, value in (live_matrices or {}).items():
            if dyn.core.norm_code(raw) == code:
                matches = value
                break
        if matches is None:
            raise SupplyContractError('V24916_DYNAMIC_SKIM_LIVE_DEMAND_MISSING:' + code)
        a = np.asarray(matches, dtype=np.float64)
        if a.shape != (n, n) or not np.isfinite(a).all() or float(np.min(a)) < -1.e-10:
            raise SupplyContractError('V24916_DYNAMIC_SKIM_LIVE_DEMAND_INVALID:' + code)
        return a

    family = {
        'WORK': dyn._weighted_pair(matrices['NATIVE_CW'], matrices['NATIVE_CW_NOT'],
                                   flow('NATIVE_CW'), flow('NATIVE_CW_NOT')),
        'SERVICE': dyn._weighted_pair(matrices['NATIVE_CS'], matrices['NATIVE_CS_NOT'],
                                      flow('NATIVE_CS'), flow('NATIVE_CS_NOT')),
        'LONG': np.array(matrices['NATIVE_CL'], copy=True),
        'FOREIGN': np.array(matrices['NATIVE_CF'], copy=True),
    }
    fhash = {k: matrix_values_hash(family[k]) for k in ('WORK', 'SERVICE')}
    fhash.update(LONG=meta['NATIVE_CL']['values_sha256'], FOREIGN=meta['NATIVE_CF']['values_sha256'])
    self.epoch += 1
    rm = getattr(self.adapter, 'readback_manager', None)
    assignment_epoch = int(getattr(rm, 'assignment_epoch', self.epoch) or self.epoch)
    payload = {
        'schema': dyn.SCHEMA, 'epoch': self.epoch, 'assignment_epoch': assignment_epoch,
        'assignment_token': str(assignment_token), 'zone_order_sha256': zhash,
        'operation_positions': [int(x) for x in operation_positions],
        'matrix_hashes': {d: meta[d]['values_sha256'] for d in dyn.REQUIRED_NATIVE_DSEGS},
        'family_hashes': fhash,
    }
    return dyn.DynamicSkimEpoch(
        schema=dyn.SCHEMA, epoch=self.epoch, assignment_epoch=assignment_epoch,
        assignment_token=str(assignment_token), zone_order_sha256=zhash,
        operation_positions=tuple(int(x) for x in operation_positions), matrices_by_dseg=matrices,
        matrix_meta_by_dseg=meta, family_distance=family, family_hashes=fhash, epoch_hash=dyn._hash(payload))


def prepare_grid(self, key, distance_matrix, edges, fine_x):
    scope = getattr(self, '_td_perf_grid_scope', None)
    grid_key = (id(distance_matrix), tuple(edges), tuple(fine_x))
    if scope is not None:
        if scope['epoch'] is not self.bridge.dynamic_skim_epoch:
            raise SupplyContractError('TD_PERF_METRIC_EPOCH_CHANGED')
        if grid_key in scope['grids']:
            return scope['grids'][grid_key]
    distance = np.asarray(distance_matrix, dtype=float)
    if distance.ndim != 2 or distance.shape[0] != distance.shape[1]:
        raise SupplyContractError('V24916_DYNAMIC_DISTANCE_NOT_SQUARE:' + key)
    n_zones = int(distance.shape[0])
    d = distance.ravel()
    idx = np.flatnonzero((d >= edges[0]) & (d <= edges[-1]))
    x = d[idx]
    coarse_bins = np.searchsorted(edges, x, side='right') - 1
    coarse_bins = np.minimum(coarse_bins, len(edges) - 2)
    fine_bins = np.searchsorted(fine_x, x, side='left')
    if len(fine_bins) and int(np.max(fine_bins)) >= len(fine_x):
        raise SupplyContractError('V24916_DYNAMIC_FINE_GRID_COVERAGE_FAIL:' + key)
    is_diag = idx // n_zones == idx % n_zones
    prepared = idx, x, coarse_bins, fine_bins, is_diag
    if scope is not None:
        scope['grids'][grid_key] = prepared
    return prepared


def wrap_evaluate(original):
    @functools.wraps(original)
    def evaluate(self, matrices):
        previous = getattr(self, '_td_perf_grid_scope', None)
        epoch = self.bridge.dynamic_skim_epoch
        scope = {'epoch': epoch, 'grids': {}}
        self._td_perf_grid_scope = scope
        try:
            result = original(self, matrices)
            if self.bridge.dynamic_skim_epoch is not epoch:
                raise SupplyContractError('TD_PERF_METRIC_EPOCH_CHANGED')
            self._td_perf_metrics_last = {'targets': len(result), 'grid_preparations': len(scope['grids'])}
            return result
        finally:
            self._td_perf_grid_scope = previous
    evaluate._td_perf_numpy = True
    return evaluate


def _evaluate_one(self, key, distance_matrix, matrices):
    ref = self.ref; np = ref.np; t = ref.TARGETS[key]
    fine = ref.FINE_AUTHORITY['targets'][key]
    fine_x = np.asarray(ref.FINE_AUTHORITY['common_grid_%s_km' % fine['grid']], dtype=float)
    goal = np.asarray(fine['cdf'], dtype=float)
    edges = np.asarray(t['edges'], dtype=float)
    idx, x, coarse_bins, fine_bins, is_diag = prepare_grid(self, key, distance_matrix, edges, fine_x)
    weights = np.zeros(len(idx), dtype=float)
    total = 0.0
    for no in t["matrix_nos"]:
        a = matrices[int(no)]
        weights += a.ravel()[idx]
        total += float(a.sum())
    mass = float(weights.sum())
    if not (mass > 0.0 and total > 0.0):
        raise SupplyContractError("V24916_DYNAMIC_NO_CONDITIONED_DEMAND:" + key)
    count = len(edges) - 1
    hist = np.bincount(coarse_bins, weights=weights, minlength=count)
    shares = hist / mass
    mean_exact = float(np.dot(weights, x) / mass)
    if str(t["mean_basis"]).startswith("BIN_MIDPOINT"):
        centres = (np.asarray(t["edges"][:-1]) + np.asarray(t["edges"][1:])) / 2
        mean = float(np.dot(shares, centres))
    else:
        mean = mean_exact
    q = np.asarray(t["shares"])
    diff = shares - q
    rel = (mean - t["mean_km"]) / t["mean_km"]
    model_cdf = np.cumsum(np.bincount(
        fine_bins, weights=weights, minlength=len(fine_x))) / mass
    cdf_diff = model_cdf - goal
    if abs(float(model_cdf[-1]) - 1.0) >= 1e-8:
        raise SupplyContractError("V24916_DYNAMIC_FINE_CDF_NOT_NORMALIZED:" + key)
    residual = np.r_[cdf_diff / math.sqrt(len(fine_x)),
                     math.sqrt(ref.CONFIG["shape_mean_weight"]) * rel]
    zero_mass = float(np.sum(weights[x == 0]) / mass)
    diag_zero_mass = float(np.sum(weights[(x == 0) & is_diag]) / mass)
    offdiag_zero_mass = zero_mass - diag_zero_mass
    return {
        "component": key, "shares": shares, "bin_volumes": hist,
        "fine_model_cdf": model_cdf,
        "fine_cdf_rmse": float(np.sqrt(np.mean(cdf_diff ** 2))),
        "fine_cdf_mae": float(np.mean(np.abs(cdf_diff))),
        "fine_cdf_ks": float(np.max(np.abs(cdf_diff))),
        "fine_cdf_mean_signed": float(np.mean(cdf_diff)),
        "fine_points_used": len(fine_x),
        "model_cdf_at_first_idp_node": float(model_cdf[0]),
        "target_cdf_at_first_idp_node": float(goal[0]),
        "zero_distance_share_diagnostic": zero_mass,
        "intrazonal_zero_distance_share_diagnostic": diag_zero_mass,
        "offdiagonal_zero_distance_share_diagnostic": offdiag_zero_mass,
        "zero_distance_structural_warning": int(
            zero_mass >= ref.CONFIG["structural_zero_distance_warning_threshold"]),
        "mean_model_km": mean,
        "mean_exact_distance_km_diagnostic": mean_exact,
        "mean_target_km": t["mean_km"], "mean_basis": t["mean_basis"],
        "mean_delta_km": mean - t["mean_km"],
        "mean_relative_error": rel,
        "l1_half": float(.5 * abs(diff).sum()),
        "rmse_share": float(np.sqrt(np.mean(diff ** 2))),
        "objective": float(residual @ residual), "residual": residual,
        "conditioned_volume_diagnostic": mass,
        "total_volume_diagnostic": total,
        "conditioned_share_diagnostic": mass / total,
    }


def install():
    cls = bridge.DynamicFamilyMetrics
    if not getattr(cls.evaluate, '_td_perf_numpy', False):
        cls._evaluate_one = functools.wraps(cls._evaluate_one)(_evaluate_one)
        cls.evaluate = wrap_evaluate(cls.evaluate)
    if not getattr(dyn.DynamicSkimManager._read_epoch, '_td_perf_numpy', False):
        read_epoch._td_perf_numpy = True
        dyn.DynamicSkimManager._read_epoch = functools.wraps(dyn.DynamicSkimManager._read_epoch)(read_epoch)
    return {'installed': True, 'release': RELEASE, 'skim_weight_dsegs': list(SKIM_WEIGHT_DSEGS),
            'grid_cache_lifetime': 'ONE_EVALUATE_CALL', 'hash_protocol_changed': False,
            'native_skim_count': len(dyn.REQUIRED_NATIVE_DSEGS)}
