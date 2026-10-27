from pathlib import Path
from types import SimpleNamespace
from collections import Counter
import r1_15a2_diagfast_v1 as df

class Attr:
    def __init__(self, attrs=None, counter=None, **kw):
        self.a=dict(attrs or {},**kw);self.counter=counter if counter is not None else Counter()
    def AttValue(self,key):
        self.counter['AttValue']+=1; self.counter[key]+=1
        value=self.a[key]
        if isinstance(value,Exception):raise value
        return value
    def SetAttValue(self,*a):raise AssertionError('MUTATION')

class Coll:
    def __init__(self,items,bulk=True):self.items=list(items);self.bulk=bulk;self.counter=Counter()
    @property
    def GetAll(self):self.counter['GetAll']+=1;return tuple(self.items)
    @property
    def Count(self):return len(self.items)
    def __iter__(self):return iter(self.items)
    def GetMultiAttValues(self,attr,*rest):
        self.counter['GetMultiAttValues']+=1
        if not self.bulk:raise NotImplementedError('BULK_NOT_SUPPORTED')
        rows=[(i+11,x.a[attr]) for i,x in enumerate(self.items)]
        return rows[::-1] if attr=='FROMNODENO' else rows
    def ItemByKey(self,*key):
        self.counter['ItemByKey']+=1
        if len(key)==2:
            for x in self.items:
                if (x.a.get('FROMNODENO'),x.a.get('TONODENO'))==key:return x
        else:
            for x in self.items:
                if x.a.get('NO')==key[0]:return x
        raise KeyError(key)

class Matrix(Attr):
    def __init__(self,no,values,code=None,counter=None):
        super().__init__(NO=no,CODE=code or 'M%d'%no,NAME='Matrix '+str(no),MATRIXTYPE='Demand',
                         OBJECTTYPEREF='Zones',NUMROWS=len(values),NUMCOLS=len(values[0]) if values else 0,counter=counter)
        self.values=values;self.getvalues=0
    def GetValues(self):
        self.getvalues+=1
        return tuple(tuple(row) for row in self.values)


def make12(workspace,extra=2000,bulk=True):
    workspace=Path(workspace); workspace.mkdir(parents=True,exist_ok=True)
    env=df.reference_namespace('12D',workspace)
    import shutil
    for name in (env['AUTHORITY_CSV_NAME'],env['CITY_CSV_NAME']):shutil.copy2(df.ROOT/'authorities'/name,workspace/name)
    manifest=env['load_manifest']();wanted=df.requested_keys(manifest)
    keys=[(8000000+i,1000000+i,2000000+i) for i in range(extra)]+wanted
    # De-duplicate exactly, retaining order.
    keys=list(dict.fromkeys(keys));counts=Counter()
    links=[]
    for i,k in enumerate(keys):
        a=dict(NO=k[0],FROMNODENO=k[1],TONODENO=k[2],TYPENO=7,ROADNO='R1',TSYSSET='C,C_noT',LENGTH=1.25,
               NUMLANES=2,CAPPRT=1200.0,V0PRT=70.0,VDFNO=1)
        for j,ds in enumerate(env['PASSENGER_DSEGS']):a['VOLVEH_DSEG(%s,AP)'%ds]=(i%37+1)*(j+1)*.125
        a.update({'VOLVEH_DSEG(LNV,AP)':3.5,'VOLVEH_DSEG(NV,AP)':8.0,
                  'VOLVEH_TSYS(C,AP)':12.3,'VOLVEH_TSYS(C_noT,AP)':34.5,'VOLVEHPRT(AP)':99.0})
        links.append(Attr(a,counter=counts))
    cls=[]
    for r in manifest.values():
        k=tuple(int(r[x]) for x in ('current_link_no','current_from_node_no','current_to_node_no'))
        both=r.get('observation_direction')=='BOTH'
        cls.append(Attr(NO=int(r['countlocation_no']),CODE=r['countlocation_code'],NAME='Count',
            R1_OBS_ID=r['profile_id'],R1_ROLE=r['role'],R1_OBS_SCOPE=r.get('vehicle_scope_original') if both else r['vehicle_scope'],
            R1_OBS_BASIS=r['period_basis'],LINKNO=k[0],FROMNODENO=k[1],TONODENO=k[2],
            R1_OBS_RPDI=float(r['observed_passenger_cars_O']),R1_ACTIVE=1,R1_WEIGHT=float(r['live_weight']),
            R1_RPDI_READY=1,R1_DIR='BOTH' if both else 'DIRECTED',RELPOS=.5))
    v=SimpleNamespace(Net=SimpleNamespace(Links=Coll(links,bulk),CountLocations=Coll(cls),LinkTypes=Coll([Attr(NO=7,NAME='Road')])),
                      GetPath=lambda no:str(workspace),IO=SimpleNamespace(CurrentVersionFile=str(workspace/'fake.ver')))
    return v,env,manifest,counts


def add_matrices(v,n=681,with_time=True):
    # Dense, deterministic, nonuniform values. All matrices have distinct data.
    dist=[[float((i*7+j*3)%230) for j in range(n)] for i in range(n)]
    mats=[Matrix(9001,dist,code='R1_OSRM_DIST_KM')]
    if with_time:mats.append(Matrix(9002,[[x*.4 for x in row] for row in dist],code='R1_OSRM_TIME_MIN'))
    for no in list(range(9101,9118))+list(range(9301,9307)):
        vals=[[float(((i*3+j*5+no)%19)+1)*.013 for j in range(n)] for i in range(n)]
        mats.append(Matrix(no,vals))
    v.Net.Matrices=Coll(mats)
    op=Attr(OPERATIONTYPE=66,ACTIVE=0,CODE='',COMMENT='R1 STEP 11c v2.3')
    op.DemandMatrixCorrectionParameters=Attr(ProcedureVariant='TFLOWFUZZY')
    v.Procedures=SimpleNamespace(Operations=Coll([op]))
    return v
