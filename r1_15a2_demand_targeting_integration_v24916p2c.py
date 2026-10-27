"""Controller-independent hook protocol for staged V24916 activation.

The existing PERF2C controller remains the owner of state transitions. This
module supplies three explicit hook boundaries only; it performs no COM writes.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class V24916FeatureFlags:
    enabled: bool = False
    shadow_mode: bool = True
    generation_targeting_enabled: bool = False
    td_mask_enabled: bool = False
    combined_enabled: bool = False

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> "V24916FeatureFlags":
        s = dict(cfg.get("performance", {}).get("v24916_flowbundle_skim", {}))
        return cls(**{k: bool(s.get(k, getattr(cls(), k))) for k in cls.__dataclass_fields__})


class DemandTargetingHooks:
    """Narrow hook facade; safe no-op when disabled."""
    def __init__(self, adapter: Any, config: Mapping[str, Any]):
        self.adapter = adapter
        self.flags = V24916FeatureFlags.from_config(config)

    def before_generation_apply(self, rows: Sequence[Any], target_zone_nos: Sequence[int], **fields: Any):
        if not self.flags.enabled or not self.flags.generation_targeting_enabled:
            return list(rows), {"status": "FEATURE_OFF", "hook": "BEFORE_GENERATION_APPLY"}
        return self.adapter.v24916_target_generation_rows(rows, target_zone_nos, **fields)

    def before_finecdf_active_set(self, ordered_components: Sequence[str], pressure_by_component: Mapping[str, float]):
        if not self.flags.enabled or not self.flags.td_mask_enabled:
            return list(ordered_components), {"status": "FEATURE_OFF", "hook": "BEFORE_FINECDF_ACTIVE_SET"}
        return self.adapter.v24916_select_td_components(ordered_components, pressure_by_component)

    def after_fresh_candidate_assignment(self, evidence_identity: Any):
        # Deliberately read-only. Acceptance remains with the parent controller.
        return {
            "status": "SHADOW_EVIDENCE_BOUNDARY",
            "hook": "AFTER_FRESH_CANDIDATE_ASSIGNMENT",
            "identity_hash": getattr(evidence_identity, "identity_hash", None),
            "acceptance_authority_changed": False,
        }
