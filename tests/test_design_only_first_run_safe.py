from pathlib import Path
import ast, hashlib, json
ROOT=Path(__file__).resolve().parents[1]

def test_safe_runner_forces_apply_false_even_if_environment_is_set():
    src=(ROOT/'R1_15A2_DESIGN_ONLY_FIRST_RUN_V2_3_7.py').read_text()
    t=ast.parse(src)
    fn=next(node for node in t.body if isinstance(node,ast.FunctionDef) and node.name=='load_config')
    assignments=[node for node in ast.walk(fn) if isinstance(node,ast.Assign) and any(isinstance(x,ast.Subscript) and isinstance(x.value,ast.Name) and x.value.id=='cfg' and isinstance(x.slice,ast.Constant) and x.slice.value=='apply' for x in node.targets)]
    assert len(assignments)==1
    assert isinstance(assignments[0].value,ast.Constant) and assignments[0].value.value is False
    assert 'R1_15A2_V237_APPLY' not in src

def test_selected_12d_helper_only_disables_diagnostic_uda_writes():
    path=ROOT/'helpers/R1_12D_CSD408_CITY90_RPDI_498_APPROVED.py'
    body=path.read_text()
    assert 'WRITE_DIAGNOSTIC_UDAS = False' in body
    orig=body.replace('WRITE_DIAGNOSTIC_UDAS = False  # DESIGN-FIRST-RUN: no CountLocation attribute writes','WRITE_DIAGNOSTIC_UDAS = True')
    assert hashlib.sha256(orig.encode()).hexdigest()=='0e907474dead5dc765c5cdb198019f71945c08c8cb514218861d74c97822667d'
    assert 'if WRITE_DIAGNOSTIC_UDAS:' in body

def test_model_calibration_stays_gated():
    c=json.loads((ROOT/'R1_15A2_CONFIG_V2_3_7.json').read_text())
    assert c['apply'] is False
    assert c['supply']['assignment_operations']==[]
    assert c['supply']['gap_readback']['maximum_gap']==0.005
    assert not c['csd408_mapping_review_acknowledged']
    assert not c['city90_bidirectional_qa_acknowledged']
