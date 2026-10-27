"""Read-only verifier detects real-byte corruption and divergent pointers."""
import json
from pathlib import Path
import r1_15a2_overnight_controller_v240 as ctl
from tests.synthetic_v22_adapter import SyntheticAdapter,synthetic_config
from VERIFY_CHECKPOINTS_V245_CP01 import verify_checkpoint_state


def initial(tmp_path):
    a=SyntheticAdapter(synthetic_config());r=tmp_path/'run'
    cp=ctl._save_rotating_checkpoint(a,r,0)
    return a,r,cp


def test_base_and_two_slot_verified(tmp_path):
    a,r,cp=initial(tmp_path)
    assert verify_checkpoint_state(r)['status']=='PASS'
    ctl._save_rotating_checkpoint(a,r,1)
    v=verify_checkpoint_state(r)
    assert v['status']=='PASS' and v['canonical_latest']['accepted_count']==1
    assert v['verified_pointer_count']==3
    assert not v['model_writes'] and not v['com_calls']


def test_payload_corruption_blocks_verification(tmp_path):
    a,r,cp=initial(tmp_path)
    Path(cp['path']).write_bytes(b'garbled')
    v=verify_checkpoint_state(r)
    assert v['status']=='FAIL'
    assert any('sha256 mismatch' in s for s in v['issues'])


def test_pointer_mismatch_is_not_autorepaired(tmp_path):
    a,r,cp=initial(tmp_path)
    path=r/'CHECKPOINTS/SLOT_B.json'
    o=json.loads(path.read_text());o['accepted_count']=2
    path.write_text(json.dumps(o))
    v=verify_checkpoint_state(r)
    assert v['status']=='FAIL'
    assert any('CANONICAL_SLOT_POINTER_MISMATCH' in s for s in v['issues'])
    assert json.loads(path.read_text())==o


def test_path_escape_is_rejected(tmp_path):
    a,r,cp=initial(tmp_path)
    pointer=r/'LATEST_ACCEPTED_CHECKPOINT.json'
    o=json.loads(pointer.read_text());o['checkpoint']['path']=str(tmp_path/'outside.ver')
    pointer.write_text(json.dumps(o))
    v=verify_checkpoint_state(r)
    assert v['status']=='FAIL'
    assert any('outside expected' in s for s in v['issues'])


def test_orphan_is_reported_but_not_removed(tmp_path):
    a,r,cp=initial(tmp_path)
    x=r/'CHECKPOINTS/ACCEPTED_A_0001_ORPHAN.ver';x.write_bytes(b'orphan')
    v=verify_checkpoint_state(r)
    assert v['status']=='PASS' and x.name in v['orphan_files_not_deleted']
    assert x.is_file()
