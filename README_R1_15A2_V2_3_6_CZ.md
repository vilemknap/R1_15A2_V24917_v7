# R1 15A2 V2.3.6 - LIVE exact TG 09F4 prefeed compatibility

Source: live PTV Visum 2026 COM report 2026-10-16 00:18 local.

The V2.3.5 run had 110 PASS, one required FAIL: TG_FORMULA_PARAMETER_BINDINGS.
The 10 active WORK/SERVICE TG DStrata contain precise formulas:
  PRODUCTIONFUNCTION = [FP_component] + [P09F4_PER_PRE_component]
  ATTRACTIONFUNCTION = [FA_family] + [A09F4_PER_PRE_component]
All 20 prefeed attributes are present in the live Zones.Attributes catalog,
ValueType=2 (Real).  This release requires exact formulas (no extra terms,
missing terms, swapped prefeed, arbitrary factors or unapproved aliases).

The production TG contract and the separate inline COM preflight both check
these 10 exact pairs.  The production runtime additionally requires 20 prefeed
attributes (numeric, finite, all 681 zones) and validates their REAL datatype.
The inline preflight validates exact live formula pairs, attributes, and
ValueType=2, and stores output beside the currently loaded .ver.

ACTIVE FILES:
- R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_6.py (EXTERNAL Visum Scripts only)
- R1_15A2_CONFIG_V2_3_6.json (apply=false)
- R1_15A2_VISUM_COM_PREFLIGHT_V2_3_6_INLINE.py (standalone read-only)
- authorities/R1_TG_PARAMETER_DEPENDENCY_CONTRACT_V2_3_6.json
- authorities/R1_TG_OPERATION_5_ADDITIVE_LIVE_EVIDENCE_20261016.json

NO changes to protected numeric algorithms, observed CSD408/CITY90 data,
APPROVED_RPDI interpretation, kappa, IDP, ADDVAL1, or generation formulae
inside Visum.  Only software readback/contract is updated.

APPLY=false.  Assignment-operation bindings and achieved-GAP-to-final-iteration
binding are NOT approved.  The separate CSD mapping and CITY bidirectional QA
flags are NOT acknowledged.  Path parity/full coverage and live production
calibration remain untested.  Never treat 110/111 as an APPLY permit.

WARNING: Formula metadata confirms exact OUTER TG references in the live .ver.
It does NOT re-prove the nested FP/FA UDA formula after user edits.
Repeat 09G nested-formula forensic export if those expressions are changed.

Run the stand-alone inline COM preflight once in Visum and inspect
TG_FORMULA_PARAMETER_BINDINGS and all ZONE_ATTRIBUTE:P09F4.../A09F4...
rows.  A successful live preflight will enable design-only testing only.

The next live preflight writes sum and nonzero_count for each P09F4/A09F4 zone attribute.
This allows a separate audit of fixed additive prefeed exposure. IMPORTANT:
A relative change in the FP/FA component is NOT automatically the same relative
change in the whole TG formula when additive 09F4 prefeed is present.
Generation APPLY requires a separately confirmed effect/elasticity audit;
this gate repair alone does not prove generation candidate causal accuracy.
