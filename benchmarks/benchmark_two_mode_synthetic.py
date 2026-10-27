"""Offline scalability exercise, NOT a Visum/COM throughput prediction."""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1_15a2_supply import SupplyPolicy
from r1_15a2_two_mode_v238 import TwoModeRouteCollector,EXPECTED_MODE_DSEGS


def run(n=5000,length=100):
    chain=tuple((1000+i,i+1,i+2) for i in range(length))
    links={e:{'addval1':0.,'t0_c_seconds':60.,'eligible':True} for e in chain}
    bymode={m:sorted(codes) for m,codes in EXPECTED_MODE_DSEGS.items()}
    allcodes=[c for group in bymode.values() for c in group]
    volumes={c:i+1. for i,c in enumerate(allcodes)}
    expected=n*sum(volumes.values())
    e=chain[0]
    profiles=[{'countlocation_no':'mock','link_no':e[0],'from_node_no':e[1],
         'to_node_no':e[2],'observed':expected,'model':expected,'role':'CALIBRATION'}]
    with TemporaryDirectory() as d:
        db=Path(d)/'two_mode.sqlite'
        c=TwoModeRouteCollector(profiles,SupplyPolicy(),'SYNTHETIC_ONLY',links,db)
        start=time.monotonic();times={}
        try:
            for mode,group in bymode.items():
                for code in group:
                    v=volumes[code]
                    c.add_parents(code,mode,((1,j+2,1,v) for j in range(n)),
                        {'matrix_interzonal':n*v,'matrix_total':n*v,'matrix_diagonal':0})
            times['parent_storage_seconds']=time.monotonic()-start
            tick=time.monotonic()
            for mode in bymode:
                def rows():
                    for j in range(n):
                        yield [1,j+2,1,'','','','']
                        for ix,e in enumerate(chain,1):yield ['', '', '', ix, *e]
                c.add_geometry(mode,rows())
            times['geometry_validation_and_storage_seconds']=time.monotonic()-tick
            tick=time.monotonic();c.build_route_evidence();c.finish()
            impact=c.impact([{'key':list(chain[0]),'delta':1}],0,expected)
            times['flow_and_impact_seconds']=time.monotonic()-tick
            assert c.flow==[expected]
            assert impact['affected_routes']==n*12
            assert impact['max_abs_path_seconds']==10
            assert impact['by_cal_class']['DRIVER_ON']['volume']==expected
            result={'status':'PASS','source':'SYNTHETIC_PYTHON_GENERATORS_NOT_VISUM_COM',
                'read_only':True,'segment_count':12,'parent_volume_records':n*12,
                'unique_geometry_routes':n*2,'stored_geometric_link_occurrences':n*2*length,
                'expanded_equivalent_link_occurrences':n*12*length,
                'sqlite_bytes':db.stat().st_size,'elapsed_seconds':time.monotonic()-start,
                'timings':times,'speedup_claim_for_visum':None,
                'geometry_identity_proven':False,'apply_permitted':False}
            return result
        finally:c.close()


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--out',required=True);a.add_argument('--routes-per-mode',type=int,default=5000)
    x=a.parse_args();result=run(x.routes_per_mode)
    Path(x.out).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
