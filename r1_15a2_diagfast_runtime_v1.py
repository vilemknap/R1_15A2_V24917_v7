# -*- coding: utf-8 -*-
"""Additive runtime routing. Installed explicitly by the DIAGFAST launcher only."""
from __future__ import annotations
import copy
import functools
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

import r1_15a2_diagfast_v1 as df

_ACTIVE = False


def activate(launcher, backend='FAST_EXACT'):
    global _ACTIVE
    if _ACTIVE:
        raise df.DiagFastError('DIAGFAST_ALREADY_ACTIVATED')
    backend = df.mode(backend)
    integrity = df.verify_integrity()
    rt = launcher.rt
    original_helper = rt.run_helper
    original_archive = rt._archive_helper_workspace

    def helper(script, visum, stage, workspace, stage_log, retry_policy=None):
        ctx = df.CONTEXT.get()
        kind = next((k for k,n in df.HELPERS.items() if Path(script).name==n),None)
        if not ctx or not kind:
            return original_helper(script,visum,stage,workspace,stage_log,retry_policy)
        wrapper = df.ROOT/'helpers'/('R1_'+kind+'_DIAGFAST_V1.py')
        token = df.CONTEXT.set(dict(ctx,helper=kind,stage=stage))
        try:
            return original_helper(wrapper,visum,stage,workspace,stage_log,retry_policy)
        finally:
            # Keep evidence, but always release context even when copying fails.
            had_error = sys.exc_info()[0] is not None
            try:
                for path in Path(workspace).glob('DIAGFAST_*_*.json'):
                    target = Path(stage_log).parent/(path.stem+'_'+uuid.uuid4().hex[:8]+'.json')
                    try:
                        shutil.copy2(path,target)
                    except Exception as exc:
                        if ctx['backend']=='PARITY_AUDIT' and not had_error:
                            raise df.DiagFastError('DIAGFAST_PARITY_EVIDENCE_NOT_DURABLE:'+str(exc)) from exc
                        print('DIAGFAST_EVIDENCE_IO_WARNING:',repr(exc))
            finally:
                df.CONTEXT.reset(token)

    def archive(workspace, zip_path):
        start=time.perf_counter()
        try:
            return original_archive(workspace,zip_path)
        finally:
            ctx=df.CONTEXT.get()
            if ctx:
                p=Path(zip_path)
                report={'schema':'R1_DIAGFAST_ARCHIVE_PROFILE_V1',
                        'name':'DIAG_EVIDENCE_ARCHIVE','backend':ctx['backend'],
                        'inclusive_seconds':time.perf_counter()-start,
                        'archive':str(p),'bytes':p.stat().st_size if p.is_file() else None,
                        'note':'Archive span, separate from helper internal archive. Do not sum nested spans.'}
                dest=p.parent/('DIAGFAST_ARCHIVE_'+uuid.uuid4().hex[:8]+'.json')
                try:
                    dest.write_text(json.dumps(report,indent=2),encoding='utf-8')
                except Exception as exc:
                    print('DIAGFAST_ARCHIVE_TELEMETRY_IO_WARNING:',repr(exc))

    def routed(original,kind):
        @functools.wraps(original)
        def run(visum,out_dir,label,*args,**kwargs):
            if kind=='12D':
                cfg = kwargs.get('cfg', args[0] if args else {})
            else:
                cfg = kwargs.get('cfg', args[1] if len(args)>1 else {}) or {}
            chosen=df.mode(cfg.get('diagnostics_backend','LEGACY'))
            token=df.CONTEXT.set({'backend':chosen,'policy':cfg.get('com_resilience',{}),'cfg':cfg})
            before=time.perf_counter()
            try:
                result=original(visum,out_dir,label,*args,**kwargs)
                result['diagfast_execution']={'release':df.RELEASE,'backend':chosen,
                    'original_helper_unchanged_on_disk':True,
                    'value_read_overlay_active':chosen!='LEGACY',
                    'scope':'ONE_HELPER_INVOCATION',
                    'wall_seconds_with_io_and_gate':time.perf_counter()-before}
                # The old gate field describes sealed source bytes. Clarify its
                # meaning without changing the gate decision or any legacy field.
                if kind=='11D':
                    result['diagfast_execution']['legacy_gate_original_helper_unchanged_scope']='ON_DISK_SOURCE_ONLY_NOT_EXECUTION_PATH'
                return result
            finally:
                df.CONTEXT.reset(token)
        return run

    rt.run_helper=helper
    rt._archive_helper_workspace=archive
    rt.run_12d=routed(rt.run_12d,'12D')
    rt.run_11d=routed(rt.run_11d,'11D')
    original_prepare=launcher.prepare_runtime_config
    @functools.wraps(original_prepare)
    def prepare(*args,**kwargs):
        result=original_prepare(*args,**kwargs)
        cfg=result[0]
        science_before=copy.deepcopy({k:v for k,v in cfg.items() if k not in
                         ('implementation_files','implementation_hash','aggressive_tuning')})
        cfg['diagnostics_backend']=backend
        certificate = getattr(launcher, '_diagfast_live_certificate', {})
        cfg['diagfast']={'release':df.RELEASE,
            'live_status':certificate.get('status','LIVE_PENDING_UNTIL_CERTIFICATE'),
            'live_certificate_scope':certificate.get('scope'),
            'live_report_folder':certificate.get('report_folder'),
            'numeric_backend':('ORIGINAL_SCALAR_ACCUMULATION' if backend=='LEGACY' else
                               'V2_NUMPY_SEQUENTIAL_CUMSUM_BITWISE_EXACT_REFERENCE_FALLBACK'),
            'matrix_cache_lifetime':'ONE_HELPER_INVOCATION',
            'sparse_link_scope':'APPROVED_PHYSICAL_DIRECTIONS_PLUS_ORIGINAL_FIRST_SAMPLE',
            'unselected_required_volume_validation':'12_BULK_NETWORK_SWEEPS_OR_LEGACY_FULL_FALLBACK',
            'v2_read_backend':('NONE' if backend=='LEGACY' else
                               'PROBE_VERIFIED_BULK_COLUMNS_ONE_HELPER_INVOCATION_V1_FALLBACK'),
            'all_original_sources_unchanged':True,'base_archive_sha256':integrity['parent_archive_sha256'],
            'legacy_original_helper_unchanged_metadata_scope':'ON_DISK_ONLY',
            'source_identity':df.digest_file(df.ROOT/'DIAGFAST_V1_RELEASE_MANIFEST.json')}
        own=json.loads((df.ROOT/'DIAGFAST_V1_RELEASE_MANIFEST.json').read_text('utf-8'))
        for name in own['files']:
            if name.endswith('.py') or name.endswith('MANIFEST.json'):
                cfg['implementation_files'][name]=df.digest_file(df.ROOT/name)
        cfg['implementation_hash']=launcher.canonical_hash(cfg['implementation_files'])
        cfg['aggressive_tuning']['diagfast_overlay']=dict(cfg['diagfast'],backend=backend,
              pre_overlay_science_hash=launcher.canonical_hash(science_before))
        non_science=frozenset(('config_path','config_sha256','implementation_hash',
            'tg_dependency_contract_path','tg_dependency_contract_sha256',
            'long_authority_path','long_authority_sha256','aggressive_tuning'))
        cfg['aggressive_tuning']['effective_science_hash']=launcher.canonical_hash(
            {k:v for k,v in cfg.items() if k not in non_science})
        return result
    launcher.prepare_runtime_config=prepare
    _ACTIVE=True
    return {'active':True,'backend':backend,'release':df.RELEASE,'integrity':integrity}


def certificate_path():
    explicit=os.environ.get('R1_DIAGFAST_LIVE_CERTIFICATE','').strip()
    if explicit: return Path(explicit)
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'R1DF'/'LIVE_CERTIFICATE.json'


# A network UDA named SYS_R1_15A2_CALIBRATION_BUSY is *not* installed by
# the sealed HOTFIX2 calibrator. It may legitimately be absent in a .ver.
# Absence is not proof of idle, and arbitrary COM errors are NOT absence.
_BUSY_UDA = 'SYS_R1_15A2_CALIBRATION_BUSY'
_MISSING_ACK = 'MISSING_UDA_USER_CONFIRMED_ON_IDLE_COPY'


class MissingIdleMarker(df.DiagFastError):
    """Expected missing optional marker; only an explicit UI consent may proceed."""


def _is_exact_missing_busy_uda(exc):
    # The PTV Visum 2026 IDispatch exception has this exact NETWORK message.
    # It is deliberately narrower than checking HRESULT -2147352567, which
    # is shared with a wide range of unrelated Visum failures.
    # A plain Python/network exception with matching prose is NOT sufficient.
    # Visum2601 uses DISP_E_EXCEPTION. Verify this as well as the exact ID.
    hresult = getattr(exc, 'hresult', None)
    if hresult is None and getattr(exc, 'args', None):
        hresult = exc.args[0] if isinstance(exc.args[0], int) else None
    if hresult != -2147352567:
        return False
    detail = repr(exc).casefold()
    needle = ('network: could not find attribute with id ' + _BUSY_UDA).casefold()
    if needle not in detail:
        return False
    return detail[detail.index(needle)+len(needle):].startswith(('.', "'", '"', ',', ')', ' ', '\n'))


def assert_idle_visum(visum, policy=None, *, absent_marker_attestation=None):
    """Require explicit idle evidence; never infer idle from a generic COM error.

    A missing *optional* network UDA is accepted ONLY with a user attestation
    obtained by the live parity harness. A production launcher may reuse that
    attestation only via an intact model-bound live parity certificate.
    """
    if getattr(sys, '_r1_15a2_calibration_busy', False):
        raise df.DiagFastError('ANOTHER_15A2_RUN_IS_ACTIVE')
    prof = df.Profile('IDLE_CHECK', 'LEGACY')
    guarded = df.ReadOnlyProxy(visum, prof, policy)
    try:
        value = guarded.Net.AttValue(_BUSY_UDA)
    except Exception as exc:
        if _is_exact_missing_busy_uda(exc):
            if not isinstance(absent_marker_attestation, dict) or \
               absent_marker_attestation.get('mode') != _MISSING_ACK or \
               absent_marker_attestation.get('user_confirmed') is not True:
                raise MissingIdleMarker(
                    'DIAGFAST_IDLE_MARKER_ABSENT: optional model UDA is missing. '
                    'Live parity requires explicit confirmation of a separate, '
                    'idle Visum instance with a COPY of the .ver file.') from exc
            return {'idle': True, 'marker_status': 'ABSENT_USER_ATTESTED',
                    'network_marker': None, 'attestation_mode': _MISSING_ACK}
        raise df.DiagFastError(
            'DIAGFAST_IDLE_STATE_UNREADABLE: Cannot prove idle model; ' + repr(exc)
        ) from exc
    normalized = str(value).strip().lower()
    if normalized in ('1', '1.0', 'true'):
        raise df.DiagFastError('LIVE_PARITY_FORBIDDEN_DURING_ACTIVE_CALIBRATION')
    if normalized not in ('0', '0.0', 'false'):
        raise df.DiagFastError('DIAGFAST_IDLE_STATE_INVALID:' + repr(value))
    # Fail closed if the marker suddenly appears after the user confirmed
    # it was absent; a different/mutated model cannot reuse that consent.
    if isinstance(absent_marker_attestation, dict) and \
       absent_marker_attestation.get('mode') == _MISSING_ACK:
        raise df.DiagFastError('DIAGFAST_IDLE_MARKER_CHANGED_DURING_AUDIT')
    return {'idle': True, 'marker_status': 'PRESENT_ZERO',
            'network_marker': value}


def _ask_idle_copy_confirmation(message, title):
    """Explicit local operator acknowledgement; NEVER auto-accept in headless mode."""
    if os.name != 'nt':
        raise df.DiagFastError('DIAGFAST_IDLE_CONFIRMATION_WINDOWS_GUI_REQUIRED')
    try:
        import ctypes
        # MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2: default is No.
        response = ctypes.windll.user32.MessageBoxW(None, message, title,
                                                     0x00000004 | 0x00000030 | 0x00000100)
    except Exception as exc:
        raise df.DiagFastError('DIAGFAST_IDLE_CONFIRMATION_UI_ERROR:'+repr(exc)) from exc
    return response == 6  # IDYES, anything else (including window close) denies.


def attest_idle_for_live_parity(visum, policy=None, confirmation_callback=None):
    """Ask once, only if the optional UDA is absent; never mutate Visum.

    The confirmation is not a cross-process mutex: another Visum instance is
    invisible to the Python sys flag. The user must actually inspect the
    independent idle COPY before confirming; the certificate additionally
    binds the permission to a read-only snapshot of that same model.
    """
    try:
        proof = assert_idle_visum(visum, policy)
        return {'mode': 'PRESENT_ZERO', 'user_confirmed': False,
                'initial_check': proof['marker_status']}
    except MissingIdleMarker:
        confirm = confirmation_callback or _ask_idle_copy_confirmation
        message = (
            'Visum does not define optional network attribute '+_BUSY_UDA+'.\n\n'
            'This DOES NOT prove the model is idle.\n\n'
            'Continue ONLY if you opened a separate, IDLE Visum 2026 instance '
            'with a saved COPY of the .ver model.\n'
            'No R1_15A2 calibration or procedure execution may be active in '
            'this Visum instance, and you must leave the model unchanged.\n\n'
            'YES: I checked these conditions and authorize READ-ONLY parity.\n'
            'NO: Cancel (recommended if uncertain).'
        )
        if confirm(message, 'R1 DIAGFAST: verify idle model COPY') is not True:
            raise df.DiagFastError('DIAGFAST_IDLE_COPY_CONFIRMATION_DECLINED')
        attestation = {'mode': _MISSING_ACK, 'user_confirmed': True,
                       'basis': 'EXPLICIT_LOCAL_UI_CONFIRMATION_FOR_SEPARATE_IDLE_COPY',
                       'marker_at_start': 'ABSENT'}
        # Re-read. Confirming is not permission to ignore COM errors or a new
        # busy marker that appears during the UI interaction.
        assert_idle_visum(visum, policy, absent_marker_attestation=attestation)
        return attestation


def require_live_certificate(visum=None, cfg=None):
    """Bind permission to immutable release bytes, durable proof and tested state.

    Omitting visum is useful only to inspect the proof offline. The production
    launcher always supplies it, BEFORE it changes the model or saves a version.
    """
    path=certificate_path()
    if not path.is_file():
        raise df.DiagFastError('DIAGFAST_LIVE_PARITY_REQUIRED: run R1_15A2_DIAGFAST_LIVE_PARITY.py first; '+str(path))
    cert=json.loads(path.read_text('utf-8'))
    if (cert.get('status')!='LIVE_PARITY_VERIFIED' or cert.get('pairs_passed',0)<3
        or cert.get('release_manifest_sha256')!=df.digest_file(df.ROOT/'DIAGFAST_V1_RELEASE_MANIFEST.json')):
        raise df.DiagFastError('DIAGFAST_LIVE_CERTIFICATE_INVALID_OR_DIFFERENT_SOURCE:'+str(path))
    proof_folder = Path(cert.get('report_folder', ''))
    proof_files = cert.get('proof_files', {})
    required = {'PAIR_01_REPORT.json', 'PAIR_02_REPORT.json', 'PAIR_03_REPORT.json',
                'PERFORMANCE_BENCHMARK.json', 'EFFECTIVE_CONFIG.json'}
    idle_attestation = cert.get('idle_marker_attestation')
    if isinstance(idle_attestation, dict) and idle_attestation.get('mode') == _MISSING_ACK:
        required.add('IDLE_ATTESTATION.json')
    if not required.issubset(proof_files) or not cert.get('source_snapshot'):
        raise df.DiagFastError('DIAGFAST_LIVE_CERTIFICATE_MISSING_PROOF')
    for name, expected in proof_files.items():
        artifact = (proof_folder/name).resolve()
        if not artifact.is_relative_to(proof_folder.resolve()) or not artifact.is_file() or df.digest_file(artifact)!=expected:
            raise df.DiagFastError('DIAGFAST_LIVE_CERTIFICATE_PROOF_MISMATCH:'+name)
    if isinstance(idle_attestation, dict) and idle_attestation.get('mode') == _MISSING_ACK:
        recorded = json.loads((proof_folder/'IDLE_ATTESTATION.json').read_text('utf-8'))
        if (recorded.get('attestation') != idle_attestation or
            recorded.get('source_snapshot') != cert['source_snapshot']):
            raise df.DiagFastError('DIAGFAST_LIVE_CERTIFICATE_IDLE_PROOF_MISMATCH')
    for i in range(1,4):
        report=json.loads((proof_folder/('PAIR_%02d_REPORT.json'%i)).read_text('utf-8'))
        if (report.get('status')!='PARITY_PASS' or report.get('state_unchanged') is not True
            or report.get('scope')!='LIVE_VISUM_2026' or not report.get('artifact_count')):
            raise df.DiagFastError('DIAGFAST_LIVE_CERTIFICATE_PROOF_NOT_PASS')
    if visum is not None:
        if cfg is None:
            raise df.DiagFastError('DIAGFAST_LIVE_CERTIFICATE_MODEL_CONFIG_REQUIRED')
        # A model without the optional marker can only use an attestation
        # produced by a previously verified 3-pair read-only live audit.
        if isinstance(idle_attestation, dict) and idle_attestation.get('mode') == _MISSING_ACK:
            if idle_attestation.get('basis') != 'EXPLICIT_LOCAL_UI_CONFIRMATION_FOR_SEPARATE_IDLE_COPY':
                raise df.DiagFastError('DIAGFAST_LIVE_CERTIFICATE_IDLE_PROOF_INVALID')
            assert_idle_visum(visum,cfg.get('com_resilience',{}),
                              absent_marker_attestation=idle_attestation)
        else:
            assert_idle_visum(visum,cfg.get('com_resilience',{}))
        from r1_15a2_diagfast_parity_v1 import capture_state
        current=capture_state(visum,cfg)
        if current!=cert['source_snapshot']:
            differences=[k for k in set(current)|set(cert['source_snapshot']) if current.get(k)!=cert['source_snapshot'].get(k)]
            raise df.DiagFastError('DIAGFAST_LIVE_CERTIFICATE_DIFFERENT_MODEL_STATE:'+','.join(sorted(differences)))
    return cert


def invalidate_live_certificate(reason):
    """A new failed/in-progress audit must not leave a previous green gate active."""
    path=certificate_path()
    if not path.exists(): return None
    existing=json.loads(path.read_text('utf-8'))
    if existing.get('release_manifest_sha256') != df.digest_file(df.ROOT/'DIAGFAST_V1_RELEASE_MANIFEST.json'):
        return None
    backup=path.with_name(path.stem+'_PRIOR_'+uuid.uuid4().hex[:8]+'.json')
    shutil.copy2(path,backup)
    value={'status':'LIVE_PARITY_NOT_VALIDATED','reason':str(reason),'prior_certificate_backup':str(backup),
           'release_manifest_sha256':existing['release_manifest_sha256']}
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,indent=2),encoding='utf-8');tmp.replace(path)
    return str(backup)
