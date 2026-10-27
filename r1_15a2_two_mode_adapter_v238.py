"""Read-only 15A2 adapter using a fresh two-mode cache for supply and generation."""
from pathlib import Path

import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError
from r1_15a2_supply_visum import VisumAdapter as BaseAdapter, base
from r1_15a2_sequence_v23 import propose_sequence_supply
from r1_15a2_two_mode_v238 import (
    TwoModeRouteCollector, collect_two_modes, DEFAULT_SETTINGS, PROVISIONAL,
    atomic_json, QuietControl)


class VisumAdapter(BaseAdapter):
    def __init__(self, visum, cfg, control=None):
        if cfg.get('apply') is not False:
            raise SupplyContractError('TWO_MODE_DESIGN_ONLY_APPLY_FORBIDDEN')
        if cfg.get('two_mode', {}).get('design_only') is not True:
            raise SupplyContractError('EXPLICIT_TWO_MODE_DESIGN_ONLY_CONTRACT_REQUIRED')
        super().__init__(visum,cfg)
        self.control=control or QuietControl()
        self.cache=None
        self.cache_snapshot=None
        self.initial_snapshot=None

    def design_checkpoint(self, phase):
        self.control.checkpoint(phase,force=True)

    def preflight(self, folder):
        self.design_checkpoint('PREFLIGHT')
        out=super().preflight(folder)
        self.initial_snapshot=self.snapshot()
        return out

    def diagnostics(self, folder, label='CURRENT'):
        self.design_checkpoint('BASELINE_12D_11D')
        return super().diagnostics(folder,label)

    def _deny_write(self, *args, **kwargs):
        raise SupplyContractError('EXPERIMENTAL_TWO_MODE_NO_ASSIGNMENT_APPLY_OR_RELOAD')

    def save(self, path):
        # A read-only design needs a fingerprint, not a new .ver. In particular,
        # SaveVersion could change IO.CurrentVersionFile to the checkpoint path.
        dest=Path(path).with_suffix('.snapshot.json')
        atomic_json(dest,{'schema':'READ_ONLY_FINGERPRINT_NOT_A_VISUM_VERSION',
                          'snapshot':self.snapshot(),'apply_permitted':False})
        return {'path':str(dest),'sha256':rt.sha256_file(dest),
                'not_loadable_version':True,'save_version_called':False}

    assign=_deny_write
    apply_supply=_deny_write
    apply_generation=_deny_write
    apply_td=_deny_write
    restore=_deny_write

    def supply_design(self, diag, folder, snapshot):
        if self.cfg.get('apply') is not False:
            raise SupplyContractError('TWO_MODE_DESIGN_ONLY_APPLY_FORBIDDEN')
        folder=Path(folder)
        self.design_checkpoint('SUPPLY_TWO_MODE_BEGIN')
        links=self.read_links()
        # Do not retain any live link COM objects in the cache or exception frames.
        links={k:{a:v for a,v in r.items() if a!='object'} for k,r in links.items()}
        settings=dict(DEFAULT_SETTINGS,**self.cfg['two_mode'])
        settings['dseg_path_volume_relative_tolerance']=self.cfg['dseg_path_volume_relative_tolerance']
        seq=self.cfg['supply'].get('sequence',{})
        if self.cache is not None:
            raise SupplyContractError('TWO_MODE_STORE_ALREADY_EXISTS_THIS_RUN')
        collector=TwoModeRouteCollector(diag['d12']['rows'],self.policy,snapshot['state_hash'],
            links,folder/'TWO_MODE_PATH_STORE.sqlite',settings,self.control,
            duplicate_scope_policy=seq.get('design_only_duplicate_scope_policy','FAIL'),
            max_unique_sequences=seq.get('max_unique_sequences',100000),
            max_pairs_per_market=seq.get('max_pairs_per_market',64))
        atomic_json(folder/'SUPPLY_DUPLICATE_SCOPE_AUDIT.json',collector.duplicate_scope_audit)
        try:
            export=collect_two_modes(self.visum,collector,self.cfg,folder)
            self.design_checkpoint('SUPPLY_SNAPSHOT_RECHECK')
            if self.snapshot()!=snapshot:
                raise SupplyContractError('STATE_CHANGED_DURING_TWO_MODE_EXPORT')
            # Write parity before the old technical gate so a failure has evidence.
            rows=[]
            for i,row in enumerate(collector.profiles):
                m=float(row['model']);diff=abs(collector.flow[i]-m)
                tol=max(self.policy.parity_absolute_tolerance,self.policy.parity_relative_tolerance*abs(m))
                rows.append({'countlocation_no':row.get('countlocation_no',i),
                    'model':m,'path_flow':collector.flow[i],'absolute_difference':diff,
                    'tolerance':tol,'passes':diff<=tol})
            rt.write_csv(folder/'SUPPLY_PROFILE_FLOW_PARITY.csv',rows)
            self.design_checkpoint('SUPPLY_SEQUENCE_CANDIDATES')
            design=propose_sequence_supply(collector,links,self.baseline_addval,self.policy,
                sequence_caps=seq.get('sequence_cap_schedule',[4,2,1]),
                max_collateral_ratio=seq.get('max_collateral_volume_to_driver_ratio'))
            for candidate in design['candidates']:
                candidate['representative_sequence_confidence']=candidate.get('confidence')
                candidate['confidence']='PROVISIONAL_MODE_GEOMETRY_REQUIRES_FULL_IDENTITY_AND_ASSIGNMENT'
                candidate['impact_audit_basis']='ALL_12_DSEG_VOLUMES_WITH_PROVISIONAL_TWO_MODE_GEOMETRY'
                candidate.update(provisional=True,apply_permitted=False,
                    geometry_identity=PROVISIONAL,
                    requires_full_geometry_verification_before_apply=True)
            design.update(provisional=True,apply_permitted=False,geometry_identity=PROVISIONAL,
                pathlink_geometry_full_identity_proven=False,
                duplicate_scope_audit=collector.duplicate_scope_audit,
                design_only_duplicate_driver_exclusion=bool(collector.duplicate_scope_audit['conflicting_same_source_groups']),
                path_export_summary=export,route_store_file='TWO_MODE_PATH_STORE.sqlite')
            atomic_json(folder/'SUPPLY_PATH_SEQUENCE_DESIGN.json',design)
            self.cache=collector
            self.cache_snapshot=snapshot
            self.supply_path_proof={'parent_hash':snapshot['state_hash'],
                'assignment_path_hash':design['authority']['assignment_path_hash'],
                'apply_permitted':False,'geometry_identity':PROVISIONAL}
            return design
        except BaseException as exc:
            collector.ready=False
            collector.summary.update(status='STOPPED' if getattr(exc,'stop_design_run',False) else 'FAILED',
                                     fatal_errors=[type(exc).__name__+': '+str(exc)])
            atomic_json(folder/'TWO_MODE_CACHE_AUDIT.json',collector.summary)
            collector.close()
            raise

    def generation_design(self, diag, folder):
        if self.cache is None or not self.cache.ready:
            # Never fall back to a second full COM export after a failed supply.
            raise SupplyContractError('TWO_MODE_CACHE_UNAVAILABLE_NO_DUPLICATE_COM_EXPORT')
        self.design_checkpoint('GENERATION_VERIFY_SAME_STATE_CACHE')
        if self.snapshot()!=self.cache_snapshot:
            raise SupplyContractError('GENERATION_CACHE_STATE_MISMATCH')
        incidence_export=self.cache.incidence(self.cfg,self.actuatable_zones)
        rt.write_json(Path(folder)/'TWO_MODE_CACHE_REUSE.json',{
            'cache':self.cache.route_db_path,'parent_hash':self.cache_snapshot['state_hash'],
            'geometry_identity':PROVISIONAL,'provisional':True,'apply_permitted':False,
            'additional_com_path_exports':0})
        return base.path_guidance_design(self.visum,folder,self.cfg,diag['d12'],self.zones,
            self.actuatable_zones,incidence_and_export=incidence_export,
            progress_callback=self.design_checkpoint)

    def generation_preview(self, context, scale):
        proposal=super().generation_preview(context,scale)
        proposal.update(provisional=True,apply_permitted=False,geometry_identity=PROVISIONAL)
        return proposal

    def td_design(self, diag, block, scale, folder):
        self.design_checkpoint(block)
        return super().td_design(diag,block,scale,folder)

    def close(self):
        if self.cache is not None:
            self.cache.close()
            self.cache=None
