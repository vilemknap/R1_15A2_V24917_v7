from r1_15a2_trial_adapter_v24916p2c import VisumAdapter as Overlay
from r1_15a2_trial_adapter_v24915p2c import VisumAdapter as Parent


def test_overlay_is_current_parent_subclass():
    assert issubclass(Overlay, Parent)

def test_feature_off_does_not_override_parent_snapshot():
    assert "snapshot" not in Overlay.__dict__
    if hasattr(Parent, "snapshot"):
        assert Overlay.snapshot is Parent.snapshot

def test_feature_off_does_not_override_parent_diagnostics():
    assert "diagnostics" not in Overlay.__dict__
    if hasattr(Parent, "diagnostics"):
        assert Overlay.diagnostics is Parent.diagnostics
