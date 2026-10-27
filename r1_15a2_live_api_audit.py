"""Read-only, non-modal collection of live Visum COM compatibility evidence.

No assignment, matrix writes, parameter writes, LoadVersion or SaveVersion.
Unknown bindings are reported, NEVER automatically approved. This report is
structural evidence, not a convergence/path coverage or calibration PASS.
"""
from __future__ import annotations
import csv
import importlib
import json
import math
import os
import re
import struct
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import r1_15a2_com_compat as com

RELEASE = "R1_15A2_V2_3_6_LIVE_TG_09F4_PREFEED_REMEDIATION"


def json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (list, tuple)):
        return [json_value(x) for x in value]
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if getattr(value, "_oleobj_", None) is not None:
        return {"com_proxy_type": type(value).__name__}
    return {"python_type": type(value).__name__, "representation": repr(value)[:400]}


def error_info(exc):
    return {"type": type(exc).__name__, "message": str(exc)[:2000],
            "hresult": getattr(exc, "hresult", None),
            "excepinfo": json_value(getattr(exc, "excepinfo", None))}


def read_attributes(obj, names):
    result = []
    for name in names:
        try:
            value = obj.AttValue(name)
            result.append({"id": name, "status": "READ", "python_type": type(value).__name__, "value": json_value(value)})
        except Exception as exc:
            result.append({"id": name, "status": "UNAVAILABLE", "error": error_info(exc)})
    return result


def type_members(obj):
    """Read ITypeInfo only. Do not invoke enumerated functions/properties."""
    ole = getattr(obj, "_oleobj_", None)
    if ole is None:
        return {"status": "NO_OLE_TYPEINFO", "members": []}
    try:
        info = ole.GetTypeInfo()
        attrs = info.GetTypeAttr()
        count = attrs.cFuncs if hasattr(attrs, "cFuncs") else attrs[8]
        members = []
        for i in range(int(count)):
            desc = info.GetFuncDesc(i)
            memid = desc.memid if hasattr(desc, "memid") else desc[0]
            invkind = desc.invkind if hasattr(desc, "invkind") else desc[4]
            names = list(info.GetNames(memid))
            members.append({"names": names, "memid": int(memid), "invkind": int(invkind), "signature": repr(desc)[:1600]})
        return {"status": "READ", "interface": info.GetDocumentation(-1)[0], "members": members}
    except Exception as exc:
        return {"status": "TYPEINFO_UNAVAILABLE", "error": error_info(exc), "members": []}


def attribute_catalog(obj):
    """Best-effort catalog with exact live IDs. It is discovery, not alias matching."""
    try:
        attrs = com.object_property(obj, "Attributes")
        rows = com.collection_items(attrs, "Attributes")
        out = []
        for item in rows:
            row = {}
            for name in ("ID", "Name", "ValueType", "Editable", "IsUserDefined"):
                try:
                    row[name] = json_value(getattr(item, name))
                except Exception:
                    continue
            if row:
                out.append(row)
        return {"status": "READ", "attributes": out}
    except Exception as exc:
        return {"status": "CATALOG_UNAVAILABLE", "error": error_info(exc)}


def typelib_evidence(visum):
    try:
        info = visum._oleobj_.GetTypeInfo()
        lib, _ = info.GetContainingTypeLib()
        wanted = {"OperationType", "ValueType", "EnumValueType", "RouteFilterT", "MatrixType", "MatrixTypeT", "MatrixDataSourceType", "DataSourceType", "ObjectTypeRefT", "FileTypeT",
                  "IPrTPathList", "IPrTPathLinkList", "IPrTAssQualityList", "IPrTAssignmentPara",
                  "ITripDistributionDStratPara", "IGravitationPara", "IOperations", "IOperation",
                  "ITripGenerationPara", "ITripGenerationDStratPara", "ITripDistributionPara", "IPrTEquilibriumAssignmentPara", "INetBalancingPara", "IPrTGeneralPara", "IAttributes", "IAttribute"}
        result = {"status": "READ", "library": json_value(lib.GetDocumentation(-1)), "types": {}}
        for i in range(int(lib.GetTypeInfoCount())):
            name = lib.GetDocumentation(i)[0]
            if name not in wanted:
                continue
            ti = lib.GetTypeInfo(i)
            ta = ti.GetTypeAttr()
            nfunc = ta.cFuncs if hasattr(ta, "cFuncs") else ta[8]
            nvar = ta.cVars if hasattr(ta, "cVars") else ta[9]
            entry = {"functions": [], "constants": []}
            for j in range(int(nfunc)):
                d = ti.GetFuncDesc(j)
                memid = d.memid if hasattr(d, "memid") else d[0]
                entry["functions"].append({"names": list(ti.GetNames(memid)), "signature": repr(d)[:1600]})
            for j in range(int(nvar)):
                d = ti.GetVarDesc(j)
                memid = d.memid if hasattr(d, "memid") else d[0]
                entry["constants"].append({"names": list(ti.GetNames(memid)), "descriptor": repr(d)[:800]})
            result["types"][name] = entry
        return result
    except Exception as exc:
        return {"status": "TYPELIB_UNAVAILABLE", "error": error_info(exc)}


def bounded_list_sample(obj, limit=5, retry_policy=None):
    """Never accidentally fetch millions of rows through a zero-argument getter."""
    meta = type_members(obj)
    methods = [x for x in meta.get("members", []) if x["names"] and x["names"][0].lower() == "savetoarray"]
    if methods:
        names = {str(x).lower() for x in methods[0]["names"][1:]}
        if not {"firstobject", "lastobject"} <= names:
            return {"status": "NO_CONFIRMED_BOUNDED_SIGNATURE", "typeinfo": meta}
        try:
            desc = methods[0]
            flag = desc["invkind"] if desc["invkind"] in (1, 2) else 2
            values = com.bounded_ole_invoke_with_retry(
                obj._oleobj_, desc["memid"], flag, 1, int(limit),
                retry_policy=retry_policy, label="LIVE_API_BOUNDED_SAMPLE")
            return {"status": "READ_BOUNDED", "first": 1, "last": limit, "rows": json_value(values)}
        except Exception as exc:
            return {"status": "BOUNDED_READ_FAILED", "error": error_info(exc), "typeinfo": meta}
    return {"status": "NO_TYPEINFO_BOUNDED_READ_SKIPPED", "typeinfo": meta}


def current_version_file(visum):
    """Full current *.ver pathname, not Visum's configurable project folder.

    PTV Visum 2026 COM: IIO.CurrentVersionFile is a read-only property
    containing the complete path and filename of the loaded version.
    Never guess the path from cwd, __file__, GetPath(2) or LOCALAPPDATA.
    """
    try:
        io = com.object_property(visum, "IO")
        raw = com.member_value(getattr(io, "CurrentVersionFile"))
    except Exception as exc:
        raise RuntimeError("VISUM_CURRENT_VERSION_FILE_UNAVAILABLE: Visum.IO.CurrentVersionFile is required") from exc
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("VISUM_CURRENT_VERSION_FILE_EMPTY: first open a saved .ver file")
    path = Path(raw.strip()).expanduser()
    if path.suffix.lower() not in (".ver", ".verx"):
        raise RuntimeError("VISUM_CURRENT_VERSION_FILE_BAD_EXTENSION: %r" % str(path))
    if not path.is_absolute():
        raise RuntimeError("VISUM_CURRENT_VERSION_FILE_NOT_ABSOLUTE: %r" % str(path))
    if not path.is_file():
        raise RuntimeError("VISUM_CURRENT_VERSION_FILE_NOT_FOUND: %r" % str(path))
    return path


def project_output_root(visum):
    """Output directory strictly beside the .ver loaded in this Visum."""
    version_file = current_version_file(visum)
    root = version_file.parent / "R1_15A2_COM_API_PREFLIGHT"
    root.mkdir(parents=True, exist_ok=True)
    return root, "Visum.IO.CurrentVersionFile"

def collect_live_api(visum, cfg, folder, extra_checks=()):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    report = {"release": RELEASE, "started": datetime.now().astimezone().isoformat(),
              "status": "RUNNING", "read_only_model": True, "assignment_executed": False,
              "apply_permitted": False, "checks": [], "catalogs": {}}
    def save():
        target = folder / "COM_API_PREFLIGHT.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(json_value(report), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.replace(temp, target)
    def check(label, fn, required=True):
        try:
            data = fn()
            status = "FAIL" if isinstance(data, dict) and data.get("passes") is False else "PASS"
            report["checks"].append({"check": label, "status": status, "required": required, "result": json_value(data)})
            save()
            return data
        except Exception as exc:
            report["checks"].append({"check": label, "status": "FAIL", "required": required, "error": error_info(exc)})
            save()
            return None
    (folder / "00_STARTED.txt").write_text(RELEASE + "\n", encoding="utf-8")
    save()
    report["runtime"] = {"python": sys.version, "executable": sys.executable, "bits": 8*struct.calcsize("P"),
                         "main_thread": threading.current_thread() is threading.main_thread(),
                         "os": os.name, "COM_activation": "INJECTED_INSTANCE_ONLY"}
    def environment():
        com.bind_injected({"Visum": visum})
        # Standard 3.13 uses the main thread; Legacy file execution can use a
        # host-managed wx thread and still provides supported COM access. Do
        # not reject that documented mode or create/marshal another instance.
        module = importlib.import_module("numpy")
        return {"numpy": module.__version__, "module_file": str(getattr(module, "__file__", "")),
                "thread_policy": "USE_HOST_INJECTED_OBJECT_ON_CALLING_THREAD; LEGACY_HOST_THREAD_ALLOWED"}
    check("ENVIRONMENT_AND_INJECTED_INSTANCE", environment)
    report["catalogs"]["Visum"] = type_members(visum)
    try:
        report["catalogs"]["Net"] = {"typeinfo": type_members(visum.Net), "attributes": attribute_catalog(visum.Net)}
    except Exception as exc:
        report["catalogs"]["Net"] = {"unavailable": error_info(exc)}
    try:
        # A catalog is discovery-only: its absence never creates a fake alias.
        report["catalogs"]["Zones"] = {"attributes": attribute_catalog(visum.Net.Zones)}
    except Exception as exc:
        report["catalogs"]["Zones"] = {"unavailable": error_info(exc)}
    report["typelib"] = typelib_evidence(visum)
    report["instance"] = {}
    for attr in ("VersionNumber", "UserName", "VersionName"):
        try:
            value = com.member_value(getattr(visum, attr))
            report["instance"][attr] = json_value(value)
        except Exception as exc:
            report["instance"][attr] = {"unavailable": error_info(exc)}
    try:
        report["instance"]["IO.CurrentVersionFile"] = str(current_version_file(visum))
    except Exception as exc:
        report["instance"]["IO.CurrentVersionFile"] = error_info(exc)
    try:
        report["instance"]["GetPath(2)"] = str(visum.GetPath(2))
    except Exception as exc:
        report["instance"]["GetPath(2)"] = error_info(exc)
    ops = check("OPERATIONS_POSITION_TYPE_ACTIVE", lambda: com.operation_rows(visum))
    suggestions = []
    if ops:
        # Remove live COM proxies before JSON; the returned list remains local.
        report["checks"][-1]["result"] = [{k: v for k, v in r.items() if k != "object"} for r in ops]
        for row in ops:
            params_name = {45: "TripGenerationParameters", 46: "TripDistributionParameters", 101: "PrTAssignmentParameters"}.get(row["type"])
            if not params_name:
                continue
            label = "OP_%d_%s" % (row["no"], params_name)
            def parameters(row=row, prop=params_name):
                obj = com.object_property(row["object"], prop)
                # Keep exact interface evidence even if the expected attribute
                # turns out to differ in this installed Visum release.
                report["catalogs"][label] = {"typeinfo": type_members(obj), "attributes": attribute_catalog(obj)}
                scope_attr = "DSEGSET" if row["type"] == 101 else "DSTRATSET"
                scope = obj.AttValue(scope_attr)
                com.code_set(scope, scope_attr)
                if row["type"] == 101 and row["active"]:
                    suggestions.append({"no": row["no"], "operation_type": 101,
                                        "dseg_object_path": [prop], "dseg_attribute": scope_attr,
                                        "observed_dsegset": str(scope), "approved": False})
                return {"scope_attribute": scope_attr, "scope_value": scope, "python_type": type(scope).__name__}
            check(label, parameters, required=bool(row["active"]))
            if row["type"] == 101:
                for prop in ("PrTEquilibriumAssignmentParameters",):
                    try:
                        obj = com.object_property(row["object"], prop)
                        report["catalogs"][label+"/"+prop] = {"typeinfo": type_members(obj), "attributes": attribute_catalog(obj),
                            "caution": "Stopping tolerances are NOT achieved convergence results"}
                    except Exception as exc:
                        report["catalogs"][label+"/"+prop] = {"unavailable": error_info(exc)}
    report["assignment_binding_proposals_NOT_APPROVED"] = suggestions

    def tg_formula_probe():
        target = [r for r in (ops or []) if r["type"] == 45 and r["active"]]
        if len(target) != 1:
            raise RuntimeError("AMBIGUOUS_ACTIVE_TG_OPERATIONS:count=%d" % len(target))
        params = com.object_property(target[0]["object"], "TripGenerationParameters")
        found = []
        for code in cfg.get("tg_dependency_contract", {}).get("required_dstrata", []):
            d = None
            source = None
            for prefix in ("TripGenerationDStratParameters", "TripGenerationDStratParas", "DStratParameters", "DStratParas"):
                try:
                    pool = getattr(params, prefix)
                except Exception:
                    continue
                if getattr(pool,"_oleobj_",None) is None and (callable(pool)):
                    try:
                        d = pool(code)
                        if d is not None:
                            source = prefix + "(code)"
                    except Exception:
                        pass
                if d is None:
                    for meth in ("ItemByKey", "Item"):
                        try:
                            d = getattr(pool, meth)(code)
                            if d is not None:
                                source = prefix + "." + meth
                                break
                        except Exception:
                            pass
                if d is None:
                    try:
                        for item in com.collection_items(pool, prefix):
                            for idname in ("DEMANDSTRATUMCODE", "CODE"):
                                try:
                                    if str(item.AttValue(idname)).strip().upper()==str(code).strip().upper():
                                        d = item
                                        source = prefix + ".GetAll"
                                        break
                                except Exception:
                                    pass
                            if d is not None:
                                break
                    except Exception:
                        pass
                if d is not None:
                    break
            row = {"dstrat_code": code, "access_source": source or "NOT_READABLE"}
            if d is not None:
                for dest, candidates in (("production",("PRODUCTIONFUNCTION","ProductionFunction","PRODFUNCTION")),
                                         ("attraction",("ATTRACTIONFUNCTION","AttractionFunction","ATTFUNCTION"))):
                    for attr in candidates:
                        try:
                            val = d.AttValue(attr)
                            if val is not None and str(val).strip():
                                row[dest] = str(val)
                                row[dest+"_attribute"] = attr
                                break
                        except Exception:
                            continue
                row["population_token_matches"] = sorted(set(
                    re.findall(r"\[([^\]]*(?:POP|ZP|OBYV)[^\]]*)\]", " ".join(
                        row.get(k,"") for k in ("production","attraction")), flags=re.I)))
            found.append(row)
        readable = sum(1 for x in found if x.get("production") and x.get("attraction"))
        return {"operation_no": target[0]["no"], "rows": found,
                "readable_formula_pairs": readable, "expected_formula_pairs": len(found),
                "passes": readable == len(found),
                "note": "Read-only raw formula evidence. Live formula evidence confirms POP_ZP. Read live POP_ZP zone values; nested formula evidence is a snapshot and must be refreshed after model formula edits."}
    tg_raw = check("TG_LIVE_FORMULAS_POPULATION_PROBE", tg_formula_probe, required=False)
    def _strict_tg_prefeed_contract():
        contract = cfg.get("tg_dependency_contract", {})
        results = []
        failures = []
        if not isinstance(tg_raw, dict) or not tg_raw.get("passes"):
            return {"passes": False, "failures": ["LIVE_TG_READBACK_UNAVAILABLE"], "rows": []}
        bycode = {x.get("dstrat_code"): x for x in tg_raw.get("rows", [])}
        for code, spec in sorted(contract.get("dstrata", {}).items()):
            observed = bycode.get(code, {})
            row = {"dstrat_code": code}
            for role, field in (("production", "production"), ("attraction", "attraction")):
                base = spec.get(role+"_outer_attribute", "")
                additive = spec.get(role+"_additive_attribute", "")
                expected = "["+base+"] + ["+additive+"]" if base and additive else ""
                live = observed.get(field, "")
                ok = bool(expected) and re.sub(r"\s+", "", live).upper() == re.sub(r"\s+", "", expected).upper()
                row[role+"_expected"] = expected
                row[role+"_status"] = "EXACT_MATCH" if ok else "FORMULA_MISMATCH"
                if not ok:
                    failures.append("TG_FORMULA_MISMATCH:"+code+":"+role)
            results.append(row)
        schema = report.get("catalogs", {}).get("Zones", {}).get("attributes", {})
        catalogue = {str(x.get("ID", "")).upper():x for x in schema.get("attributes", [])}
        for attr, value_type in sorted(contract.get("expected_zone_attribute_types", {}).items()):
            found = catalogue.get(attr.upper())
            if not found or found.get("ValueType") != value_type:
                failures.append("TG_ZONE_ATTRIBUTE_TYPE_MISMATCH:"+attr)
        return {"passes": not failures, "failures": failures, "rows": results,
                "checked_real_type_count": len(contract.get("expected_zone_attribute_types", {}))}
    if cfg.get("tg_dependency_contract", {}).get("outer_formula_mode") == "EXACT_FP_PLUS_P09F4_AND_FA_PLUS_A09F4_PER_DSTRAT":
        check("TG_09F4_OUTER_FORMULAS_AND_TYPED_SCHEMA", _strict_tg_prefeed_contract)
    try:
        numbers = cfg.get("expected_zones", 681)
        def zones():
            try:
                rows = list(visum.Net.Zones.GetMultiAttValues("NO", False))
            except TypeError:
                rows = list(visum.Net.Zones.GetMultiAttValues("NO"))
            result = [com.exact_int(v, "Zone.NO") for _, v in rows]
            if result != list(range(1, int(numbers)+1)):
                raise RuntimeError("ZONE_NUMBER_OR_MATRIX_AXIS_ORDER_MISMATCH")
            return result
        zone_nos = check("ZONE_MATRIX_AXIS_ORDER", zones)
        if zone_nos:
            required_attrs = cfg.get("tg_dependency_contract", {}).get("required_zone_attributes", [])
            for attr in required_attrs:
                def read_zone(attr=attr):
                    values = com.indexed_zone_values(visum, attr, zone_nos)
                    return {"count": len(values), "min": min(values), "max": max(values),
                            "sum": float(sum(values)), "nonzero_count": sum(x != 0 for x in values),
                            "numeric": True}
                check("ZONE_ATTRIBUTE:"+attr, read_zone)
    except Exception as exc:
        check("ZONE_AUDIT", lambda: (_ for _ in ()).throw(exc))
    if zone_nos and cfg.get("zahr"):
        def _live_foreign_population_scope():
            zcfg = cfg["zahr"]
            mask = com.indexed_zone_values(visum, zcfg.get("domestic_mask_attr", "NOT_ZAHR"), zone_nos)
            neigh = com.indexed_zone_values(visum, zcfg.get("neighbour_attr", "ZAHR_SUSED"), zone_nos)
            pop = com.indexed_zone_values(visum, zcfg.get("population_attr", "POP_ZP"), zone_nos)
            domestic = sum(m >= float(zcfg.get("domestic_threshold", 0.5)) for m in mask)
            neighbouring = sum(m < float(zcfg.get("domestic_threshold", 0.5)) and n > 0 for m, n in zip(mask, neigh))
            effective = [int(z) for z, m, n, p in zip(zone_nos, mask, neigh, pop)
                         if m < float(zcfg.get("domestic_threshold", 0.5)) and n > 0 and p > 0]
            if not effective:
                raise RuntimeError("ZERO_FOREIGN_GENERATION_POP_ZP_SUPPORT")
            return {"population_attribute": zcfg.get("population_attr", "POP_ZP"),
                    "domestic_zones": domestic, "foreign_neighbouring_zones": neighbouring,
                    "foreign_effective_population_zones": len(effective),
                    "effective_zone_nos": effective,
                    "classification": "ZAHR_SUSED>0 AND POP_ZP>0; NO hardcoded required count"}
        check("ZONE_FOREIGN_POPULATION_ACTUATOR_SCOPE", _live_foreign_population_scope)
    ds = check("DEMAND_SEGMENTS_GETALL", lambda: com.collection_items(visum.Net.DemandSegments))
    required_ds = cfg.get("supply", {}).get("passenger_dsegs", []) + cfg.get("supply", {}).get("freight_dsegs", [])
    matrix_nos = set(cfg.get("supply", {}).get("component_matrix_nos", []))
    if ds is not None:
        dmap = {}
        for obj in ds:
            try:
                code = str(obj.AttValue("CODE"))
                if code in dmap:
                    raise RuntimeError("DUPLICATE_DSEG_CODE:"+code)
                dmap[code] = obj
            except Exception as exc:
                check("DSEG_IDENTITY", lambda: (_ for _ in ()).throw(exc))
        for code in required_ds:
            def read_binding(code=code):
                mat = com.object_property(dmap[code], "ODMatrix")
                no = com.exact_int(mat.AttValue("NO"), "Matrix.NO")
                matrix_nos.add(no)
                return {"code": code, "matrix_no": no, "matrix_metadata": read_attributes(mat, ["CODE", "MATRIXTYPE", "DATASOURCETYPE", "OBJECTTYPEREF", "NUMROWS", "NUMCOLS", "MATRIXUNIT", "SUM"])}
            check("DSEG_ODMATRIX:"+code, read_binding)
    matrices = check("MATRIX_CATALOG", lambda: com.collection_items(visum.Net.Matrices))
    if matrices is not None:
        byno, bycode = {}, {}
        for mat in matrices:
            try:
                no = com.exact_int(mat.AttValue("NO"))
                code = str(mat.AttValue("CODE"))
                byno[no] = mat
                bycode.setdefault(code, []).append(no)
            except Exception:
                continue
        def distance():
            found = bycode.get("R1_OSRM_DIST_KM", [])
            if len(found) != 1:
                raise RuntimeError("REQUIRED_UNIQUE_DISTANCE_CODE:R1_OSRM_DIST_KM candidates=%r" % found)
            matrix_nos.add(found[0])
            return {"matrix_no": found[0], "purpose": "11D DIST_KM classification; NOT Matrix(9001) time band authority"}
        check("DISTANCE_MATRIX_AUTHORITY", distance)
        for no in sorted(matrix_nos):
            def shape(no=no):
                mat = byno[no]
                values = mat.GetValues()
                np = importlib.import_module("numpy")
                a = np.asarray(values, dtype=float)
                expected = int(cfg.get("expected_zones", 681))
                if a.shape != (expected, expected) or not np.isfinite(a).all() or np.any(a < 0):
                    raise RuntimeError("MATRIX_SHAPE_OR_FINITE_NONNEGATIVE_GATE:%d" % no)
                return {"no": no, "shape": list(a.shape), "sum": float(a.sum()), "metadata": read_attributes(mat, ["MATRIXTYPE", "DATASOURCETYPE", "OBJECTTYPEREF", "MATRIXUNIT"])}
            check("MATRIX_VALUES:%s" % no, shape)
    links = check("LINKS_GETALL", lambda: com.collection_items(visum.Net.Links))
    directed_link_keys = set()
    directed_link_tsys = {}
    if links:
        attrs = ["NO", "FROMNODENO", "TONODENO", "ADDVAL1", "T0_PRTSYS(C)", "CAPPRT", "LENGTH", "TYPENO", "TSYSSET"]
        link_indices = set()
        def link_schema():
            # One bulk call per attribute; do not use 9 x 8594 COM roundtrips.
            columns = {}
            for attr in attrs:
                rows = list(visum.Net.Links.GetMultiAttValues(attr, False))
                col = {}
                for index, value in rows:
                    index = com.exact_int(index, "link container index")
                    if index in col:
                        raise RuntimeError("DUPLICATE_LINK_ATTRIBUTE_INDEX:"+attr)
                    col[index] = value
                if len(col) != len(links):
                    raise RuntimeError("LINK_ATTRIBUTE_COVERAGE:"+attr)
                if columns and set(col) != set(columns[attrs[0]]):
                    raise RuntimeError("LINK_ATTRIBUTE_INDEX_MISMATCH:"+attr)
                columns[attr] = col
            link_indices.update(columns[attrs[0]])
            keys = set()
            for index in sorted(link_indices):
                values = {a: columns[a][index] for a in attrs}
                key = tuple(com.exact_int(values[a], a) for a in attrs[:3])
                if key in keys:
                    raise RuntimeError("DUPLICATE_DIRECTED_LINK")
                keys.add(key)
                directed_link_keys.add(key)
                raw_tsys = values["TSYSSET"]
                directed_link_tsys[key] = (com.code_set(raw_tsys, "TSYSSET") if isinstance(raw_tsys,str) and raw_tsys.strip() else set())
                for attr in ("ADDVAL1", "T0_PRTSYS(C)", "CAPPRT", "LENGTH"):
                    com.finite_float(values[attr], attr)
                com.exact_int(values["TYPENO"], "TYPENO")
                if not isinstance(values["TSYSSET"], str):
                    raise RuntimeError("NONSTRING_LINK_TSYSSET")
            return {"count": len(links), "bulk_calls": len(attrs),
                    "sample_attributes": read_attributes(links[0], attrs)}
        check("ALL_DIRECTIONAL_LINK_ATTRIBUTES", link_schema)
        for code in cfg.get("supply", {}).get("passenger_dsegs", []):
            attr = "VOLVEH_DSEG(%s,AP)" % code
            def volumes(attr=attr):
                # Bulk read avoids 100k+ tiny COM roundtrips on the real R1 net.
                raw = list(visum.Net.Links.GetMultiAttValues(attr, False))
                if len(raw) != len(links):
                    raise RuntimeError("VOLUME_ATTRIBUTE_COVERAGE:"+attr)
                indices = [com.exact_int(k) for k,_ in raw]
                if len(set(indices)) != len(indices):
                    raise RuntimeError("DUPLICATE_VOLUME_ARRAY_INDEX:"+attr)
                if link_indices and set(indices) != link_indices:
                    raise RuntimeError("MODEL_VOLUME_INDEX_MISMATCH:"+attr)
                values = [com.finite_float(v, attr) for _,v in raw]
                if any(v < 0 for v in values):
                    raise RuntimeError("NEGATIVE_MODEL_VOLUME:"+attr)
                return {"rows": len(values), "sum_link_volumes_not_trip_total": sum(values),
                        "zero_rows": sum(v == 0 for v in values), "zero_is_valid": True}
            check("REQUIRED_PASSENGER_VOLUME:"+code, volumes)
    # Exact caller-supplied approved observations, not all historical 920xxx.
    observations = cfg.get("api_approved_observations", [])
    if observations:
        def counts():
            coll = visum.Net.CountLocations
            seen = set()
            for row in observations:
                no = int(row["no"])
                obj = coll.ItemByKey(no)
                if com.exact_int(obj.AttValue("NO")) != no or no in seen:
                    raise RuntimeError("COUNTLOCATION_IDENTITY:%d" % no)
                seen.add(no)
                observed = com.finite_float(obj.AttValue("R1_OBS_RPDI"), "R1_OBS_RPDI")
                if abs(observed-float(row["observed"])) > 1e-6:
                    raise RuntimeError("R1_OBS_RPDI_AUTHORITY_CHANGED:%d" % no)
                active_flag = com.active_bool(obj.AttValue("R1_ACTIVE"))
                if not active_flag:
                    raise RuntimeError("COUNTLOCATION_APPROVED_PROFILE_INACTIVE:%d" % no)
                if str(obj.AttValue("R1_ROLE")).strip().upper() != str(row["role"]).upper():
                    raise RuntimeError("COUNTLOCATION_ROLE_CHANGED:%d" % no)
                # Production 12D needs the same exact identity/scope fields;
                # detect them here rather than discovering the next COM error
                # only after the entire assignment is executed.
                for live_name, authority_name in (("CODE", "countlocation_code"),
                                                  ("R1_OBS_ID", "profile_id"),
                                                  ("R1_OBS_BASIS", "period_basis"),
                                                  ("R1_OBS_SCOPE", "observed_scope")):
                    if authority_name in row:
                        live = str(obj.AttValue(live_name)).strip()
                        if live != str(row[authority_name]).strip():
                            raise RuntimeError("COUNTLOCATION_%s_CHANGED:%d:%s!=%s" %
                                               (live_name, no,live,row[authority_name]))
                if "weight" in row:
                    weight = com.finite_float(obj.AttValue("R1_WEIGHT"), "R1_WEIGHT")
                    if abs(weight-float(row["weight"])) > 1e-8:
                        raise RuntimeError("COUNTLOCATION_WEIGHT_CHANGED:%d" % no)
                if "edge_key" in row:
                    key = tuple(com.exact_int(obj.AttValue(a), a) for a in ("LINKNO","FROMNODENO","TONODENO"))
                    if key != tuple(row["edge_key"]):
                        raise RuntimeError("COUNTLOCATION_EDGE_CHANGED:%d" % no)
                    if key not in directed_link_keys:
                        raise RuntimeError("COUNTLOCATION_DIRECTIONAL_LINK_MISSING:%d:%r" % (no,key))
                    if "C" not in directed_link_tsys.get(key,set()):
                        raise RuntimeError("COUNTLOCATION_LINK_DISALLOWS_C:%d:%r" % (no,key))
                if row.get("direction") == "BOTH":
                    reverse = (int(row["edge_key"][0]), int(row["edge_key"][2]), int(row["edge_key"][1]))
                    if reverse not in directed_link_keys:
                        raise RuntimeError("COUNTLOCATION_BOTH_REVERSE_LINK_MISSING:%d:%r" % (no, reverse))
                    if "C" not in directed_link_tsys.get(reverse,set()):
                        raise RuntimeError("COUNTLOCATION_BOTH_REVERSE_DISALLOWS_C:%d:%r" % (no,reverse))
            # 12D consumes all 920001..920444 present plus ACTIVE city 912xxx.
            # Other 912xxx can remain in the network provided they are inactive.
            used = set()
            for obj in com.collection_items(coll, "CountLocations"):
                identifier = com.exact_int(obj.AttValue("NO"), "COUNTLOCATION.NO")
                if 920001 <= identifier <= 920444:
                    used.add(identifier)
                elif 912001 <= identifier <= 912142:
                    if com.active_bool(obj.AttValue("R1_ACTIVE")):
                        used.add(identifier)
            if used != seen:
                raise RuntimeError("12D_LIVE_COUNTLOCATION_SCOPE_MISMATCH:missing=%r unexpected=%r" %
                                   (sorted(seen - used), sorted(used - seen)))
            return {"approved_count": len(seen), "source": "R1_OBS_RPDI already converted; no reconversion",
                    "both_direction_source": "FROZEN_CITY90_AUTHORITY_PLUS_LIVE_REVERSE_EDGE",
                    "zero_model_flow_allowed": True}
        check("APPROVED_COUNTLOCATION_RPDI_AND_ROLE", counts)
    def getlists():
        try:
            return visum.Workbench.Lists
        except Exception:
            return visum.Lists
    lists = check("WORKBENCH_LISTS", getlists)
    if lists is not None:
        for kind in ("CreatePrTPathList", "CreatePrTPathLinkList", "CreatePrTAssQualityList"):
            def probe_list(kind=kind):
                obj = com.object_property(lists, kind)
                meta = {"typeinfo": type_members(obj), "attributes": attribute_catalog(obj)}
                report["catalogs"][kind] = meta
                if kind != "CreatePrTAssQualityList":
                    dseg = cfg.get("supply", {}).get("passenger_dsegs", ["NATIVE_CW"])[0]
                    obj.SetObjects(0, dseg, com.ALL_ROUTES)
                    columns = (["OrigZoneNo", "DestZoneNo", "Index", "Vol(AP)"] if kind == "CreatePrTPathList"
                               else ["OrigZoneNo", "DestZoneNo", "PathIndex", "Index", "LinkNo", "FromNodeNo", "ToNodeNo"])
                    for name in columns:
                        obj.AddColumn(name)
                    sample = bounded_list_sample(
                        obj, limit=80 if kind == "CreatePrTPathLinkList" else 5,
                        retry_policy=cfg.get("com_resilience"))
                    if sample.get("status") != "READ_BOUNDED":
                        raise RuntimeError("REQUIRED_BOUNDED_LIST_SAMPLE_UNAVAILABLE:"+kind)
                    if kind == "CreatePrTPathLinkList":
                        raw = sample.get("rows", [])
                        if raw:
                            # A five-row sample may end mid-route. Parsing just
                            # the first valid child suffices to prove the host
                            # uses the supported (hierarchical or flat) layout.
                            norm = list(com.normalized_prt_pathlink_rows(raw, columns))
                            if not norm:
                                raise RuntimeError("PATHLINK_SAMPLE_HAS_NO_REAL_LINKS")
                            sample["normalized_child_links"] = len(norm)
                            sample["sample_layout"] = ("PARENT_CHILD" if any(
                                x and x[0] not in (None, "") and x[3] in (None, "") for x in raw)
                                else "FLAT")
                    return {"required_columns": columns, "dseg_probe": dseg, "sample": sample,
                            "scope": "Schema/sample only; not full path coverage"}
                quality = {"factory": "READ", "gap_binding": "UNAPPROVED: observed achieved GAP must be matched to the final assignment iteration"}
                try:
                    for name in ("DSEGCODE", "ITERATION", "GAP"):
                        obj.AddColumn(name)
                    quality["bounded_quality_sample"] = bounded_list_sample(
                        obj, limit=10, retry_policy=cfg.get("com_resilience"))
                except Exception as exc:
                    quality["bounded_quality_sample"] = {"status":"NOT_READABLE", "error":error_info(exc)}
                return quality
            check("LIST_INTERFACE:"+kind, probe_list)
    for label, fn in extra_checks:
        check(label, fn)
    failed = [r["check"] for r in report["checks"] if r["required"] and r["status"] == "FAIL"]
    report["required_failures"] = failed
    report["status"] = "LIVE_API_REVIEW_REQUIRED" if not failed else "LIVE_API_BLOCKERS_FOUND"
    report["finished"] = datetime.now().astimezone().isoformat()
    report["limits"] = ["No assignment or calibration run", "No automatic approval of operation/gap bindings", "No full path-coverage/parity test", "Matrix units and formula semantics require model-authority confirmation"]
    save()
    (folder / "00_FINAL_STATUS.txt").write_text(report["status"] + "\n" + "\n".join(failed), encoding="utf-8")
    return report
