"""Read-only daily export of the user's currently opened calibrated 2022 model.

No import/recompute receipt is available for the original calibrated version.
Matrix consistency is checked here; assignment freshness is not certified.
"""
from datetime import datetime
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import uuid

import numpy as np


def current_2022_path(visum, api):
    path = str(visum.IO.CurrentVersionFile or '').strip()
    if not path or PureWindowsPath(path).suffix.casefold() != '.ver':
        raise api['ScenarioError']('OPEN_SAVED_CALIBRATED_2022_VERSION_FIRST')
    # Accepted checkpoint filenames need not contain a year. Explicit scenario
    # filenames are rejected so a forecast cannot casually be labelled 2022.
    stem = PureWindowsPath(path).stem
    if any(re.search(r'(?<!\d)' + str(year) + r'(?!\d)', stem) for year in api['YEARS']):
        raise api['ScenarioError']('FORECAST_MODEL_CANNOT_BE_EXPORTED_AS_2022')
    return path


def round_freight_half_up(values, error):
    """Round nonnegative floating-point counts without truncation or ties-to-even."""
    if not np.isfinite(values).all() or np.any(values < 0) or np.any(values >= 2**53):
        raise error('INVALID_FREIGHT_VALUES_FOR_INTEGER_EXPORT')
    whole = np.floor(values)
    return whole + ((values - whole) >= 0.5)


def run_export_2022(visum, folder, api):
    folder = Path(folder)
    error = api['ScenarioError']
    version = current_2022_path(visum, api)
    order, _ = api['zone_order'](visum)
    cfg = {'passenger_dsegs': api['PASSENGER_DSEGS']}
    codes = list(cfg['passenger_dsegs']) + ['LNV', 'NV']
    matrix_nos = {code: api['integer'](api['resolve_matrix'](visum, code).AttValue('NO'), code) for code in codes}
    if len(set(matrix_nos.values())) != len(codes):
        raise error('EXPORT_2022_MATRIX_SCOPE_OVERLAP')
    if matrix_nos['NATIVE_CL'] != 9305:
        raise error('EXPORT_2022_NATIVE_CL_MUST_USE_9305')
    before, oa, freight = api['fingerprint'](visum, cfg, order)
    rounded = {code: round_freight_half_up(arr, error) for code, arr in freight.items()}
    staging = folder / ('EXPORT_STAGING_' + uuid.uuid4().hex)
    staging.mkdir()
    try:
        outputs = []
        for label, arr in [('OA_CAL_WORK', oa), ('LNV', rounded['LNV']), ('NV', rounded['NV'])]:
            path = staging / ('R1_2022_' + label + '.mtx')
            text_stats = api['write_matrix'](path, arr, order, 2022, label)
            record = {'label': label, 'file': path.name, 'sha256': api['digest'](path.read_bytes()),
                      'unit': 'vehicles/day', 'sum_before_text_format': float(arr.sum()),
                      'diagonal': float(np.trace(arr)), 'nonzero_od': int(np.count_nonzero(arr)),
                      'freight_integer_values': label in rounded, **text_stats}
            if label in rounded:
                delta = arr - freight[label]
                record.update(rounding='CELLWISE_HALF_UP_NO_RENORMALIZATION',
                              source_sum_before_rounding=float(freight[label].sum()),
                              rounding_sum_delta=float(delta.sum()),
                              maximum_cell_rounding_delta=float(np.max(np.abs(delta))))
            outputs.append(record)
        # A changed model must not publish a mixed snapshot. This second read
        # includes the passenger/freight inputs, OSRM and masked LONG matrices.
        after_order, _ = api['zone_order'](visum)
        if current_2022_path(visum, api) != version or after_order != order:
            raise error('MODEL_OR_ZONE_ORDER_CHANGED_DURING_EXPORT_2022')
        after, _, _ = api['fingerprint'](visum, cfg, after_order)
        if after != before:
            raise error('MODEL_MATRICES_CHANGED_DURING_EXPORT_2022')
        result = {'status': 'PASS_EXPORTED', 'year': 2022, 'model_path': version,
                  'year_basis': 'USER_SELECTED_OPEN_CALIBRATED_2022_MODEL',
                  'assignment_freshness': 'NOT_VERIFIED_BY_EXPORTER',
                  'fingerprint': before, 'source_matrix_nos': matrix_nos, 'outputs': outputs,
                  'OA_source': 'SUM_OF_12_DISTINCT_COMPONENT_DSEG_MATRICES',
                  'model_writes': False, 'version_saved': False, 'recomputed': False,
                  'period_conversion': 'NOT_APPLIED_DAILY_MATRICES'}
        api['write_json'](staging / 'EXPORT_MANIFEST.json', result)
        target = folder / ('EXPORT_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        if target.exists():
            raise error('EXPORT_TARGET_ALREADY_EXISTS')
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print('PASS_EXPORT', 2022, target)
    return result
