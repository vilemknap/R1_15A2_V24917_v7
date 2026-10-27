# -*- coding: utf-8 -*-
"""R1 VDF EDIT - change volume-delay function parameters in the open Visum model.

Default change (R1 VDF diagnostic 2026-10-25):
    link VDF 7 "I. - 3/4 pruh" (link types 8, 9, 20):  CAPACITYFACTOR 1.0 -> 1.8
    (BPR_A 0.35 and BPR_B 3.5 unchanged)

Usage in Visum: open the .ver -> Scripts -> Run script file -> R1_VDF_EDIT.py
  * DRY_RUN = True  -> only checks and shows what would change, nothing is written
  * DRY_RUN = False -> writes the change, reads it back, verifies that NOTHING else in
                       the procedure functions changed; on any mismatch the original
                       procedure parameters are restored.
The .ver is NOT saved - after PASS use File -> Save version as (new name).

Output next to the .ver (else next to this script, else Documents):
  R1_VDF_EDIT\\<timestamp>\\00_STATUS.txt, 01_CHANGES.csv,
  PROCEDURES_BEFORE.xml (backup), PROCEDURES_AFTER.xml
"""
from __future__ import annotations

import csv
import datetime
import math
import os
import re
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

# ----------------------------------------------------------------- settings
DRY_RUN = False
SCOPE = "LINKVDFUNCTIONSPARAMETERS"          # link VD functions
CHANGES = {7: {"CAPACITYFACTOR": 1.8}}         # VDF no -> {XML attribute: new value}
EXPECTED_BEFORE = {7: {"VDFUNCTIONTYPE": "BPR", "BPR_A": 0.35, "BPR_B": 3.5, "CAPACITYFACTOR": 1.0}}
SHOW_MESSAGE_BOX = True
TOL = 1e-9


# ------------------------------------------------------------------ helpers
def _here():
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path(os.getcwd())


def _visum():
    g = globals()
    if "Visum" in g:
        return g["Visum"]
    import __main__
    if hasattr(__main__, "Visum"):
        return __main__.Visum
    raise RuntimeError("Visum object not found - run the script from inside Visum")


def _num(v):
    try:
        x = float(str(v).replace(",", "."))
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _same(a, b):
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) <= TOL * max(1.0, abs(na), abs(nb))
    return str(a).strip() == str(b).strip()


def _fmt(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(v) if isinstance(v, float) else str(v)


# ------------------------------------------------------- procedure XML I/O
def export_procedures(visum, path):
    """Save the procedure parameters (operations + functions) as XML."""
    path = str(path)
    errors = []
    for name, args in (("SaveXml", (path,)), ("Save", (path,))):
        fn = getattr(visum.Procedures, name, None)
        if fn is None:
            continue
        try:
            fn(*args)
            if Path(path).is_file() and Path(path).stat().st_size > 0:
                return name
        except Exception as exc:
            errors.append("%s:%r" % (name, exc))
    raise RuntimeError("Procedure parameters could not be exported: " + "; ".join(errors))


def import_procedures(visum, path, functions_only=True):
    """Load procedure parameters from XML (functions only when the API allows it)."""
    path = str(path)
    errors = []
    attempts = []
    if functions_only:
        # OpenXmlWithOptions(file, ReadOperations, ReadFunctions, ImportMode)
        attempts += [("OpenXmlWithOptions", (path, False, True, 0)),
                     ("OpenXmlWithOptions", (path, False, True))]
    attempts += [("OpenXml", (path,)), ("Open", (path,))]
    for name, args in attempts:
        fn = getattr(visum.Procedures, name, None)
        if fn is None:
            continue
        try:
            fn(*args)
            return "%s%s" % (name, "(functions only)" if len(args) > 1 else "(full XML)")
        except Exception as exc:
            errors.append("%s%d:%r" % (name, len(args), exc))
    raise RuntimeError("Procedure parameters could not be imported: " + "; ".join(errors))


def vdf_table(xml_text):
    """{(scope, no): {attr: value}} for every VDFUNCTION element."""
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    out = {}
    for scope_el in root.iter():
        tag = scope_el.tag.upper()
        if not tag.endswith("VDFUNCTIONSPARAMETERS"):
            continue
        for el in scope_el:
            if el.tag.upper() == "VDFUNCTION":
                out[(tag, int(float(el.attrib.get("NO", "0"))))] = dict(el.attrib)
    return out


def functions_signature(xml_text):
    """Every element below <FUNCTIONS> with its attributes (order-independent compare)."""
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    fn = None
    for el in root.iter():
        if el.tag.upper() == "FUNCTIONS":
            fn = el
            break
    rows = []
    if fn is None:
        return rows

    def walk(el, path):
        p = path + "/" + el.tag.upper()
        rows.append((p, tuple(sorted(el.attrib.items()))))
        for ch in el:
            walk(ch, p)
    walk(fn, "")
    return rows


def edit_xml_text(xml_text, scope, changes):
    """Change attribute values of <VDFUNCTION NO=n> inside <scope>, byte-preserving elsewhere."""
    m = re.search(r"<%s\b[^>]*>(.*?)</%s>" % (scope, scope), xml_text, flags=re.S | re.I)
    if not m:
        raise RuntimeError("XML section %s not found" % scope)
    block = m.group(1)
    new_block = block
    for no, attrs in changes.items():
        tag_re = re.compile(r"<VDFUNCTION\b[^>]*\bNO=\"%d\"[^>]*/?>" % int(no), flags=re.I)
        tags = tag_re.findall(new_block)
        if len(tags) != 1:
            raise RuntimeError("VDFUNCTION NO=%d found %d times in %s" % (no, len(tags), scope))
        tag = tags[0]
        new_tag = tag
        for attr, value in attrs.items():
            a_re = re.compile(r"(\b%s=\")([^\"]*)(\")" % re.escape(attr))
            if not a_re.search(new_tag):
                raise RuntimeError("Attribute %s missing on VDFUNCTION NO=%d" % (attr, no))
            new_tag = a_re.sub(lambda mm: mm.group(1) + _fmt(value) + mm.group(3), new_tag, count=1)
        new_block = new_block.replace(tag, new_tag, 1)
    return xml_text[:m.start(1)] + new_block + xml_text[m.end(1):]


def check_before(table, scope, expected, changes):
    problems, already = [], True
    for no, attrs in expected.items():
        row = table.get((scope, no))
        if row is None:
            problems.append("VDF %d missing in %s" % (no, scope))
            continue
        for attr, val in attrs.items():
            if attr in changes.get(no, {}) and _same(row.get(attr), changes[no][attr]):
                continue
            if not _same(row.get(attr), val):
                problems.append("VDF %d %s = %s (expected %s)" % (no, attr, row.get(attr), val))
    for no, attrs in changes.items():
        row = table.get((scope, no)) or {}
        for attr, val in attrs.items():
            if not _same(row.get(attr), val):
                already = False
    return problems, already


def verify_after(before_xml, after_xml, scope, changes):
    """The re-exported functions must equal the original with exactly the requested edits."""
    expected = vdf_table(edit_xml_text(before_xml, scope, changes))
    got = vdf_table(after_xml)
    diffs = []
    for key in sorted(set(expected) | set(got)):
        a, b = expected.get(key), got.get(key)
        if a is None or b is None:
            diffs.append("%s VDF %d present only on one side" % key)
            continue
        for attr in sorted(set(a) | set(b)):
            if not _same(a.get(attr), b.get(attr)):
                diffs.append("%s VDF %d %s expected %s got %s" % (key[0], key[1], attr, a.get(attr), b.get(attr)))
    # all other function settings (impedances, node VDFs, skim settings, ...) unchanged
    sig_exp = [r for r in functions_signature(before_xml) if "VDFUNCTIONSPARAMETERS/VDFUNCTION" not in r[0]]
    sig_got = [r for r in functions_signature(after_xml) if "VDFUNCTIONSPARAMETERS/VDFUNCTION" not in r[0]]

    def norm(rows):
        return sorted((p, tuple((k, (_num(v) if _num(v) is not None else v)) for k, v in attrs))
                      for p, attrs in rows)
    if norm(sig_exp) != norm(sig_got):
        diffs.append("OTHER_FUNCTION_SETTINGS_CHANGED (%d vs %d elements)" % (len(sig_exp), len(sig_got)))
    return diffs


# --------------------------------------------------------------------- run
def run(visum, out_root, dry_run=DRY_RUN, scope=SCOPE, changes=CHANGES, expected=EXPECTED_BEFORE):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(out_root) / "R1_VDF_EDIT" / ("%s%s" % ("DRYRUN_" if dry_run else "", stamp))
    out.mkdir(parents=True, exist_ok=True)
    lines = ["R1 VDF EDIT " + stamp, "mode: " + ("DRY_RUN (nothing written)" if dry_run else "APPLY"),
             "scope: " + scope, "changes: " + repr(changes)]
    before_path = out / "PROCEDURES_BEFORE.xml"
    lines.append("export: " + export_procedures(visum, before_path))
    before_xml = before_path.read_text(encoding="utf-8")
    table = vdf_table(before_xml)
    rows = []
    for no, attrs in changes.items():
        cur = table.get((scope, no), {})
        for attr, val in attrs.items():
            rows.append({"scope": scope, "vdf_no": no, "name": cur.get("NAME"), "attribute": attr,
                         "before": cur.get(attr), "after": _fmt(val)})
    with open(out / "01_CHANGES.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        lines.append("VDF %s (%s) %s: %s -> %s" % (r["vdf_no"], r["name"], r["attribute"], r["before"], r["after"]))
    problems, already = check_before(table, scope, expected, changes)
    if problems:
        lines += ["CHECK FAILED - the model does not have the expected current values:"] + problems
        status = "FAILED_PRECHECK_NOTHING_WRITTEN"
        lines.append("STATUS: " + status)
        (out / "00_STATUS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return status, out
    if already:
        status = "PASS_ALREADY_APPLIED_NOTHING_WRITTEN"
        lines.append("STATUS: " + status)
        (out / "00_STATUS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return status, out
    edited = edit_xml_text(before_xml, scope, changes)
    (out / "PROCEDURES_EDITED.xml").write_text(edited, encoding="utf-8")
    if dry_run:
        status = "PASS_DRY_RUN_NOTHING_WRITTEN"
        lines.append("STATUS: " + status)
        (out / "00_STATUS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return status, out
    try:
        lines.append("import: " + import_procedures(visum, out / "PROCEDURES_EDITED.xml"))
        after_path = out / "PROCEDURES_AFTER.xml"
        export_procedures(visum, after_path)
        diffs = verify_after(before_xml, after_path.read_text(encoding="utf-8"), scope, changes)
    except Exception as exc:
        diffs = ["IMPORT_OR_VERIFY_ERROR: %r" % (exc,)]
    if diffs:
        lines += ["VERIFY FAILED:"] + diffs[:50]
        try:
            lines.append("restore: " + import_procedures(visum, before_path, functions_only=False))
            status = "FAILED_ROLLED_BACK"
        except Exception as exc:
            lines.append("RESTORE FAILED: %r - reopen the .ver WITHOUT saving" % (exc,))
            status = "FAILED_RESTORE_FAILED_REOPEN_VER"
    else:
        status = "PASS_APPLIED_NOT_SAVED"
        lines.append("Verified: only the requested VDF attributes changed. Now File -> Save version as.")
    lines.append("STATUS: " + status)
    (out / "00_STATUS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return status, out


def _out_root(visum, here):
    cands = []
    try:
        cands.append(Path(str(visum.IO.CurrentVersionFile)).parent)
    except Exception:
        pass
    cands += [here, Path.home() / "Documents"]
    for c in cands:
        try:
            c.mkdir(parents=True, exist_ok=True)
            t = c / ".r1_write_test"
            t.write_text("x")
            t.unlink()
            return c
        except Exception:
            continue
    return here


def main():
    visum = _visum()
    here = _here()
    status, out = run(visum, _out_root(visum, here))
    msg = "R1 VDF EDIT: %s\n%s\\00_STATUS.txt" % (status, out)
    if SHOW_MESSAGE_BOX:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "R1 VDF edit", 0)
            return
        except Exception:
            pass
    print(msg)


if __name__ != "__r1_test__":
    try:
        main()
    except Exception as exc:
        txt = "R1 VDF EDIT FAILED: %r\n%s" % (exc, traceback.format_exc())
        try:
            (_here() / "R1_VDF_EDIT_FAILED.txt").write_text(txt, encoding="utf-8")
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, txt[:1500], "R1 VDF edit", 0)
        except Exception:
            print(txt)
