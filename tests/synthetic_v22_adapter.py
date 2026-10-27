"""Deterministic synthetic adapter, NOT a Visum or traffic-equilibrium emulator.

Only verifies the real controller's transactions, selection and state isolation.
"""
import copy,json,hashlib
from pathlib import Path
from r1_15a2_supply import canonical_hash,SupplyContractError,key_text
from r1_15a2_supply_visum import base
import r1_15a2_core as core


class SyntheticAdapter:
    runtime_backend = "SYNTHETIC_STATE_MACHINE_STUB_NOT_ASSIGNMENT"
    def __init__(self,cfg,*,mutate_supply_demand=False,flat=False,broken_restore=False,fail_save=False):
        self.cfg=cfg
        self.state={'a':{'1|1|2':0.,'2|2|3':0.},'q':1000.,'generation':1.,'b':0.}
        self.baseline_addval=None;self.assignments=[];self.restores=0;self.saves=[]
        self.mutate_supply_demand=mutate_supply_demand;self.flat=flat
        self.broken_restore=broken_restore;self.fail_save=fail_save
    def preflight(self,folder):
        self.baseline_addval={tuple(map(int,k.split('|'))):v for k,v in self.state['a'].items()}
        return {'apply_preflight_passes':True,'SYNTHETIC_TEST_ONLY':True}
    def snapshot(self):
        s=self.state
        gen={'ADD_PROD_W':{'1':s['generation']}}
        td=[{'component':'WORK_E_C','current_b':s['b'],'current_c':-.1,'status':'OK'}]
        mats=[{'matrix_no':9101,'rows':2,'cols':2,'sha256_float64_le':canonical_hash([s['q'],s['b']])}]
        ds={'NATIVE_CW':9101}
        out={'addval1':dict(s['a']),'addval_hash':canonical_hash(s['a']),
             'fixed_link_hash':'fixed','matrix_hash':canonical_hash(mats),'matrices':mats,
             'dseg_map':ds,'dseg_hash':canonical_hash(ds),'generation_hash':canonical_hash(gen),
             'generation_values':gen,'td_values':td,'td_hash':canonical_hash(td),'operations_hash':'ops'}
        out['state_hash']=canonical_hash(out)
        return out
    def save(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        if self.fail_save and path.name=='EVALUATED_CANDIDATE.ver':raise RuntimeError('INJECTED_SAVE_FAILURE')
        path.write_text(json.dumps({'SYNTHETIC_CHECKPOINT_NOT_VISUM':True,'state':self.state}))
        self.saves.append(str(path))
        return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
    def restore(self,checkpoint,snapshot):
        self.restores+=1
        p=Path(checkpoint['path'])
        if hashlib.sha256(p.read_bytes()).hexdigest()!=checkpoint['sha256']:raise SupplyContractError('CHECKPOINT_BYTES_CHANGED')
        self.state=json.loads(p.read_text())['state']
        if self.broken_restore:self.state['a']['1|1|2']=99
        if self.snapshot()!=snapshot:raise SupplyContractError('ROLLBACK_STATE_NOT_IDENTICAL')
        return self.snapshot()
    def assign(self,folder,*,supply_only):
        self.assignments.append({'supply_only':supply_only,'a':dict(self.state['a']),'q':self.state['q']})
        if self.mutate_supply_demand and supply_only and any(self.state['a'].values()):self.state['q']+=1
        return 0.
    def diagnostics(self,folder,label='CURRENT'):
        s=self.state
        model=600. if self.flat else .6*s['q']-200*s['a']['1|1|2']-350*s['a']['2|2|3']
        error=.4 if self.flat else .4-.2*s['b']
        sig={'component':'WORK_E_C','calibratable':True,'authority_id':'SYNTHETIC_ONLY',
             'target_status':'ACTIVE_COMPONENT_DIST_TARGET','l1_half':error,'rmse_share':error,
             'mean_target':10.,'mean_delta':-10*error,'conditioned_volume':s['q'],
             'model_bins':[{'bin_low':0.,'bin_high':10.,'target_share':.5,'model_share':.5+error},
                           {'bin_low':10.,'bin_high':20.,'target_share':.5,'model_share':.5-error}]}
        counts=[{'countlocation_no':'a','role':'CALIBRATION','link_no':1,'from_node_no':1,'to_node_no':2,'observed':1000.,'model':model},
                {'countlocation_no':'v','role':'VALIDATION','link_no':2,'from_node_no':2,'to_node_no':3,'observed':100.,'model':100.}]
        summary={'component_dist_summary_rows':[{'component':'WORK_E_C','family':'WORK','target_status':'ACTIVE_COMPONENT_DIST_TARGET',
                  'mean_model_conditioned':10-10*error,'mean_target':10.,'l1_distance_half':error,'rmse_share':error}]}
        return {'d12':{'rows':counts},'d11':{'summary':summary},'signals':{'WORK_E_C':sig}}
    def supply_design(self,diag,folder,snapshot):
        return {'candidates':[{'candidate_id':'candidate_'+str(i),'parent_hash':snapshot['state_hash'],
                 'changes':[{'key':list(map(int,k.split('|'))),'expected_old':v,'new':v-1,'delta':-1,'equivalent_seconds':-10}]} for i,(k,v) in enumerate(snapshot['addval1'].items())]}
    def apply_supply(self,candidate,snapshot,folder):
        if self.snapshot()!=snapshot:raise SupplyContractError('STALE_PARENT')
        for r in candidate['changes']:self.state['a'][key_text(r['key'])]=r['new']
    def generation_design(self,diag,folder):return {}
    def generation_preview(self,context,scale):
        old=self.state['generation'];new=old+.03*scale
        return {'candidate_rows':[{'zone_no':1,'attr':'ADD_PROD_W','current':old,'proposed':new}]}
    def apply_generation(self,context,scale,folder):
        rows=self.generation_preview(context,scale)['candidate_rows']
        self.state['generation']=rows[0]['proposed'];self.state['q']=1000*self.state['generation']
        return rows
    def td_design(self,diag,block,scale,folder):
        return {'candidate_rows':[{'component':'WORK_E_C','candidate_b':self.state['b']+.08*scale,'candidate_c':-.1}]}
    def apply_td(self,rows):self.state['b']=rows[0]['candidate_b']
    def parameter_persistence(self,block,rows):pass
    def block_gate(self,block,before,after,rows):
        if block in ('SUPPLY_ADDVAL1','GENERATION'):
            return core.acceptance_decision(before['d12']['rows'],after['d12']['rows'],before['d11']['summary'],after['d11']['summary'],self.cfg)
        return base.td_acceptance_decision(before['d12']['rows'],after['d12']['rows'],before['d11']['summary'],after['d11']['summary'],
                          before['signals'],after['signals'],[r['component'] for r in rows],self.cfg)


def synthetic_config():
    return {'apply':True,'max_cycles':1,'max_accepted_blocks':10,
            'block_schedule':['SUPPLY_ADDVAL1','GENERATION','TD_COMPONENT_WORK'],
            'backtracking_scales':[1.,.5,.25],
            'matrix_scope_by_block':{'GENERATION':{'matrix_nos':[9101]},'TD_COMPONENT_WORK':{'matrix_nos':[9101]}},
            'shared_objective':{'cal_weight':1.,'idp_weight':1.,'minimum_improvement':1e-8},'td':{},'supply':{}}
