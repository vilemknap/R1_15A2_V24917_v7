"""V2.3 Visum adapter: only replace the V2.2 ADDVAL1 candidate designer.

The accepted-state controller, original COM writer, all matrix guards, and
TG/TD component implementation are inherited unchanged from V2.2.
"""
from pathlib import Path
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply_visum import VisumAdapter as V22VisumAdapter
from r1_15a2_sequence_v23 import ActualSequenceRouteCollector, propose_sequence_supply


class VisumAdapter(V22VisumAdapter):
    def supply_design(self, diag, folder, snapshot):
        folder=Path(folder)
        links=self.read_links()
        raw=self.cfg.get('supply', {}).get('sequence', {})
        # Even in diagnostic mode the original counts, 12D and objective are
        # immutable. Exclude ONLY conflicting same-source route-selection drivers.
        scope_mode=("FAIL" if self.cfg.get('apply') else
            raw.get('design_only_duplicate_scope_policy', 'FAIL'))
        collector=ActualSequenceRouteCollector(
            diag['d12']['rows'],self.policy,snapshot['state_hash'],
            [key for key,row in links.items() if row['eligible']],
            db_path=folder/'SUPPLY_ACTUAL_ROUTE_STORE.sqlite',
            max_unique_sequences=raw.get('max_unique_sequences',100000),
            max_pairs_per_market=raw.get('max_pairs_per_market',64),
            duplicate_scope_policy=scope_mode)
        rt.write_json(folder/'SUPPLY_DUPLICATE_SCOPE_AUDIT.json',
                      collector.duplicate_scope_audit)
        try:
            cfg=dict(self.cfg,path_export_dsegs=list(self.cfg['supply']['passenger_dsegs']),
                mutable_dsegs=[],include_exog_ee_paths=True,
                require_all_path_export_dsegs=True)
            _,export=rt.export_actual_paths_and_build_incidence(
                self.visum,folder,cfg,diag['d12']['rows'],[],
                route_batch_callback=collector.consume,build_incidence=False)
            design=propose_sequence_supply(collector,links,self.baseline_addval,self.policy,
                sequence_caps=raw.get('sequence_cap_schedule',[4,2,1]),
                max_collateral_ratio=raw.get('max_collateral_volume_to_driver_ratio'))
            design['duplicate_scope_audit']=collector.duplicate_scope_audit
            design['design_only_duplicate_driver_exclusion']=bool(
                collector.duplicate_scope_audit['conflicting_same_source_groups'])
            design['path_export_summary']=export
            design['route_store_file']='SUPPLY_ACTUAL_ROUTE_STORE.sqlite'
            self.supply_path_proof={
                'parent_hash':snapshot['state_hash'],
                'assignment_path_hash':design['authority']['assignment_path_hash']}
            rt.write_json(folder/'SUPPLY_PATH_SEQUENCE_DESIGN.json',design)
            return design
        finally:
            collector.close()
