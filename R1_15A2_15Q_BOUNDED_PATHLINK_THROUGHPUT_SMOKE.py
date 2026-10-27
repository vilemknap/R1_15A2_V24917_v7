# -*- coding: utf-8 -*-
"""15Q: read-only bounded 256-row throughput smoke, no calibration/assignment.

Run inside open PTV Visum 2026: Scripts > Execute script file, outside Procedure
Sequence. Evidence beside Visum.IO.CurrentVersionFile. No version reload.
"""
import json
import time
from pathlib import Path
from datetime import datetime

import r1_15a2_runtime_v1 as rt
import r1_15a2_com_compat as com

PATH_COLS = rt.PATHLINK_KEY_HEADERS + rt.PATHLINK_EXTRA_ATTRS
DSEGS = ('NATIVE_CW','NATIVE_CW_noT')
PAGE_SIZE = 256
MAX_PAGES = 100  # up to 25600 raw rows/DSeg, NOT the full list


def run(visum):
    raw_path=visum.IO.CurrentVersionFile
    if not isinstance(raw_path,str) or not raw_path.strip():
        raise RuntimeError('VISUM_IO_CURRENTVERSIONFILE_UNREADABLE')
    ver=Path(raw_path)
    if not ver.is_absolute() or ver.suffix.lower() not in ('.ver','.verx'):
        raise RuntimeError('LOADED_VERSION_PATH_INVALID')
    base=ver.parent/'R1_15A2_15Q_PATHLINK_PERFORMANCE'
    out=base/('RUN_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    out.mkdir(parents=True,exist_ok=False)
    report={'schema':'R1_15A2_15Q_BOUNDED_LINK_RATE_V1',
            'loaded_version_file':str(ver), 'apply':False,
            'writes_to_visum':False,'assignment_executed':False,
            'rows_budget_per_dseg':PAGE_SIZE*MAX_PAGES,
            'page_size':PAGE_SIZE,'results':[]}
    try:
        lists,_=rt.get_lists_object(visum)
        filt,_=rt.get_all_routes_filter()
        for code in DSEGS:
            item={'dseg_code':code,'status':'STARTED','pages':0,'raw_rows':0,'link_children':0,'route_parents':0}
            report['results'].append(item)
            start=time.perf_counter()
            try:
                obj=rt.create_list(lists,'CreatePrTPathLinkList')
                obj.SetObjects(0,code,filt)
                for col in PATH_COLS:obj.AddColumn(col)
                ole,mid,kind=rt.verified_bounded_signature(obj)
                # Hard stop at the requested number of pages without assuming
                # that a partial final route makes up a complete source.
                for index in range(MAX_PAGES):
                    first=1+index*PAGE_SIZE
                    page=ole.Invoke(mid,0,kind,True,first,first+PAGE_SIZE-1)
                    rows=[] if page is None else [list(x) for x in page]
                    if len(rows)>PAGE_SIZE or any(len(x)!=len(PATH_COLS) for x in rows):
                        raise RuntimeError('BOUNDED_PAGE_SIZE_OR_COLUMN_MISMATCH')
                    item['pages']+=1
                    item['raw_rows']+=len(rows)
                    for row in rows:
                        if all(x in (None,'') for x in row[3:]):
                            item['route_parents']+=1
                        else:
                            item['link_children']+=1
                    if len(rows)<PAGE_SIZE:break
                item['elapsed_seconds']=round(time.perf_counter()-start,3)
                item['rows_per_second']=(item['raw_rows']/item['elapsed_seconds']
                    if item['elapsed_seconds']>0 else None)
                item['status']='BOUNDED_SAMPLE_READABLE'
                item['complete_export']=False
            except Exception as exc:
                item['status']='FAIL'
                item['error']=rt.compact_error(exc)
                item['elapsed_seconds']=round(time.perf_counter()-start,3)
        report['status']='SAMPLE_PASSED' if all(x['status']=='BOUNDED_SAMPLE_READABLE'
           for x in report['results']) else 'SAMPLE_FAILED'
    except Exception as exc:
        report['status']='ERROR'
        report['error']=rt.compact_error(exc)
    finally:
        rt.write_json(out/'15Q_PATHLINK_THROUGHPUT_SMOKE.json',report)
        (out/'00_FINAL_STATUS.txt').write_text(report['status']+'\n',encoding='utf-8')
        (base/'LATEST_RUN.txt').write_text(str(out),encoding='utf-8')
    return report

if 'Visum' in globals():
    run(globals()['Visum'])
elif __name__=='__main__':
    raise RuntimeError('Run inside existing Visum with a saved version open')
