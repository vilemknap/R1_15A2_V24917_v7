# -*- coding: utf-8 -*-
"""Semantically tolerant DIAGFAST artifact parity (not source integrity parity)."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import zipfile
import r1_15a2_diagfast_v1 as df

TIMESTAMP_KEYS = frozenset(('timestamp','created_at','updated_at'))

# The embedded 11D helper auto-extracts its packaged IDP authority to a unique
# Windows temporary directory for each invocation. The suffix is a random
# tempfile nonce, not part of the source authority or the calibration result.
# Only the three KNOWN 11D provenance outputs may normalize it. All other
# paths, suffixes, numbers, source IDs and source content remain strict.
_11D_EPHEMERAL_PROVENANCE_FILES = frozenset((
    'r1_step11d_v1_3_component_dist_behavior_idp_authority_autorecovery.txt',
    'r1_step11d_v1_3_component_dist_behavior_recommendation.txt',
    'r1_step11d_v1_3_component_dist_behavior_summary.json',
))
_11D_TEMP_ID_RE = re.compile(
    r'(?i)([\\/]AppData[\\/]Local[\\/]Temp[\\/])R1A2_11DLIVEPAR_[a-z0-9_]{8}(?=[\\/])'
)

# This is a DIAGNOSTIC IMPLEMENTATION parity threshold, not a calibration
# acceptance threshold. 0.1% relative + 0.001 absolute of the source unit.
# Treat only tiny +/- and zero crosses as numerical noise, not genuine flow
# support changes. Counts, matrix/source identity, decisions and structure remain
# exact. No science outputs are rounded or changed.
DEFAULT_NUMERIC_ATOL = 1e-3
DEFAULT_NUMERIC_RTOL = 1e-3
DEFAULT_ZERO_CROSS_ATOL = 1e-6
MAX_SAME_SIGN_RELATIVE_DRIFT = 0.05  # prevents 100% drift of tiny nonzero counts
# SHA-256 is cryptographic: two hashes are never "approximately equal".
# A whitelist of DERIVED DIAGNOSTIC-REPORT digests can be ignored for parity
# only when the same artifact includes successfully verified numeric results.
# These names NEVER include source .ver, matrix, path epoch, checkpoint, cache,
# input or scientific authority digests. Actual release manifests stay exact.
_DERIVED_REPORT_DIGEST_FIELDS = frozenset((
    'output_sha256', 'output_hash', 'artifact_sha256', 'artifact_hash',
    'report_sha256', 'report_hash', 'normalized_sha256', 'result_sha256',
    'diagnostic_sha256', 'diagnostic_hash', 'summary_sha256',
))
_SHA256_RE = re.compile(r'(?i)^[a-f0-9]{64}$')
_CSV_FLOAT_RE = re.compile(r'^[+-]?(?:(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[0-9]+[eE][+-]?[0-9]+)$')
_EXACT_FIELD_NAMES = frozenset((
    'id', 'no', 'code', 'key', 'index', 'indices', 'order', 'ordinal',
    'year', 'rank', 'position', 'zone', 'zone_id', 'matrix_id', 'matrix_no',
    'link_id', 'link_no', 'countlocation_id', 'countlocation_no',
    'source', 'target', 'status', 'state', 'decision', 'accepted', 'valid',
    'bin_label', 'label', 'version', 'sha256', 'digest', 'fingerprint',
))
_EXACT_FIELD_SUFFIXES = ('_id', '_no', '_code', '_index', '_indices',
                         '_hash', '_sha256', '_fingerprint', '_checksum')


def _is_identity_field(field):
    if field is None:
        return False
    text = str(field).strip().lower()
    return text in _EXACT_FIELD_NAMES or text.endswith(_EXACT_FIELD_SUFFIXES)


def _close_numeric(a, b, atol, rtol):
    """Accept sub-threshold floating drift, including truly tiny zero crosses."""
    if not (math.isfinite(a) and math.isfinite(b)):
        return a == b  # unchanged +/- infinity only; NaN handled separately
    if a == b:
        return True
    delta = abs(a-b)
    scale = max(abs(a), abs(b))
    # A cross through exactly zero or across signs is allowed ONLY in a tiny
    # absolute noise band. Avoid a 0 versus 0.0009 artificial demand flow.
    if a == 0.0 or b == 0.0 or ((a < 0.0) != (b < 0.0)):
        return max(abs(a), abs(b)) <= DEFAULT_ZERO_CROSS_ATOL and \
            delta <= 2.0 * DEFAULT_ZERO_CROSS_ATOL
    return (delta <= max(atol, rtol*scale) and
            delta <= MAX_SAME_SIGN_RELATIVE_DRIFT * scale)


def _diagnostic_derived_digest(field, x, y):
    """A derivation of an output report, NOT a source/model/cache digest."""
    return (str(field).strip().lower() in _DERIVED_REPORT_DIGEST_FIELDS and
            isinstance(x, str) and isinstance(y, str) and
            _SHA256_RE.fullmatch(x) is not None and
            _SHA256_RE.fullmatch(y) is not None)


def _compare_numeric_value(a, b, field, fmt, atol, rtol):
    if _is_identity_field(field):
        return None
    if fmt == 'JSON' and type(a) is float and type(b) is float:
        if math.isnan(a) and math.isnan(b):
            return (True, 0.0, 0.0)
        return (_close_numeric(a, b, atol, rtol), abs(a - b),
                abs(a - b) / max(abs(a), abs(b), 1e-300))
    if fmt == 'CSV' and isinstance(a, str) and isinstance(b, str):
        if not (_CSV_FLOAT_RE.fullmatch(a) and _CSV_FLOAT_RE.fullmatch(b)):
            return None
        x, y = float(a), float(b)
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        return (_close_numeric(x, y, atol, rtol), abs(x-y),
                abs(x-y) / max(abs(x), abs(y), 1e-300))
    return None


def _bounded_diff(a, b, fmt, *, atol, rtol, limit=30):
    """Return exact-structure / bounded-float verdict plus auditable extrema.

    Any schema, type, array length, order, identifier, integer, NaN-status or
    binary change remains a hard failure. The comparator never mutates files.
    """
    stats = {'failed_values': 0, 'tolerated_values': 0,
             'max_tolerated_abs_difference': 0.0,
             'max_tolerated_relative_difference': 0.0,
             'tolerated_examples': [], 'differences': [],
             'tolerated_derived_digests': [], 'numeric_evidence_count': 0}
    pending_derived_digests = []

    def add_diff(x, y, path):
        stats['failed_values'] += 1
        if len(stats['differences']) < limit:
            diff = {'path': path, 'legacy': repr(x)[:300], 'fast': repr(y)[:300]}
            if type(x) in (int, float, str) and type(y) in (int, float, str):
                try:
                    lx, ly = float(x), float(y)
                    if math.isfinite(lx) and math.isfinite(ly):
                        diff['abs_difference'] = abs(lx-ly)
                        diff['relative_difference'] = abs(lx-ly)/max(abs(lx),abs(ly),1e-300)
                except (ValueError, TypeError, OverflowError):
                    pass
            stats['differences'].append(diff)

    def scalar(x, y, path, field=None):
        if type(x) is not type(y):
            add_diff(x, y, path)
            return
        if type(x) is float and math.isnan(x) and math.isnan(y):
            return
        # Evidence must be a REAL scientific numeric output in the SAME
        # artifact, not an ID, integer count, bare checksum or status.
        if not _is_identity_field(field) and (
                type(x) is float and math.isfinite(x) and math.isfinite(y) or
                fmt == 'CSV' and isinstance(x, str) and isinstance(y, str)
                and _CSV_FLOAT_RE.fullmatch(x) is not None
                and _CSV_FLOAT_RE.fullmatch(y) is not None):
            stats['numeric_evidence_count'] += 1
        if x == y:
            return
        if _diagnostic_derived_digest(field, x, y):
            pending_derived_digests.append((x, y, path))
            return
        compared = _compare_numeric_value(x, y, field, fmt, atol, rtol)
        if compared is None or not compared[0]:
            add_diff(x, y, path)
            return
        _, delta, relative = compared
        stats['tolerated_values'] += 1
        stats['max_tolerated_abs_difference'] = max(
            stats['max_tolerated_abs_difference'], delta)
        stats['max_tolerated_relative_difference'] = max(
            stats['max_tolerated_relative_difference'], relative)
        if len(stats['tolerated_examples']) < 10:
            stats['tolerated_examples'].append({
                'path': path, 'legacy': repr(x)[:100], 'fast': repr(y)[:100],
                'abs_difference': delta, 'relative_difference': relative,
            })

    def json_walk(x, y, path='$', field=None):
        if type(x) is not type(y):
            add_diff(x, y, path)
        elif isinstance(x, dict):
            if set(x) != set(y):
                add_diff(sorted(x), sorted(y), path + '.keys')
            for k in sorted(set(x) & set(y)):
                json_walk(x[k], y[k], path + '.' + str(k), field=k)
        elif isinstance(x, list):
            if len(x) != len(y):
                add_diff(len(x), len(y), path + '.length')
            for i, (xx, yy) in enumerate(zip(x, y)):
                json_walk(xx, yy, '%s[%d]' % (path, i), field=field)
        else:
            scalar(x, y, path, field)

    if fmt == 'JSON':
        json_walk(a, b)
    elif fmt == 'CSV':
        if not isinstance(a, list) or not isinstance(b, list):
            add_diff(type(a), type(b), '$.schema')
        else:
            if len(a) != len(b):
                add_diff(len(a), len(b), '$.row_count')
            ha = a[0] if a else []
            hb = b[0] if b else []
            if ha != hb:
                add_diff(ha, hb, '$.header')
            for i, (ra, rb) in enumerate(zip(a[1:], b[1:]), 1):
                if len(ra) != len(rb):
                    add_diff(len(ra), len(rb), '$.rows[%d].length' % i)
                for j, (x, y) in enumerate(zip(ra, rb)):
                    field = ha[j] if j < len(ha) and ha == hb else None
                    scalar(x, y, '$.rows[%d][%d]' % (i,j), field)
    else:
        if a != b:
            add_diff(a, b, '$')
    # A derived JSON/CSV report SHA may differ due formatting/numeric drift.
    # Do not relax a hash-only artifact, or a report with no numeric evidence:
    # we would have no scientific payload to independently compare.
    for x, y, path in pending_derived_digests:
        if stats['numeric_evidence_count'] > 0:
            stats['tolerated_derived_digests'].append({
                'path': path, 'legacy_sha256': x, 'fast_sha256': y,
                'reason': 'DERIVED_DIAGNOSTIC_DIGEST__NUMERIC_PAYLOAD_VALIDATED',
            })
        else:
            add_diff(x, y, path)
    return stats


def _normalize_11d_temp_authority(value, name):
    """Remove *only* the 8-char Python tempfile nonce in 3 known 11D reports.

    Python tempfile nonces use a-z, 0-9 AND underscore. An initial
    underscore creates a double-underscore prefix after LIVEPAR_.
    Anchor to AppData/Local/Temp and preserve the entire enclosing absolute
    path plus the relative authority/output filename. A changed source root,
    filename, IDP value or any numerical result must still fail parity.
    """
    basename=name.rsplit('!/', 1)[-1].replace('\\', '/').rsplit('/', 1)[-1]
    if basename not in _11D_EPHEMERAL_PROVENANCE_FILES:
        return value
    if isinstance(value, str):
        return _11D_TEMP_ID_RE.sub(
            lambda m: m.group(1)+'R1A2_11DLIVEPAR_<EPHEMERAL_NONCE>', value)
    if isinstance(value, dict):
        return {k: _normalize_11d_temp_authority(v, name) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_11d_temp_authority(v, name) for v in value]
    return value


def _normalize_text(text, root):
    roots = root if isinstance(root, (tuple, list)) else [root]
    for item in sorted(map(str, roots), key=len, reverse=True):
        text=text.replace(item,'<WORKSPACE>').replace(item.replace('\\','/'),'<WORKSPACE>')
    text=re.sub(r'R1_12D_\d{8}_\d{6}', 'R1_12D_<STAMP>',text)
    # Only timestamp prefixes in the legacy 12D log, not arbitrary numbers.
    text=re.sub(r'(?m)^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]', '[<TIMESTAMP>]',text)
    return text


def _normalize_json(value, root):
    if isinstance(value,dict):
        return {k:('<TIMESTAMP>' if k in TIMESTAMP_KEYS else _normalize_json(v,root)) for k,v in value.items()}
    if isinstance(value,list): return [_normalize_json(v,root) for v in value]
    if isinstance(value,str): return _normalize_text(value,root)
    return value


def _canonical(name, raw, root):
    suffix=Path(name).suffix.lower()
    if suffix=='.json':
        value=_normalize_json(json.loads(raw.decode('utf-8-sig')),root)
        value=_normalize_11d_temp_authority(value,name)
        data=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=True).encode('utf-8')
        return data, {'format':'JSON'}, value
    if suffix=='.csv':
        text=raw.decode('utf-8-sig')
        head=text.splitlines()[0] if text else ''
        delimiter=';' if head.count(';')>head.count(',') else ','
        rows=list(csv.reader(io.StringIO(text),delimiter=delimiter))
        rows=[[_normalize_text(cell,root) for cell in row] for row in rows]
        if name.endswith('00_EXECUTIVE_SUMMARY.csv'):
            rows=[([row[0],'<TIMESTAMP>'] if len(row)==2 and row[0]=='timestamp' else row) for row in rows]
        data=json.dumps(rows,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        return data, {'format':'CSV','columns':rows[0] if rows else [],'data_rows':max(0,len(rows)-1)}, rows
    try:
        text=_normalize_text(raw.decode('utf-8-sig'),root)
        text=_normalize_11d_temp_authority(text,name)
        # Diagnostic TEXT formatting is not scientific identity. Canonicalize
        # CRLF/LF and end-of-line spaces before hashing; preserve EVERY letter,
        # digit, sign, number, internal space and scientific/provenance token.
        # This affects output artifact parity only, never source manifests.
        text='\n'.join(line.rstrip(' \t') for line in
                       text.replace('\r\n','\n').replace('\r','\n').split('\n'))
        text=text.rstrip('\n') + ('\n' if text else '')
        if name.endswith('20_STAGE_LOG.txt'):
            text=re.sub(r'(?m)^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2}', '<TIMESTAMP>', text)
        return text.encode('utf-8'), {'format':'TEXT'}, text
    except UnicodeError:
        return raw, {'format':'BINARY'}, None


def artifact_map(root):
    """Include every legacy artifact, recursively including ZIP payloads.

    New DIAGFAST instrumentation and .py sources are reported separately, not
    confused with legacy outputs. Source bytes are checked by release manifests.
    """
    root=Path(root)
    roots=[str(root)]
    for profile in root.rglob('DIAGFAST_*_PROFILE*.json'):
        data=json.loads(profile.read_text('utf-8'))
        workspace=data.get('notes',{}).get('workspace_path')
        if workspace: roots.append(workspace)
    out={}
    def add(name,raw):
        parts=Path(name).parts
        if any(p.startswith('DIAGFAST_') for p in parts) or name.endswith(('.py','.pyc')):
            return
        name=_normalize_text(name,roots)
        if name.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if z.testzip() is not None: raise df.DiagFastError('PARITY_BAD_ZIP:'+name)
                for info in sorted(z.infolist(),key=lambda x:x.filename):
                    if not info.is_dir(): add(name+'!/'+info.filename,z.read(info))
            return
        if name in out: raise df.DiagFastError('PARITY_DUPLICATE_ARTIFACT_KEY:'+name)
        data,meta,value=_canonical(name,raw,roots)
        out[name]={'sha256':hashlib.sha256(data).hexdigest(),'canonical_bytes':len(data),
                   'metadata':meta,'value':value}
    for p in sorted(root.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            add(p.relative_to(root).as_posix(),p.read_bytes())
    return out


def _diff_values(a,b,path='',limit=30):
    diffs=[]
    def add(x,y,p):
        if len(diffs)>=limit:return
        d={'path':p,'legacy':repr(x)[:300],'fast':repr(y)[:300]}
        try:
            fx,fy=float(x),float(y)
            if math.isfinite(fx) and math.isfinite(fy):
                d['abs_difference']=abs(fx-fy)
                d['relative_difference']=abs(fx-fy)/max(abs(fx),abs(fy),1e-300)
        except (TypeError,ValueError): pass
        diffs.append(d)
    def walk(x,y,p):
        if len(diffs)>=limit:return
        if isinstance(x,dict) and isinstance(y,dict):
            if set(x)!=set(y):add(sorted(x),sorted(y),p+'.keys')
            for k in sorted(set(x)&set(y)):walk(x[k],y[k],p+'.'+str(k))
        elif isinstance(x,list) and isinstance(y,list):
            if len(x)!=len(y):add(len(x),len(y),p+'.length')
            for i,(xx,yy) in enumerate(zip(x,y)):walk(xx,yy,p+'[%d]'%i)
        elif type(x)!=type(y) or x!=y:
            if isinstance(x,float) and isinstance(y,float) and math.isnan(x) and math.isnan(y):return
            add(x,y,p)
    walk(a,b,path)
    return diffs


def compare_artifacts(legacy, fast, scope='PARITY_EXECUTION', *,
                      numeric_tolerance=True,
                      numeric_atol=DEFAULT_NUMERIC_ATOL,
                      numeric_rtol=DEFAULT_NUMERIC_RTOL):
    """Compare every diagnostic output under explicit semantic tolerances.

    Canonical SHA-256 can differ when numeric content is semantically equal.
    Selected derived output digests can also differ, but only with numeric
    evidence in that same report. Source/model/checkpoint/cache/manifests
    remain byte-exact; disable numeric_tolerance for forensic comparisons.
    """
    if (type(numeric_tolerance) is not bool or
            not math.isfinite(numeric_atol) or not math.isfinite(numeric_rtol) or
            numeric_atol < 0 or numeric_rtol < 0):
        raise df.DiagFastError('DIAGFAST_PARITY_INVALID_NUMERIC_TOLERANCE')
    a, b = artifact_map(legacy), artifact_map(fast)
    entries, failures = [], []
    tolerated_artifacts = tolerated_values = tolerated_digests = 0
    max_abs = max_rel = 0.0
    for name in sorted(set(a) | set(b)):
        aa, bb = a.get(name), b.get(name)
        byte_equal = aa is not None and bb is not None and aa['sha256'] == bb['sha256']
        same = byte_equal
        record = None
        if (not same and numeric_tolerance and aa is not None and bb is not None and
                aa['metadata'] == bb['metadata'] and
                aa['metadata']['format'] in ('JSON', 'CSV')):
            record = _bounded_diff(aa['value'], bb['value'], aa['metadata']['format'],
                                   atol=numeric_atol, rtol=numeric_rtol)
            same = not record['failed_values']
        entry = {
            'artifact': name, 'equal': same, 'byte_equal': byte_equal,
            'canonical_sha_equal': byte_equal,
            'semantic_match_despite_sha_mismatch': bool(same and not byte_equal),
            'legacy_sha256': aa['sha256'] if aa else None,
            'fast_sha256': bb['sha256'] if bb else None,
            'legacy_schema': aa['metadata'] if aa else None,
            'fast_schema': bb['metadata'] if bb else None,
            'numeric_tolerance_accepted': bool(same and not byte_equal),
            'tolerated_values': record['tolerated_values'] if record else 0,
            'tolerated_derived_digest_count': (len(record['tolerated_derived_digests'])
                                               if record else 0),
            'max_tolerated_abs_difference': record['max_tolerated_abs_difference'] if record else 0.0,
            'max_tolerated_relative_difference': record['max_tolerated_relative_difference'] if record else 0.0,
        }
        if record and record['tolerated_examples']:
            entry['tolerated_examples'] = record['tolerated_examples']
        if record and record['tolerated_derived_digests']:
            entry['tolerated_derived_digests'] = record['tolerated_derived_digests'][:10]
        if not same:
            entry['differences'] = (record['differences'] if record is not None else
                                    _diff_values(aa['value'] if aa else None,
                                                 bb['value'] if bb else None))
            failures.append(name)
        elif not byte_equal:
            tolerated_artifacts += 1
            tolerated_values += record['tolerated_values']
            tolerated_digests += len(record['tolerated_derived_digests'])
            max_abs = max(max_abs, record['max_tolerated_abs_difference'])
            max_rel = max(max_rel, record['max_tolerated_relative_difference'])
        entries.append(entry)
    return {
        'schema': 'R1_DIAGFAST_PARITY_REPORT_V3',
        'status': 'PARITY_PASS' if entries and not failures else 'PARITY_FAILED',
        'scope': scope,
        'artifact_count': len(entries),
        'equal_artifacts': sum(x['equal'] for x in entries),
        'byte_equal_artifacts': sum(x['byte_equal'] for x in entries),
        'canonical_sha_equal_artifacts': sum(x['byte_equal'] for x in entries),
        'tolerated_artifacts': tolerated_artifacts,
        'tolerated_value_count': tolerated_values,
        'tolerated_derived_digest_count': tolerated_digests,
        'max_tolerated_abs_difference': max_abs,
        'max_tolerated_relative_difference': max_rel,
        'failures': failures,
        'artifacts': entries,
        'exact_values_required': not numeric_tolerance,
        'numeric_tolerance_used': numeric_tolerance,
        'numeric_rounding_used': False,
        'numeric_tolerance': {
            'absolute': numeric_atol, 'relative': numeric_rtol,
            'zero_cross_noise_floor': DEFAULT_ZERO_CROSS_ATOL,
            'max_same_sign_relative_drift': MAX_SAME_SIGN_RELATIVE_DRIFT,
            'formula': 'abs(x-y) <= max(absolute, relative*max(abs(x),abs(y))); zero/sign crossing requires both values <= zero_cross_noise_floor',
            'zero_sign_noise_only': True,
            'identity_fields_exact': True,
            'applies_only_to': 'finite float JSON or decimal/exponent CSV cells',
            'derived_diagnostic_digest_exception': sorted(_DERIVED_REPORT_DIGEST_FIELDS),
            'source_model_and_cache_digests_exact': True,
        },
        'normalizations': [
            'exact workspace prefix',
            'R1_12D_YYYYMMDD_HHMMSS directory names',
            'JSON timestamp/created_at/updated_at fields',
            '12D executive timestamp row',
            '12D log timestamp prefixes',
            'ZIP entry container metadata only; payloads compared recursively',
            'TEXT CRLF/LF/trailing horizontal whitespace/terminal newline normalization',
            '11D authority autorecovery 8-character Python tempfile nonce [a-z0-9_] ONLY in 3 known provenance outputs under Windows AppData/Local/Temp; enclosing paths preserved',
        ],
        'new_instrumentation_excluded': 'DIAGFAST_* files only; separately retained and audited',
        'source_files_excluded': '*.py/*.pyc are verified by SHA manifests, not value artifacts',
    }


def _read_full_td_abc_guard(guarded):
    """Independent read-only 17-parameter seal for the approved 16/17 09C.

    4_FOREIGN is frozen even when absent from the native DSTRATSET. Unlike
    legacy vp._dstrat_object this uses the exact callable getter already
    certified by the V242 bridge and its read-only 09C preflight. It never
    changes operation flags, parameter values or COM state.
    """
    import r1_15a2_td09c_16or17_hotfix_v24916 as td09c
    import r1_15a2_runtime_v1 as rt
    import r1_15a2_multiblock as mb
    import r1_15a2_visum_parameters as vp
    import r1_15a2_finecdf_bridge_v242 as bridge

    preflight=td09c.read_only_source_preflight(guarded)
    ops=rt.get_all(guarded.Procedures.Operations)
    op=ops[preflight['selected_operation_index']-1]
    para=op.TripDistributionParameters
    codes=[r['dstrat_code'] for r in mb.COMPONENT_REGISTRY.values()]
    if len(codes)!=16 or set(codes)!=set(td09c.APPROVED_NATIVE_CODES):
        raise df.DiagFastError('DIAGFAST_09C_NATIVE_COMPONENT_REGISTRY_CHANGED')
    if '4_FOREIGN' in codes:
        raise df.DiagFastError('DIAGFAST_09C_FOREIGN_DUPLICATE')
    rows=[]
    for code in codes+['4_FOREIGN']:
        try:
            g=para.TripDistributionDStratParameters(code).GravitationParameters
            params={
                'a':bridge.NoDirectMatrixWriteTDAdapter._read_attr(g,bridge.NoDirectMatrixWriteTDAdapter.A_ATTRS),
                'b':bridge.NoDirectMatrixWriteTDAdapter._read_attr(g,vp.TD_B_ATTRS),
                'c':bridge.NoDirectMatrixWriteTDAdapter._read_attr(g,vp.TD_C_ATTRS),
            }
        except Exception as exc:
            raise df.DiagFastError('DIAGFAST_09C_ABC_READ_FAILED:%s:%r'%(code,exc)) from exc
        rows.append({'code':code, **params})
    return {'td_full_abc_hash':hashlib.sha256(json.dumps(
                rows,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest(),
            'td_source_scope':preflight['scope'],
            'td_foreign_abc_hash':hashlib.sha256(json.dumps(
                rows[-1],sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()}


def capture_state(visum,cfg):
    """Read-only guard for the parity path, not calibration's cached snapshot."""
    from r1_15a2_supply_visum import VisumAdapter
    prof=df.Profile('STATE_SEAL','LEGACY')
    guarded=df.ReadOnlyProxy(visum,prof,cfg.get('com_resilience',{}))
    adapter=VisumAdapter(guarded,cfg)
    try:
        snap=adapter.snapshot()
    except Exception as exc:
        if str(exc) != 'COMPONENT_PARAMETER_SNAPSHOT_FAILED':
            raise
        # Preserve the primary failure, but expose exact bad component codes
        # instead of the historical non-actionable blanket error.
        try:
            from r1_15a2_visum_parameters import read_td_parameter_state
            rows=read_td_parameter_state(guarded)['rows']
            invalid=[{'component':r.get('component'),
                      'dstrat_code':r.get('dstrat_code'),
                      'status':r.get('status')} for r in rows
                     if r.get('status')!='OK']
            detail=';'.join('%s/%s:%s'%(r['component'],r['dstrat_code'],r['status'])
                            for r in invalid)
            if not invalid: detail='COUNT_MISMATCH:%d'%len(rows)
        except Exception as diagnostic_exc:
            detail='DIAGNOSTIC_READ_FAILED:%r'%diagnostic_exc
        raise df.DiagFastError('DIAGFAST_TD_COMPONENT_READBACK_FAILED:'+detail) from exc
    hashes={k:v for k,v in snap.items() if k.endswith('_hash')}
    # Snapshot's 16 mutable b/c parameters do not cover frozen FOREIGN ABC.
    # Extend the seal with all 17 a/b/c readbacks without modifying the
    # protected snapshot function or the science/acceptance algorithm.
    hashes.update(_read_full_td_abc_guard(guarded))
    # Include classification values not necessarily covered by demand snapshots.
    env=df.reference_namespace('11D',Path(tempfile.gettempdir()),guarded,lambda *a,**k:None)
    dist=env['find_matrix_by_code'](guarded,env['OSRM_MATRIX_CODE'])
    time_mat,_=env['find_time_matrix'](guarded)
    mats=[];seen=set()
    for mat in (dist,time_mat):
        if mat is None:continue
        no=df.exact_id(mat.AttValue('NO'))
        if no in seen:continue
        seen.add(no)
        vals,_=env['read_matrix_values'](mat)
        raw=json.dumps(vals,ensure_ascii=True,separators=(',',':'),allow_nan=True).encode('ascii')
        mats.append((no,hashlib.sha256(raw).hexdigest()))
    hashes['classification_hash']=hashlib.sha256(json.dumps(mats).encode()).hexdigest()
    hashes['source_version_path']=str(guarded.IO.CurrentVersionFile)
    source=Path(hashes['source_version_path'])
    hashes['source_ver_sha256']=df.digest_file(source) if source.is_file() else None
    return hashes


def parity_helper(kind, workspace, visum, policy=None, print_fn=print):
    workspace=Path(workspace);ctx=df.CONTEXT.get() or {}
    cfg=ctx.get('cfg')
    seal=ctx.get('seal')
    if seal is None:
        if not cfg:raise df.DiagFastError('PARITY_STATE_SEAL_CONFIG_REQUIRED')
        seal=lambda: capture_state(visum,cfg)
    legacy=Path(tempfile.mkdtemp(prefix='r1dfL_'))
    try:
        for p in workspace.glob('*.csv'): shutil.copy2(p,legacy/p.name)
        before=seal()
        df.run_reference_helper(kind,legacy,visum,'LEGACY',policy,print_fn)
        middle=seal()
        df.run_reference_helper(kind,workspace,visum,'FAST_EXACT',policy,print_fn)
        after=seal()
        report=compare_artifacts(legacy,workspace,scope=ctx.get('parity_scope','LIVE_HELPER_AUDIT'))
        report['state_unchanged']=before==middle==after
        report['state_seals']={'before':before,'between':middle,'after':after}
        if not report['state_unchanged']:
            report['status']='PARITY_FAILED';report['failures'].append('LIVE_STATE_CHANGED_BETWEEN_HELPERS')
        with zipfile.ZipFile(workspace/('DIAGFAST_'+kind+'_LEGACY_REFERENCE.zip'),'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(legacy.rglob('*')):
                if p.is_file():z.write(p,p.relative_to(legacy).as_posix())
        (workspace/('DIAGFAST_'+kind+'_PARITY.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        if report['status']!='PARITY_PASS':
            raise df.DiagFastError('DIAGFAST_PARITY_FAILED:'+','.join(report['failures'][:10]))
        return report
    finally:
        shutil.rmtree(legacy,ignore_errors=True)
