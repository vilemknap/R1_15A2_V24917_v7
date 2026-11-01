"""Offline XLSX/CSV preparation; live Visum scripts need only NumPy, not Excel."""
import argparse
import csv
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

import openpyxl

ATTRS = ['NUM_VS','NUM_PUP','POP_ZP','E_C','E_NC','NE_C','NE_NC','PRENOC_SVK','AV_INCOME',
         'NUM_PM','NUM_PM_SMEAR','NUM_PUP_PLACES','NUM_STUD_VS_PLACES','POP_CENTRALITY_TERM']
YEARS = (2025,2040,2050,2060,2070)

def sha(raw): return hashlib.sha256(raw).hexdigest()

def table(path, sheet):
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        it = book[sheet].iter_rows(values_only=True)
        headers = [str(v).strip().upper() if v is not None else '' for v in next(it)]
        ix = {v:i for i,v in enumerate(headers) if v}
        if 'OSRM_MATRIX_ID' not in ix: raise ValueError('OSRM_MATRIX_ID missing')
        result = {}
        for row in it:
            key = row[ix['OSRM_MATRIX_ID']]
            if key is None: continue
            number = int(key)
            if float(key) != number or number in result: raise ValueError('Invalid/duplicate OSRM_MATRIX_ID')
            result[number] = {a:row[ix[a]] for a in ATTRS if a in ix}
        if set(result) != set(range(1,682)): raise ValueError('Expected exact zones 1..681')
        return result
    finally: book.close()

def numeric(value):
    if value is None or str(value).strip() == '' or isinstance(value,bool): return None
    try: x = float(str(value).strip().replace('\u00a0','').replace(',','.'))
    except (ValueError, TypeError): return None
    return x if math.isfinite(x) and x >= 0 else None

def write_csv(path, fields, rows):
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)

def prepare(manifest, target):
    records=json.loads(Path(manifest).read_text());files={r['label']:r for r in records}
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    provenance=[];sources={}
    for r in records:
        raw=Path(r['path']).read_bytes()
        sources[r['label']]={k:r[k] for k in ['file_id','filename']}
        sources[r['label']].update(size_bytes=len(raw),sha256=sha(raw))
    with zipfile.ZipFile(files['freight_zip']['path']) as archive:
        checksums={line.split()[1].lstrip('*'):line.split()[0] for line in archive.read('SHA256SUMS.txt').decode('utf-8-sig').splitlines() if line.strip()}
        for year in YEARS:
            folder=target/str(year);folder.mkdir(exist_ok=True)
            if year in (2025,2070):
                selected='zonal'+str(year);values=table(files[selected]['path'],'List1');sheet='List1'
                if year==2025:
                    supplementary=table(files['gravity2025']['path'],'vstupy_prod_att')
                    for no,row in values.items(): row['AV_INCOME']=supplementary[no]['AV_INCOME']
            else:
                selected='gravity'+str(year);sheet='vstupy_prod_att_R1';values=table(files[selected]['path'],sheet)
                if year==2040:
                    with open(files['raw2040']['path'],encoding='utf-8-sig',newline='') as stream:
                        for row in csv.DictReader(stream,delimiter=';'):
                            no=int(row['No'])
                            for attr in ATTRS[:9]:
                                if not math.isclose(float(row[attr]),numeric(values[no][attr]),rel_tol=1e-10,abs_tol=1e-8):
                                    raise ValueError('2040 CSV/workbook disagreement')
            rows=[];fallbacks=[]
            for no in range(1,682):
                row={'No':no}
                for attr in ATTRS:
                    raw=values[no].get(attr);value=numeric(raw)
                    row[attr]='KEEP_2022' if value is None else format(value,'.17g')
                    if value is None:fallbacks.append({'No':no,'attribute':attr,'source_value':str(raw),
                        'reason':'MISSING_SELECTED_SOURCE_ATTRIBUTE' if attr not in values[no] else 'INVALID_OR_MISSING_EXCEL_VALUE'})
                rows.append(row)
            zonal=folder/'ZONE_RAW_ATTRS.csv';write_csv(zonal,['No']+ATTRS,rows)
            cfg={'schema':'R1_SCENARIO_IO_20261101','year':year,'zone_count':681,'zone_attributes':ATTRS,
                 'zone_file':zonal.name,'zone_sha256':sha(zonal.read_bytes()),'freight_variant':'MC_MEAN_ROUNDED_HALF_UP',
                 'zone_source':{'label':selected,'sheet':sheet,'key':'OSRM_MATRIX_ID','fallback_policy':'KEEP_OPENED_2022_COPY_VALUE'},
                 'freight':{},'passenger_dsegs':['EXOG_EE_CF','EXOG_EE_CL','EXOG_EE_CS','EXOG_EE_CS_noT','EXOG_EE_CW','EXOG_EE_CW_noT',
                    'NATIVE_CF','NATIVE_CL','NATIVE_CS','NATIVE_CS_noT','NATIVE_CW','NATIVE_CW_noT']}
            if year==2025:cfg['zone_source']['income_supplement']='gravity2025:vstupy_prod_att:AV_INCOME; five absent additional attributes retain 2022'
            for code in ['LNV','NV']:
                source_name=f'R1_V14_{code}_OD_{year}_MC_MEAN.csv';raw=archive.read(source_name)
                if source_name not in checksums or sha(raw)!=checksums[source_name]:raise ValueError('Freight ZIP SHA mismatch:'+source_name)
                out_rows=[];seen=set();before=Decimal(0);after=0;diag=0;max_delta=Decimal(0)
                for r in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
                    o=int(r['FromZoneNo']);d=int(r['ToZoneNo']);v=Decimal(r['Value'])
                    if (o,d) in seen or not 1<=o<=681 or not 1<=d<=681 or not v.is_finite() or v<0:raise ValueError('Invalid freight row')
                    seen.add((o,d));rounded=int(v.quantize(Decimal('1'),rounding=ROUND_HALF_UP));before+=v;after+=rounded
                    if o==d:diag+=rounded
                    max_delta=max(max_delta,abs(v-rounded))
                    if rounded:out_rows.append({'FromZoneNo':o,'ToZoneNo':d,'Value':rounded})
                dest=folder/f'{code}_MC_MEAN_ROUNDED.csv';write_csv(dest,['FromZoneNo','ToZoneNo','Value'],out_rows)
                cfg['freight'][code]={'file':dest.name,'sha256':sha(dest.read_bytes()),'source_file':source_name,'source_sha256':sha(raw),
                    'source_total':str(before),'rounded_total':after,'rounded_diagonal':diag,'rounded_nonzero_od':len(out_rows),
                    'rounding_total_delta':str(Decimal(after)-before),'maximum_cell_rounding_delta':str(max_delta),'renormalized':False}
            (folder/'SCENARIO.json').write_text(json.dumps(cfg,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
            write_csv(folder/'ZONE_SOURCE_FALLBACKS.csv',['No','attribute','source_value','reason'],fallbacks)
            provenance.append({'year':year,'fallback_cells':len(fallbacks),'fallback_counts':{a:sum(r['attribute']==a for r in fallbacks) for a in ATTRS},
                               'freight':cfg['freight'],'primary_zone_source':selected,'source_sheet':sheet})
    (target/'INPUT_SOURCES.json').write_text(json.dumps(sources,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    (target/'INPUT_PREPARATION_REPORT.json').write_text(json.dumps(provenance,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return provenance

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True);parser.add_argument('--target',required=True);args=parser.parse_args()
    print(json.dumps([{'year':r['year'],'fallback_cells':r['fallback_cells'],'LNV':r['freight']['LNV']['rounded_total'],'NV':r['freight']['NV']['rounded_total']} for r in prepare(args.manifest,args.target)]))
