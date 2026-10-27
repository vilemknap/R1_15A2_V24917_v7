# -*- coding: utf-8 -*-
"""V24917 reduced CountLocation roster (user-selected calibration profiles).

The sealed V24916 runtime binds exactly 488 CountLocations (362 CSD + 126 CITY).
This module replaces that roster by authorities/R1_PROFILE_ROSTER_V24917.json,
built by tools/build_profile_roster_v24917.py from a Visum CountLocation export.
Every roster row is copied unchanged from the 488 authority (observed RPDI, edge,
weight); only membership changes.  Sealed V24916 files stay byte-identical: the
patches are applied in memory.

install_static()  - before the parent launcher's preflight (prepare time)
install_gate()    - after the parent runtime installed its PROFILE488 gate adapter
apply_cfg()/strip_cfg() - config delta used by r1_15a2_runtime_delta_v24917
"""
from __future__ import annotations

import ast
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping

HERE = Path(__file__).resolve().parent
META_REL = "authorities/R1_PROFILE_ROSTER_V24917.json"
SCHEMA = "R1_15A2_V24917_PROFILE_ROSTER_V1"
CFG_KEY = "v24917_profile_roster"
GATE488 = {"expected_12d_rows": 488, "expected_calibration_rows": 488, "expected_validation_rows": 0}
_STATE: Dict[str, Any] = {}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows(path: Path):
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def enabled(root: Path = HERE) -> bool:
    if os.environ.get("R1_PROFILE_ROSTER_DISABLE", "").strip().lower() in ("1", "true", "yes", "ano"):
        return False
    return (Path(root) / META_REL).is_file()


def load_meta(root: Path = HERE) -> Dict[str, Any]:
    root = Path(root)
    meta = json.loads((root / META_REL).read_text(encoding="utf-8"))
    if meta.get("schema") != SCHEMA:
        raise RuntimeError("V24917_ROSTER_SCHEMA")
    for rel, key in (("csd_csv", "csd_sha256"), ("city_csv", "city_sha256"),
                     ("source_xlsx", "source_xlsx_sha256"), ("helper", "helper_sha256")):
        p = root / meta[rel]
        if not p.is_file() or _sha(p) != meta[key]:
            raise RuntimeError("V24917_ROSTER_FILE_MISMATCH:" + meta[rel])
    csd, city = _rows(root / meta["csd_csv"]), _rows(root / meta["city_csv"])
    nos = sorted(int(r["countlocation_no"]) for r in csd + city)
    if (len(csd), len(city), len(nos)) != (meta["csd_rows"], meta["city_rows"], meta["rows"]):
        raise RuntimeError("V24917_ROSTER_COUNT_MISMATCH")
    if nos != sorted(meta["countlocation_nos"]) or len(set(nos)) != len(nos):
        raise RuntimeError("V24917_ROSTER_NOS_MISMATCH")
    if any(str(r.get("role", "")).upper() != "CALIBRATION" for r in csd + city):
        raise RuntimeError("V24917_ROSTER_NONCALIBRATION_ROW")
    if meta["calibration"] != meta["rows"] or meta["validation"] != 0:
        raise RuntimeError("V24917_ROSTER_ROLE_COUNTS")
    return meta


def gate_of(meta: Mapping[str, Any]) -> Dict[str, int]:
    return {"expected_12d_rows": int(meta["rows"]),
            "expected_calibration_rows": int(meta["calibration"]),
            "expected_validation_rows": int(meta["validation"])}


def section(meta: Mapping[str, Any]) -> Dict[str, Any]:
    return {"schema": SCHEMA, "enabled": True,
            "rows": meta["rows"], "csd_rows": meta["csd_rows"], "city_rows": meta["city_rows"],
            "csd_sha256": meta["csd_sha256"], "city_sha256": meta["city_sha256"],
            "source_xlsx_sha256": meta["source_xlsx_sha256"], "helper_sha256": meta["helper_sha256"],
            "observed_sum": meta.get("observed_sum"),
            "weights": "UNCHANGED_FROM_PARENT_488_AUTHORITY",
            "replaces": GATE488}


# ------------------------------------------------------------------ config
def apply_cfg(cfg: Dict[str, Any], root: Path = HERE) -> Dict[str, Any]:
    if not enabled(root):
        return cfg
    meta = load_meta(root)
    cfg.update(gate_of(meta))
    cfg[CFG_KEY] = section(meta)
    return cfg


def strip_cfg(child: Mapping[str, Any], root: Path = HERE) -> Dict[str, Any]:
    """Child config with the roster delta removed (for the inherited V24916 validator)."""
    out = {k: v for k, v in dict(child).items() if k != CFG_KEY}
    sec = child.get(CFG_KEY)
    if sec:
        meta = load_meta(root)
        if dict(sec) != section(meta):
            raise RuntimeError("V24917_ROSTER_CFG_SECTION_MISMATCH")
        for k, v in gate_of(meta).items():
            if int(child.get(k, -1)) != v:
                raise RuntimeError("V24917_ROSTER_CFG_GATE_MISMATCH:" + k)
        out.update(GATE488)
    return out


# ------------------------------------------------------------------ static patches
def _patch_preflight(meta, root):
    import r1_15a2_fresh_baseline_live_preflight_v24916p2c as pf
    pf.PROFILE488_CSD_REL = meta["csd_csv"]
    pf.PROFILE488_CITY_REL = meta["city_csv"]
    pf.PROFILE488_XLSX_REL = meta["source_xlsx"]
    pf.PROFILE488_CSD_SHA256 = meta["csd_sha256"]
    pf.PROFILE488_CITY_SHA256 = meta["city_sha256"]
    pf.PROFILE488_XLSX_SHA256 = meta["source_xlsx_sha256"]

    def _profile488_authority(root_: Path) -> Dict[str, Any]:
        m = load_meta(Path(root_))
        csd = pf._read_csv(Path(root_) / m["csd_csv"])
        city = pf._read_csv(Path(root_) / m["city_csv"])
        return {"rows": m["rows"], "calibration": m["calibration"], "validation": 0,
                "csd_rows": len(csd), "city_rows": len(city),
                "source_xlsx": m["source_xlsx"], "source_xlsx_sha256": m["source_xlsx_sha256"],
                "csd_csv": m["csd_csv"], "csd_sha256": m["csd_sha256"],
                "city_csv": m["city_csv"], "city_sha256": m["city_sha256"],
                "roster": SCHEMA,
                "zero_observation_rows": sum(1 for r in csd + city
                                             if float(r.get("observed_passenger_cars_O") or 0.0) <= 0.0)}

    def _live_profile488_compatibility(visum, root_, cfg):
        m = load_meta(Path(root_))
        rows = pf._read_csv(Path(root_) / m["csd_csv"]) + pf._read_csv(Path(root_) / m["city_csv"])
        coll = visum.Net.CountLocations
        checked, errors = [], []
        for row in rows:
            no = pf._as_int(row["countlocation_no"])
            try:
                obj = pf._call(lambda no=no: coll.ItemByKey(no), "CountLocations.ItemByKey(%d)" % no, cfg)
                got = pf._as_int(pf._att(obj, "NO"))
                obs = float(pf._att(obj, "R1_OBS_RPDI"))
                edge = tuple(pf._as_int(pf._att(obj, a)) for a in ("LINKNO", "FROMNODENO", "TONODENO"))
                exp_edge = tuple(pf._as_int(row[k]) for k in
                                 ("current_link_no", "current_from_node_no", "current_to_node_no"))
                if got != no:
                    raise RuntimeError("NO_READBACK:%s!=%s" % (got, no))
                if abs(obs - float(row.get("observed_passenger_cars_O") or 0.0)) > 1.0e-6:
                    raise RuntimeError("OBS:%s!=%s" % (obs, row.get("observed_passenger_cars_O")))
                if edge != exp_edge:
                    raise RuntimeError("EDGE:%s!=%s" % (edge, exp_edge))
                checked.append(no)
            except Exception as exc:
                errors.append("%s:%s:%s" % (no, type(exc).__name__, exc))
        if errors:
            raise RuntimeError("V24917_ROSTER_LIVE_MODEL_INCOMPATIBLE:%d:%s" % (len(errors), ";".join(errors[:12])))
        if len(set(checked)) != m["rows"]:
            raise RuntimeError("V24917_ROSTER_LIVE_MODEL_COUNT_MISMATCH")
        return {"schema": "R1_15A2_V24917_ROSTER_LIVE_COMPATIBILITY_V1", "passes": True,
                "checked_rows": len(checked), "calibration_rows": m["rows"], "validation_rows": 0,
                "source_model_mutated": False, "roster": SCHEMA,
                "other_countlocations_in_model_ignored": True}

    pf._profile488_authority = _profile488_authority
    pf._live_profile488_compatibility = _live_profile488_compatibility


def _patch_fresh0(meta):
    import r1_15a2_fresh0_shortroot_parent_v24916 as f0
    f0.CURRENT_12D_HELPER = Path(meta["helper"]).name
    f0.CURRENT_CSD_AUTH_REL = meta["csd_csv"]
    f0.CURRENT_CITY_AUTH_REL = meta["city_csv"]
    f0.CURRENT_COUNTLOCATION_SOURCE_REL = meta["source_xlsx"]
    f0.CURRENT_CSD_AUTH_SHA256 = meta["csd_sha256"]
    f0.CURRENT_CITY_AUTH_SHA256 = meta["city_sha256"]
    f0.CURRENT_COUNTLOCATION_SOURCE_SHA256 = meta["source_xlsx_sha256"]
    f0.CURRENT_PROFILE_COUNT = int(meta["rows"])


def _patch_diagfast(meta, root):
    try:
        import r1_15a2_diagfast_v1 as df
    except ImportError:
        return {"installed": False}
    name = Path(meta["helper"]).name
    df.HELPERS["12D"] = name
    original = getattr(df.reference_namespace, "_v24917_original", df.reference_namespace)

    def reference_namespace(kind, workspace, visum=None, print_fn=print):
        if kind != "12D" or df.HELPERS.get("12D") != name:
            return original(kind, workspace, visum, print_fn)
        path = df.ROOT / "helpers" / name
        if df.digest_file(path) != load_meta(Path(root))["helper_sha256"]:
            raise df.DiagFastError("DIAGFAST_REFERENCE_HASH_MISMATCH:" + name)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        final = tree.body[-1]
        if not (isinstance(final, ast.Try) and len(final.body) == 1
                and isinstance(final.body[0], ast.Expr)
                and isinstance(final.body[0].value, ast.Call)
                and isinstance(final.body[0].value.func, ast.Name)
                and final.body[0].value.func.id == "main"):
            raise df.DiagFastError("DIAGFAST_REFERENCE_BOOTSTRAP_CONTRACT_CHANGED")
        tree.body.pop()
        entry = ast.parse("def _diagfast_reference_entry():\n    pass\n").body[0]
        entry.body = [final]
        entry.lineno = final.lineno
        entry.end_lineno = final.end_lineno
        tree.body.append(entry)
        ast.fix_missing_locations(tree)
        env = {"__name__": "_r1_diagfast_reference_12D", "__file__": str(Path(workspace) / name),
               "Visum": visum, "print": print_fn}
        exec(compile(tree, str(path), "exec"), env, env)
        return env

    reference_namespace._v24917_original = original
    df.reference_namespace = reference_namespace
    return {"installed": True, "helper": name}


class _RosterComProxy:
    """com_compat proxy for r1_15a2_live_api_audit only: CountLocations outside the
    roster are invisible to its 12D scope check (the roster 12D helper ignores them)."""

    def __init__(self, base, nos):
        self._base = base
        self._nos = frozenset(int(x) for x in nos)

    def __getattr__(self, name):
        return getattr(self._base, name)

    def collection_items(self, coll, label="", *args, **kwargs):
        items = self._base.collection_items(coll, label, *args, **kwargs)
        if str(label) != "CountLocations":
            return items
        out = []
        for obj in items:
            try:
                no = int(float(obj.AttValue("NO")))
            except Exception:
                out.append(obj)
                continue
            if no in self._nos:
                out.append(obj)
        return out


def _patch_live_api_audit(meta):
    import r1_15a2_live_api_audit as audit
    base = getattr(audit.com, "_base", audit.com)
    audit.com = _RosterComProxy(base, meta["countlocation_nos"])
    return {"installed": True, "scope": "r1_15a2_live_api_audit.com.collection_items(CountLocations)"}


def install_static(root: Path = HERE, print_fn=print) -> Dict[str, Any]:
    if _STATE.get("static"):
        return _STATE["static"]
    if not enabled(root):
        _STATE["static"] = {"installed": False, "reason": "NO_ROSTER_OR_DISABLED"}
        return _STATE["static"]
    meta = load_meta(root)
    os.environ["R1_PROFILE_ROSTER_AUTH_DIR"] = str(Path(root) / "authorities")
    _patch_preflight(meta, root)
    _patch_fresh0(meta)
    diag = _patch_diagfast(meta, root)
    audit = _patch_live_api_audit(meta)
    status = {"live_api_audit": audit,"installed": True, "schema": SCHEMA, "rows": meta["rows"],
              "csd_rows": meta["csd_rows"], "city_rows": meta["city_rows"],
              "helper": meta["helper"], "diagfast": diag}
    print_fn("R1 V24917 PROFILE ROSTER: %d profiles (%d CSD + %d CITY), helper %s"
             % (meta["rows"], meta["csd_rows"], meta["city_rows"], Path(meta["helper"]).name))
    _STATE["static"] = status
    return status


# ------------------------------------------------------------------ 11D/12D cross gate
def _assess_wrapper(inner, meta):
    roster = {"rows": meta["rows"], "calibration": meta["calibration"], "validation": 0}

    def wrapped(meta11, d12, cfg):
        expected = {"rows": int(cfg.get("expected_12d_rows", -1)),
                    "calibration": int(cfg.get("expected_calibration_rows", -1)),
                    "validation": int(cfg.get("expected_validation_rows", -1))}
        if expected != roster:
            return inner(meta11, d12, cfg)
        actual = dict((d12 or {}).get("row_gate", {})) if isinstance(d12, dict) else {}
        mismatch = [k for k, v in roster.items() if actual.get(k) != v]
        d12c = copy.deepcopy(d12) if isinstance(d12, dict) else d12
        if isinstance(d12c, dict):
            d12c["row_gate"] = {"rows": 488, "calibration": 488, "validation": 0}
        cfgc = dict(cfg)
        cfgc.update(GATE488)
        dec = copy.deepcopy(inner(meta11, d12c, cfgc))
        dec["mandatory_12d_row_gate"] = actual
        dec["active_12d_row_gate_expected"] = dict(roster)
        dec["v24917_profile_roster"] = SCHEMA
        notices = [("V24917_ROSTER_12D_GATE_%d_%d_0_VALIDATED" % (roster["rows"], roster["calibration"]))
                   if x == "PROFILE488_12D_GATE_488_488_0_VALIDATED" else x
                   for x in (dec.get("notices") or [])]
        failures = [f for f in (dec.get("failures") or [])
                    if not str(f).startswith("PROFILE488_12D_ACTIVE_AUTHORITY_NOT_PROVEN:")]
        failures += ["V24917_ROSTER_12D_ACTIVE_AUTHORITY_NOT_PROVEN:" + k for k in mismatch]
        dec["notices"], dec["failures"] = notices, failures
        dec["passes"] = not failures
        dec["status"] = ("PASS_IDP_ONLY_WITH_LEGACY_11D_ADVISORIES" if not failures and notices else
                         "PASS_ATOMIC_IDP_READ_ONLY" if not failures else "FAIL_IDP_OR_READ_ONLY")
        return dec

    wrapped._v24917_roster_gate = True
    return wrapped


def install_gate(root: Path = HERE) -> Dict[str, Any]:
    if not enabled(root):
        return {"installed": False}
    import r1_15a2_runtime_v1 as rt
    import r1_15a2_profile488_gatefix_v24916p2c as gatefix
    gatefix.activate_runtime_gate_overlay()
    if getattr(rt.assess_11d_idp_gate, "_v24917_roster_gate", False):
        return {"installed": True, "status": "ALREADY_ACTIVE"}
    rt.assess_11d_idp_gate = _assess_wrapper(rt.assess_11d_idp_gate, load_meta(root))
    return {"installed": True, "status": "ACTIVE"}


__all__ = ["SCHEMA", "CFG_KEY", "enabled", "load_meta", "apply_cfg", "strip_cfg",
           "install_static", "install_gate"]
