"""GENFIX1 snapshot regressions: failed COM reads are not model changes."""
from __future__ import annotations

import copy

import pytest

from conftest import FakeAttr, FakeCollection
from test_supply_visum_v22 import small_cfg, state_visum
import r1_15a2_com_compat as com
import r1_15a2_single_pass_snapshot_v24915p2c as parent
import r1_15a2_snapshot_reads_v24917 as strict
from r1_15a2_supply_visum import VisumAdapter as SupplyAdapter


class Busy(RuntimeError):
    def __init__(self, hresult):
        super().__init__("synthetic COM snapshot read failure")
        self.hresult = hresult


class ReadFault:
    """COM-shaped wrapper that rejects a selected read, without model writes."""

    def __init__(self, inner, member, hresult, *, attribute=False, times=1):
        self.inner = inner
        self.member = member
        self.hresult = hresult
        self.attribute = attribute
        self.times = times
        self.hits = 0

    def _check(self, name, attribute):
        if name == self.member and self.attribute == attribute:
            self.hits += 1
            if self.hits <= self.times:
                raise Busy(self.hresult)

    def AttValue(self, name):
        self._check(name, True)
        return self.inner.AttValue(name)

    def __getattr__(self, name):
        self._check(name, False)
        return getattr(self.inner, name)


def _adapter():
    cfg = copy.deepcopy(small_cfg())
    retry = {
        "enabled": True,
        "max_attempts": 3,
        "initial_delay_seconds": 0.0,
        "max_delay_seconds": 0.0,
        "backoff_factor": 1.0,
        "max_elapsed_seconds": 10.0,
    }
    cfg["com_resilience"] = dict(
        retry, scoped_policies={"startup_snapshot_read": dict(retry)})
    return SupplyAdapter(state_visum(), cfg)


def _original(adapter):
    # Other suites may have installed the old whole-snapshot retry globally.
    # Unwrap it to demonstrate the underlying legacy read contract directly.
    fn = parent.single_pass_exact_snapshot
    while getattr(fn, "_r1_v24916_combusy_original", None) is not None:
        fn = fn._r1_v24916_combusy_original
    return fn(adapter)


@pytest.mark.parametrize("hresult", [
    com.RPC_E_CALL_REJECTED, com.RPC_E_SERVERCALL_RETRYLATER,
])
def test_original_swallowed_comment_busy_manufactures_false_state_change(hresult):
    adapter = _adapter()
    expected = _original(adapter)
    operations = adapter.visum.Procedures.Operations
    operations.items[0] = ReadFault(
        operations.items[0], "COMMENT", hresult, attribute=True)
    observed = _original(adapter)

    assert observed["operations_hash"] != expected["operations_hash"]
    assert observed["state_hash"] != expected["state_hash"]
    for key in set(expected) - {"operations_hash", "state_hash"}:
        assert observed[key] == expected[key]
    assert _original(adapter) == expected  # no live model edit ever occurred


def _with_optional_dseg(adapter):
    segments = adapter.visum.Net.DemandSegments
    items = list(segments.items) + [FakeAttr(
        CODE="DIAGNOSTIC_ONLY", ODMatrix=adapter.visum.Net.Matrices.ItemByKey(3))]
    adapter.visum.Net.DemandSegments = FakeCollection(items)


def _inject(adapter, location, hresult, times=1):
    visum = adapter.visum
    operations = visum.Procedures.Operations
    segments = visum.Net.DemandSegments
    params = operations.items[1].TripDistributionParameters
    collection = params.TripDistributionDStratParameters

    def fault(obj, member, *, attribute=False):
        return ReadFault(obj, member, hresult, attribute=attribute, times=times)

    if location in ("COMMENT", "NAME"):
        proxy = fault(operations.items[0], location, attribute=True)
        operations.items[0] = proxy
    elif location == "OPTIONAL_DSEG_CODE":
        proxy = fault(segments.items[-1], "CODE", attribute=True)
        segments.items[-1] = proxy
    elif location == "OPTIONAL_DSEG_BINDING":
        proxy = fault(segments.items[-1], "ODMatrix")
        segments.items[-1] = proxy
    elif location == "BOUND_MATRIX_NO":
        proxy = fault(segments.items[-1].ODMatrix, "NO", attribute=True)
        segments.items[-1].ODMatrix = proxy
    elif location == "FINGERPRINT_MATRIX_NO":
        proxy = fault(visum.Net.Matrices.ItemByKey(9101), "NO", attribute=True)
        visum.Net.Matrices.keys[9101] = proxy
    elif location == "DSEG_COLLECTION_COUNT":
        proxy = fault(segments, "Count")
        visum.Net.DemandSegments = proxy
    elif location == "TD_PARAMETERS":
        proxy = fault(operations.items[1], "TripDistributionParameters")
        operations.items[1] = proxy
    elif location == "TD_DSTRATSET":
        proxy = fault(params, "DSTRATSET", attribute=True)
        operations.items[1].TripDistributionParameters = proxy
    elif location == "TD_DSTRAT_COLLECTION":
        proxy = fault(params, "TripDistributionDStratParameters")
        operations.items[1].TripDistributionParameters = proxy
    elif location == "TD_ITEMBYKEY":
        proxy = fault(collection, "ItemByKey")
        params.TripDistributionDStratParameters = proxy
    elif location in ("TD_GRAVITY", "TD_B", "TD_C"):
        target = collection.ItemByKey("1_WORK_E_C")
        member = {"TD_GRAVITY": "GravitationParameters",
                  "TD_B": "PARA_B", "TD_C": "PARA_C"}[location]
        proxy = fault(target, member, attribute=location != "TD_GRAVITY")
        collection.keys["1_WORK_E_C"] = proxy
        collection.items[0] = proxy
    else:
        raise AssertionError(location)
    return proxy


@pytest.mark.parametrize("hresult", [
    com.RPC_E_CALL_REJECTED, com.RPC_E_SERVERCALL_RETRYLATER,
])
@pytest.mark.parametrize("location", [
    "COMMENT", "NAME", "OPTIONAL_DSEG_CODE", "OPTIONAL_DSEG_BINDING",
    "BOUND_MATRIX_NO", "FINGERPRINT_MATRIX_NO", "DSEG_COLLECTION_COUNT",
    "TD_PARAMETERS", "TD_DSTRATSET", "TD_DSTRAT_COLLECTION", "TD_ITEMBYKEY",
    "TD_GRAVITY", "TD_B", "TD_C",
])
def test_transient_optional_reads_retry_the_whole_snapshot(location, hresult):
    adapter = _adapter()
    _with_optional_dseg(adapter)
    expected = _original(adapter)
    proxy = _inject(adapter, location, hresult)

    actual = strict.strict_snapshot(adapter)

    assert actual == expected
    assert proxy.hits >= 2
    events = adapter.r1_com_busy_read_retry_events
    assert len(events) == 1
    assert events[0]["event"] == "RETRY"
    assert events[0]["label"] == "V24917_STRICT_FULL_SNAPSHOT"
    assert adapter._r1_combusy_read_retry_depth == 0


@pytest.mark.parametrize("hresult", [
    com.RPC_E_CALL_REJECTED, com.RPC_E_SERVERCALL_RETRYLATER,
])
def test_persistent_busy_is_propagated_without_a_permissive_fallback(hresult, monkeypatch):
    adapter = _adapter()
    proxy = _inject(adapter, "COMMENT", hresult, times=20)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsafe snapshot fallback")

    monkeypatch.setattr(parent, "single_pass_exact_snapshot", forbidden)
    with pytest.raises(Exception) as caught:
        strict.strict_snapshot(adapter)
    assert com.is_retryable_com_error(caught.value)
    assert proxy.hits == 3
    assert adapter._r1_combusy_read_retry_depth == 0
    assert adapter.r1_com_busy_read_retry_events[-1]["event"] == "EXHAUSTED"
    assert not hasattr(adapter, "last_perf2c_snapshot_telemetry")


def test_stable_reads_are_exact_including_telemetry_and_unsupported_name():
    adapter = _adapter()
    expected = _original(adapter)
    old_telemetry = adapter.last_perf2c_snapshot_telemetry
    actual = strict.strict_snapshot(adapter)
    assert actual == expected
    assert set(actual) == set(expected)
    telemetry = adapter.last_perf2c_snapshot_telemetry
    assert set(telemetry) == set(old_telemetry)
    for key in set(telemetry) - {"loader_seconds"}:
        assert telemetry[key] == old_telemetry[key]
    assert telemetry["cross_call_cache"] is False
    assert not getattr(adapter, "r1_com_busy_read_retry_events", [])
    # Fake operations, like live IOperation, do not expose NAME at all.
    with pytest.raises(KeyError):
        adapter.visum.Procedures.Operations.items[0].AttValue("NAME")


@pytest.mark.parametrize("domain", [
    "ADDVAL", "FIXED_LINK", "MATRIX", "GENERATION", "TD", "OPERATIONS", "DSEG",
])
def test_genuine_model_changes_remain_visible_and_exactly_match_parent(domain):
    adapter = _adapter()
    before = strict.strict_snapshot(adapter)
    visum = adapter.visum
    if domain == "ADDVAL":
        visum.Net.Links.items[0].SetAttValue("ADDVAL1", 0.5)
    elif domain == "FIXED_LINK":
        visum.Net.Links.items[0].SetAttValue("LENGTH", 2.0)
    elif domain == "MATRIX":
        visum.Net.Matrices.ItemByKey(9101).values[0, 1] += 0.00001
    elif domain == "GENERATION":
        visum.Net.Zones.rows[0]["ADD_PROD_W"] = 1.25
    elif domain == "TD":
        params = visum.Procedures.Operations.items[1].TripDistributionParameters
        params.TripDistributionDStratParameters.ItemByKey("1_WORK_E_C").SetAttValue("PARA_C", -0.2)
    elif domain == "OPERATIONS":
        visum.Procedures.Operations.items[-1].SetAttValue("ACTIVE", 0)
    else:
        visum.Net.DemandSegments.items[0].ODMatrix = visum.Net.Matrices.ItemByKey(2)
    after = strict.strict_snapshot(adapter)
    assert after == _original(adapter)
    assert after["state_hash"] != before["state_hash"]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0])
def test_invalid_matrix_cells_fail_without_retry(invalid):
    adapter = _adapter()
    adapter.visum.Net.Matrices.ItemByKey(9101).values[0, 1] = invalid
    with pytest.raises(RuntimeError, match="nonfinite or negative"):
        strict.strict_snapshot(adapter)
    assert not getattr(adapter, "r1_com_busy_read_retry_events", [])


def test_local_reader_does_not_patch_parent_read_helpers():
    saved = (parent._read_dseg_bindings, parent._read_operation_records,
             parent._read_td_snapshot_from_records, parent.single_pass_exact_snapshot)
    strict.strict_snapshot(_adapter())
    assert saved == (parent._read_dseg_bindings, parent._read_operation_records,
                     parent._read_td_snapshot_from_records, parent.single_pass_exact_snapshot)


class EnumerationOnly:
    def __init__(self, values):
        self.values = values

    @property
    def GetAll(self):
        return tuple(self.values)


class PropertyOnlyParameters:
    def __init__(self, b, c):
        self.PARA_B = b
        self.PARA_C = c

    def AttValue(self, name):
        raise AttributeError(name)


@pytest.mark.parametrize("hresult", [
    com.RPC_E_CALL_REJECTED, com.RPC_E_SERVERCALL_RETRYLATER,
])
@pytest.mark.parametrize("access", ["function", "enumeration", "property"])
def test_td_compatibility_routes_retry_busy_reads_without_switching_routes(access, hresult):
    adapter = _adapter()
    params = adapter.visum.Procedures.Operations.items[1].TripDistributionParameters
    collection = params.TripDistributionDStratParameters
    if access == "function":
        params.TripDistributionDStratParameters = lambda code: collection.ItemByKey(code)
        expected = _original(adapter)
        calls = []

        def function(code):
            calls.append(code)
            if len(calls) == 1:
                raise Busy(hresult)
            return collection.ItemByKey(code)

        params.TripDistributionDStratParameters = function
    elif access == "enumeration":
        enum = EnumerationOnly(list(collection.items))
        params.TripDistributionDStratParameters = enum
        expected = _original(adapter)
        enum.values[0] = ReadFault(enum.values[0], "DEMANDSTRATUMCODE", hresult,
                                   attribute=True)
    else:
        obj = collection.ItemByKey("1_WORK_E_C")
        obj.GravitationParameters = PropertyOnlyParameters(0.0, -0.1)
        expected = _original(adapter)
        obj.GravitationParameters = ReadFault(obj.GravitationParameters, "PARA_B", hresult)
    assert strict.strict_snapshot(adapter) == expected
    assert len(adapter.r1_com_busy_read_retry_events) == 1
    assert adapter.r1_com_busy_read_retry_events[0]["event"] == "RETRY"


def test_genuinely_unsupported_td_spellings_keep_legacy_fallbacks():
    adapter = _adapter()
    op = adapter.visum.Procedures.Operations.items[1]
    params = op.TripDistributionParameters
    del op._attrs["TripDistributionParameters"]
    op.TripDistributionParameter = params
    params._attrs["DStratSet"] = params._attrs.pop("DSTRATSET")
    collection = params._attrs.pop("TripDistributionDStratParameters")
    params.DStratParas = collection
    first = collection.ItemByKey("1_WORK_E_C")
    first.GravityParameters = PropertyOnlyParameters(0.0, -0.1)
    assert strict.strict_snapshot(adapter) == _original(adapter)
    assert not getattr(adapter, "r1_com_busy_read_retry_events", [])
