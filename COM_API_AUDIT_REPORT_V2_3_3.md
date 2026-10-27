# R1 15A2 V2.3.3 - COM/API audit and implemented changes

## Scope and truth boundary

Exact parent: V2.3.2 CSD408 CITY90, SHA256 `93f96dc9823ab2c5a0cb5f4ce1f56a8e3a2983a7addf045f854471ec75f760a9`.
This release is **OFFLINE COM/API AUDITED**, not a production or live Visum PASS.
It changes boundary validation, invocation, diagnostics and startup. It does not replace the numerical calibration methods.

## Confirmed findings and remedies

| Finding in supplied code | Implemented remedy | Basis |
|---|---|---|
| Operation inventory required `NO` and `Count` although operations use positions. | Enumerate documented `Operations.GetAll`, preserve 1-based positions; optional Count only if available. | COM01-02 |
| Callable returned COM objects were invoked again as zero-argument factories. | Distinguish a returned `_oleobj_` proxy from a Python method; use object properties directly. | COM04, PY01 |
| Assignment classification could rely on text/comment or an approved arbitrary enum. | Numeric 101 only for PrT; reject PuT100, skim103, scripts65 and the synthetic900 placeholder. Test fixtures now use101. | COM03 |
| Assignment-only filtering could disable enclosing active groups. | Preserve originally active group75 operations; disable other computations; verify and restore all ACTIVE flags. Exact live grouping remains a live-run check. | COM03 plus execution-state reasoning |
| Bulk attribute indices were treated as zone numbers. | Join GetMulti arrays by container index and Zone.NO; writes use those same indices. Preserve exact matrix-axis ordering. | COM06-07 |
| GetAll failures could lead to guessed ItemByKey(1..Count) iteration. | No guessed sparse network keys; explicit collection error. | COM06 |
| ACTIVE parsing omitted VARIANT_BOOL -1 and serialized1.0. | Typed true/false handling, reject ambiguous or missing flags. | COM Boolean semantics; regression fixtures |
| DStratSet selection used substring matching and could pick one of two plausible operations. | Exact token membership, blank-scope rejection, ambiguity detection. | Source review |
| AddKeyColumns assumed host-defined order and equal widths were treated as proof. | Explicit key column names/order; mandatory Vol(AP); per-row width and numeric validation; optional speed/time columns remain optional. | COM04 and source review |
| A required DSeg with unreadable ODMatrix could silently be omitted from the frozen-demand snapshot. | Required binding and matrix-shape checks before mutation. | Source review, COM10 |
| A failed read of a required passenger volume could become zero in12D. | Strict required read; genuine numeric0 remains accepted; missing/blank/NaN/negative is a distinct error. | Source review, approved user policy |
| Fallback activation could attach to a different running session. | Main binds only to host-injected Visum/COM; never starts or attaches through generic ROT activation. | RUN01 |
| Repeated runs could import cached modules from another release. | Controlled r1_15a2 module reload; recursion guard; correct V233 entrypoint hash and resume variable. | Source review |
| Runtime diagnostic could stop at its first mismatch. | New aggregate read-only audit saves each result and continues collecting independent mismatches. | Implemented improvement |

## Types that were already correct

Zone-demand matrix creation uses `AddMatrix(no, 2, 3)` (COM09). MatrixType is not DataSourceType; an externally sourced distance skim is not an ordinary vehicle-demand matrix (COM10). The existing diagnostic UDA types real2 and text5 are correct (COM11). Do not substitute numerical enums from PTV Vissim documentation.

COM IDs (NO, FROMNODENO, TONODENO, PathIndex) are validated as integers without rounding. Numerical observations and parameters are finite doubles. A comma decimal separator is accepted; ambiguous mixed decimal separators are rejected. GetMulti reads explicitly request all objects, independent of GUI selection.

## Execution environment

Do not universally require the Python main thread: the PTV documentation explicitly allows Legacy file execution in a host-managed wx thread. Use the injected object on the calling thread; the new code does not move it to another thread. Standard Python3.13 and Legacy support COM; Hub cloud-computing mode does not (RUN01).

`GetPath(2)` returns the configured version project directory (COM12); it is not proof of a particular version filename. The report records the resolved directory, runtime and available instance metadata. A writable LOCALAPPDATA/home fallback is explicitly reported, never described as the model folder.

The calibration master uses rollback and must run outside an already executing Procedure Sequence. The separate read-only probe may be embedded as internal source. Successful probe execution has no print, custom message box, assignment or model writes.

## What the live probe checks

Environment and injected instance; position/type/ACTIVE of operations; typed parameter objects; installed type-library declarations where exposed; exact available attribute catalogs; full required zone vectors and their ordering; required DSeg-to-matrix bindings; full required matrix dimensions and finite nonnegative values; R1_OSRM_DIST_KM identity; link key/attribute and passenger-volume schemas; approved498 IDs, RPDI values, roles, weights and directional keys; BOTH tag on90 city profiles; path/path-link/assignment-quality interfaces and required columns.

The probe reads link attributes in bulk (nine main schema calls rather than nine calls per link). It never downloads millions of path-link rows just to discover a schema: a sample is attempted only when installed type metadata confirms FirstObject/LastObject on SaveToArray. A skipped bounded sample is explicitly not a path-coverage PASS.

The full package additionally runs the existing exact TG formula token audit and all16 TD parameter reads as aggregate extra checks. The standalone probe contains the common COM audit and embedded approved roster, not the full TG/TD calibration modules.

## Still requires live approval

- `assignment_operations` remains empty: no operation IDs inferred from screenshots or generic examples.
- `gap_readback.attribute` remains null. Test `Net.GAP` is only a synthetic fixture. Do not use a configured stopping tolerance as achieved convergence.
- Multiple assignment stages must be assessed for correct final joint passenger/freight scope; group preservation is not a substitute for a live convergence test.
- Full actual path coverage/parity, support, live write/readback and PRE.ver rollback need a first bounded live test.
- Supplied VDF/impedance exports remain sealed references, not a new complete live node/turn/connector settings export.
- CSD mapping-review acknowledgements have not been automatically approved.
- LONG component target authority remains unresolved exactly as in the parent.

## Preserved decisions and evidence

All20 protected numerical/authority files listed in `evidence_v233/protected_parity.json` are byte-identical to parent. This includes sequence logic, supply/generation/TD numerical code, common controller,11D and the supplied authority files. CSD408 plus CITY90 means462 CAL and36 VALID. RPDI is already converted; no extra vehicle/year factor. BOTH model values sum both directional links; no observation halving. Genuine zero model flows, including the27 accepted CSD cases, are allowed. ADDVAL1 unit stays10 generalized seconds. Default apply staysfalse.

Offline tests run in Python3.13.5 on Linux with NumPy and COM-shaped fixtures, not Windows COM. Clean extraction is tested separately; see `V233_OFFLINE_GATE_STATUS.json` and the external clean-ZIP verification.

## Primary sources

### COM01 - PTV Visum 2026 COM: IOperations
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~IOperations.html

Operations are identified by 1-based position, not a network NO attribute.

### COM02 - PTV Visum 2026 COM: IOperations members
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~IOperations_members.html

GetAll property, ItemByKey, GetParent/GetChildren; Count is not a documented member.

### COM03 - PTV Visum 2026 COM: OperationType
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~OperationType.html

PrT assignment101; PuT100; TG45; TD46; script65; group75; PrT skims103.

### COM04 - PTV Visum 2026 COM: CreatePrTPathList
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~ILists~CreatePrTPathList.html

Read-only object property. Official Python uses SetObjects(0,"C",0) and explicit AddColumn key IDs.

### COM05 - PTV Visum 2026 COM: ILists
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~ILists_members.html

Distinct path, path-link and assignment-quality list properties.

### COM06 - PTV Visum 2026 COM: GetMultiAttValues
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~ILinks~GetMultiAttValues.html

Returned keys are GetAll indices, not object numbers. OnlyActive defaults True; pass False for full scope.

### COM07 - PTV Visum 2026 COM: SetMultiAttValues
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~ILinks~SetMultiAttValues.html

Third argument Add=False means replacement; it is NOT an OnlyActive selector.

### COM08 - PTV Visum 2026 COM: IOperation members
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~IOperation_members.html

Typed TG/TD/PrT parameter object properties are distinct.

### COM09 - PTV Visum 2026 COM: AddMatrix
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~INet~AddMatrix.html

Official example creates zone demand matrix using ObjectTypeRef2, MatrixType3.

### COM10 - PTV Visum 2026 COM: IMatrix attributes
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~IMatrix_attributes.html

MatrixType, DataSourceType and ObjectTypeRef are different attributes. NumRows/NumCols are read-only outputs. MatrixUnit is maintained separately.

### COM11 - PTV Visum 2026 COM: AddUserDefinedAttribute
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~IScreenlines~AddUserDefinedAttribute.html

Examples: integer1, float2, text5, Boolean9. Existing correct types were not replaced with Vissim enums.

### COM12 - PTV Visum 2026 COM: GetPath
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~IVisum~GetPath.html

Returns configured project directory for file type; not necessarily the full loaded version filename.

### RUN01 - PTV Visum 2026: integrating scripts
https://cgi.ptvgroup.com/vision-help/VISUM_2026_EN-DE/en-us/Content/2_Mit_Skripten_arbeiten/2_14_Skript-Dateien%20oder%20Skript-Code%20in%20den%20Verfahrensablauf%20einbinden.htm

Standard3.13 supports COM. Hub does not. Legacy script-file execution can use a wx thread. LoadVersion forbidden inside a running procedure sequence.

### RUN02 - PTV support: COM documentation
https://support.ptvgroup.com/en-us/knowledgebase/article/KA-05080

Installed COM help and COM examples are the exact local reference where public pages omit details.

### PY01 - pywin32 maintainer source: dynamic.py
https://github.com/mhammond/pywin32/blob/main/com/win32com/client/dynamic.py

CDispatch.__call__ invokes the default member. callable(COM property) does not imply a factory that should be called again.

### COM13 - PTV Visum 2026 COM object library overview
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB_P.html

Confirms interface names for type-library extraction; does not establish every parameter attribute signature.

