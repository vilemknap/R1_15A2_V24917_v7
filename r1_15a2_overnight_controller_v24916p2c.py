"""Additive V24916 controller overlay over r1_15a2_overnight_controller_v24915p2.

No parent state-machine function is overridden in P0/P1. Certified hooks are
exposed separately and must be explicitly wired after live shadow acceptance.
"""
from r1_15a2_overnight_controller_v24915p2 import *  # noqa: F401,F403
from r1_15a2_demand_targeting_integration_v24916p2c import DemandTargetingHooks, V24916FeatureFlags
from r1_15a2_trial_adapter_v24916p2c import VisumAdapter


def build_v24916_hooks(adapter, config):
    return DemandTargetingHooks(adapter, config)
