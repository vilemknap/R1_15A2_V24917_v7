"""Build a binary LONG support mask from a Visum $V;D4 OSRM distance export.

Offline only. Writes new files, never opens Visum or overwrites the input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from r1_15a2_long_distance_guard_v24917 import MIN_KM
from r1_15a2_long_od_mask_v24917 import build_osrm_support_mask
from r1_15a2_skim_v24916p2c import matrix_values_hash, ordered_zone_hash


def read_d4(path):
    lines = Path(path).read_text(encoding='utf-8-sig').splitlines()
    if not lines or lines[0].strip() != '$V;D4':
        raise ValueError('LONG_MASK_UNSUPPORTED_MATRIX_FORMAT')
    def after(comment):
        return next(i + 1 for i, line in enumerate(lines) if line.strip() == comment)
    factor = float(lines[after('* Factor')])
    n = int(lines[after('* Number of network objects')])
    if n <= 0 or not np.isfinite(factor) or factor <= 0:
        raise ValueError('LONG_MASK_INVALID_MATRIX_HEADER')
    i = after('* Network object numbers')
    zones = []
    while len(zones) < n:
        zones.extend(int(token) for token in lines[i].split()); i += 1
    if len(zones) != n or len(set(zones)) != n or min(zones) <= 0:
        raise ValueError('LONG_MASK_INVALID_ZONE_AXIS')
    values = np.empty((n, n), dtype=np.float64)
    for row, zone in enumerate(zones):
        while i < len(lines) and (not lines[i].strip() or lines[i].strip() == '*'):
            i += 1
        match = re.match(r'^\*\s+Obj\s+(\d+)\s+Sum\s*=', lines[i])
        if match is None or int(match[1]) != zone:
            raise ValueError('LONG_MASK_MATRIX_ROW_ZONE_MISMATCH')
        i += 1
        column = 0
        while column < n:
            block = [float(token) for token in lines[i].split()]; i += 1
            if not block or column + len(block) > n:
                raise ValueError('LONG_MASK_MATRIX_ROW_LENGTH')
            values[row, column:column + len(block)] = block
            column += len(block)
    values *= factor
    if not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError('LONG_MASK_INVALID_DISTANCE_VALUES')
    return values, zones, lines[i:]


def write_d4(path, mask, zones, trailer):
    lines = ['$V;D4', '* From To', '- -', '* Factor', '1.00',
             '* LONG support: 1 iff R1_OSRM_DIST_KM M9697 >= %g km' % MIN_KM,
             '* Number of network objects', str(len(zones)), '* Network object numbers']
    for start in range(0, len(zones), 10):
        lines.append(' '.join(str(z) for z in zones[start:start+10]))
    lines.append('*')
    for zone, row in zip(zones, mask):
        lines.append('* Obj %d Sum = %d' % (zone, int(row.sum())))
        for start in range(0, len(zones), 10):
            lines.append(' '.join(str(int(v)) for v in row[start:start+10]))
    lines.extend(trailer)
    Path(path).write_bytes(('\ufeff' + '\r\n'.join(lines) + '\r\n').encode('utf-8'))


def build(input_path, output_dir):
    input_path, output_dir = Path(input_path), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / ('R1_LONG_OD_MASK_GE%g_KM.mtx' % MIN_KM)
    if output.resolve() == input_path.resolve():
        raise ValueError('LONG_MASK_INPUT_OVERWRITE_FORBIDDEN')
    distance, zones, trailer = read_d4(input_path)
    mask, report = build_osrm_support_mask(distance, zones,
        expected_values_sha256=matrix_values_hash(distance),
        expected_zone_order_sha256=ordered_zone_hash(zones))
    write_d4(output, mask, zones, trailer)
    restored, restored_zones, _ = read_d4(output)
    if restored_zones != zones or not np.array_equal(restored, mask.astype(np.float64)):
        raise ValueError('LONG_MASK_EXPORT_READBACK_MISMATCH')
    np.savez_compressed(output.with_suffix('.npz'), mask=mask.astype(np.uint8),
                        zone_nos=np.asarray(zones, dtype=np.int64), minimum_km=MIN_KM)
    report.update(input_file=input_path.name,
                  source_matrix_no=9697, output_matrix_no=None,
                  output_matrix_code=output.stem,
                  input_file_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
                  output_file=output.name, output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  rows=len(zones), columns=len(zones), one_is_allowed=True,
                  directed=True, symmetrized=False,
                  asymmetric_mask_cells=int(np.count_nonzero(mask != mask.T)),
                  exact_threshold_cells=int(np.count_nonzero(distance == MIN_KM)),
                  diagonal_allowed=int(np.count_nonzero(np.diag(mask))),
                  minimum_distance_km=float(distance.min()), maximum_distance_km=float(distance.max()),
                  export_readback_verified=True, live_visum_tested=False)
    output.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.output), indent=2))
