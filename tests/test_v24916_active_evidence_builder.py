from __future__ import annotations

from types import SimpleNamespace

from r1_15a2_active_demand_evidence_v24916p2c import (
    ActiveDemandEvidenceBuilder,
    _exact_link,
    _read_flowbundle_matrix,
)


class _Link:
    def __init__(self, no, fr, to):
        self.values = {"NO": no, "FROMNODENO": fr, "TONODENO": to}

    def AttValue(self, name):
        return self.values[name]


class _Links:
    def __init__(self, link):
        self.link = link
        self.calls = []

    def ItemByKey(self, fr, to):
        self.calls.append((fr, to))
        return self.link


def _adapter_with_links(link):
    links = _Links(link)
    adapter = SimpleNamespace(
        visum=SimpleNamespace(Net=SimpleNamespace(Links=links)),
        cfg={}, com_retry_policy=None,
    )
    return adapter, links


def test_active_exact_link_uses_official_two_key_lookup_and_readback():
    adapter, links = _adapter_with_links(_Link(77, 10, 20))
    result = _exact_link(adapter, (77, 10, 20))
    assert result.AttValue("NO") == 77
    assert links.calls == [(10, 20)]


def test_active_exact_link_fails_on_link_no_mismatch():
    adapter, _ = _adapter_with_links(_Link(78, 10, 20))
    try:
        _exact_link(adapter, (77, 10, 20))
    except RuntimeError as exc:
        assert "V24916_ACTIVE_LINK_READBACK_MISMATCH" in str(exc)
    else:
        raise AssertionError("link readback mismatch must fail closed")


class _Matrix:
    def __init__(self, values, calls):
        self.values = values
        self.calls = calls

    def GetValues(self):
        self.calls.append("GetValues")
        return self.values


class _FlowBundle:
    def __init__(self):
        self.calls = []
        self._demand_segments = None
        self.matrix = _Matrix([[1.0]], self.calls)

    def Clear(self):
        self.calls.append("Clear")

    @property
    def DemandSegments(self):
        return self._demand_segments

    @DemandSegments.setter
    def DemandSegments(self, value):
        self._demand_segments = value
        self.calls.append(("DemandSegments", value))

    def CreateCondition(self, link, second, a, b, c, d):
        self.calls.append(("CreateCondition", link, second, a, b, c, d))

    def ExecuteCurrentConditions(self):
        self.calls.append("ExecuteCurrentConditions")

    def GetOrCreateFlowBundleMatrix(self, dseg):
        self.calls.append(("GetOrCreateFlowBundleMatrix", dseg))
        return self.matrix


def test_active_flowbundle_read_uses_only_sealed_contract_and_clears_afterwards():
    fb = _FlowBundle()
    adapter = SimpleNamespace(
        visum=SimpleNamespace(Net=SimpleNamespace(FlowBundle=fb)),
        cfg={}, com_retry_policy=None,
    )
    link = object(); dseg = object()
    values = _read_flowbundle_matrix(adapter, link, dseg, "NATIVE_CW")
    assert values == [[1.0]]
    assert fb.calls == [
        "Clear",
        ("DemandSegments", "NATIVE_CW"),
        ("CreateCondition", link, None, False, False, 0, 0),
        "ExecuteCurrentConditions",
        ("GetOrCreateFlowBundleMatrix", dseg),
        "GetValues",
        "Clear",
    ]


def _identity_builder(assignment_epoch=1, path_epoch=2):
    rm = SimpleNamespace(
        assignment_epoch=assignment_epoch,
        run_token="RUN",
        visum_session_token="SESSION",
    )
    adapter = SimpleNamespace(
        readback_manager=rm,
        last_gap_evidence={"gap": 0.001},
        path_epoch_index=path_epoch,
        zones=[1, 2],
        _epoch_basis=lambda: "PATH_BASIS",
        _epoch_comparison_basis=lambda: "COMPARE_BASIS",
    )
    builder = ActiveDemandEvidenceBuilder.__new__(ActiveDemandEvidenceBuilder)
    builder.adapter = adapter
    builder.cfg = {"flowbundle": {"enabled": True}}
    return builder


def test_active_evidence_identity_invalidates_on_assignment_epoch_change():
    dist = SimpleNamespace(identity_hash="DIST")
    diag = {"d12": {"hash": "X"}}
    snapshot = {"state_hash": "S" * 64}
    a = _identity_builder(assignment_epoch=1)._identity(snapshot, diag, dist)
    b = _identity_builder(assignment_epoch=2)._identity(snapshot, diag, dist)
    assert a.semantic_state_hash == b.semantic_state_hash
    assert a.identity_hash != b.identity_hash


def test_active_evidence_identity_invalidates_on_path_epoch_change_with_same_state():
    dist = SimpleNamespace(identity_hash="DIST")
    diag = {"d12": {"hash": "X"}}
    snapshot = {"state_hash": "S" * 64}
    a = _identity_builder(path_epoch=2)._identity(snapshot, diag, dist)
    b = _identity_builder(path_epoch=3)._identity(snapshot, diag, dist)
    assert a.semantic_state_hash == b.semantic_state_hash
    assert a.identity_hash != b.identity_hash
