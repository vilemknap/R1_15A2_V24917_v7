"""Small explicit transaction and result contracts used by the V2.4.5 core."""
from contextlib import contextmanager, nullcontext
from pathlib import Path
import math
from r1_15a2_supply import SupplyContractError


def recovery_scope(control, reason):
    """Defer cooperative stops only while restoring/finishing a mutated state."""
    method = getattr(control, "recovery", None)
    return method(reason) if method is not None else nullcontext()


@contextmanager
def adapter_config_scope(adapter, cfg):
    """Use one acceptance policy for the ledger AND the live adapter gate."""
    old = adapter.cfg
    adapter.cfg = cfg
    try:
        yield
    finally:
        adapter.cfg = old


def stationary_td_result(inner):
    return (inner.get("search_complete") is True and
            inner.get("stationarity_confirmed") is True and
            str(inner.get("stop_reason", "")) == "LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM")


def validate_v245_config(cfg):
    if cfg.get("apply") is not False or cfg.get("production_apply") is not False:
        raise SupplyContractError("V245_WORKING_COPY_ONLY")
    dc = cfg.get("coupled_demand", {})
    minimum = dc.get("min_stationary_cycles", 2)
    maximum = dc.get("max_outer_cycles", 12)
    def positive_int(value, name):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise SupplyContractError("V245_INVALID_CONFIG:" + name)
    positive_int(minimum, "min_stationary_cycles")
    positive_int(maximum, "max_outer_cycles")
    if minimum < 2 or maximum < minimum:
        raise SupplyContractError("V245_TWO_CONFIRMED_CYCLES_REQUIRED")
    fine = dc.get("finecdf_td", {})
    for key in ("max_iterations", "max_td_evaluations", "max_stagnant_iterations"):
        positive_int(fine.get(key), key)
    for key, value in (("max_runtime_seconds", cfg.get("trial_calibration", {}).get("max_runtime_seconds")),
                       ("td_max_runtime_seconds", fine.get("max_runtime_seconds"))):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
            raise SupplyContractError("V245_INVALID_CONFIG:" + key)
    if fine.get("native_multi_guard_policy") != "DIAGNOSTIC_ONLY_NATIVE_OUTPUT_AUTHORITY":
        raise SupplyContractError("V245_NATIVE_MULTI_POLICY_CHANGED")
    if cfg.get("block_schedule") != ["GENERATION", "TD_FINECDF_V17", "SUPPLY_ADDVAL1"]:
        raise SupplyContractError("V245_BLOCK_ORDER_CHANGED")
    if not cfg.get("trial_calibration", {}).get("enabled"):
        raise SupplyContractError("V245_TRIAL_CALIBRATION_DISABLED")
    return {"passes": True, "minimum_confirmed_stationary_cycles": minimum}


def final_artifact_name(result):
    """No status-string inference: explicit verified state is mandatory."""
    status = str(result.get("status", ""))
    if "FAILED" in status or status.startswith("SOURCE_VERSION_FILE_CHANGED"):
        return None
    if result.get("final_state_verified") is not True or not result.get("final_state_hash"):
        return None
    if result.get("calibration_complete") is True:
        return "FINAL_CALIBRATED_WORKING_COPY.ver"
    return "FINAL_VERIFIED_PARTIAL_WORKING_COPY.ver"
