"""V24916 FlowBundle/skim overlay adapter on the current PERF2C adapter.

Feature-off behavior is inherited exactly from r1_15a2_trial_adapter_v24915p2c. No parent method is
overridden unless an explicit V24916 hook is called by a certified controller.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence

from r1_15a2_trial_adapter_v24915p2c import VisumAdapter as _Perf2CVisumAdapter
from r1_15a2_demand_evidence_v24916p2c import BoundedDemandEvidenceManager
from r1_15a2_demand_targeting_hooks_v24916p2c import (
    apply_generation_positive_damping,
    recompute_generation_post_target_summary,
    select_td_components,
)
from r1_15a2_skim_v24916p2c import shortest_imp_oracle_enabled


class VisumAdapter(_Perf2CVisumAdapter):
    """Additive adapter; parent behavior is exact when V24916 is disabled."""

    def __init__(self, visum: Any, cfg: Mapping[str, Any], control: Any = None):
        super().__init__(visum, cfg, control)
        section = dict((cfg or {}).get("v24916_flowbundle_skim_runtime") or (cfg or {}).get("performance", {}).get("v24916_flowbundle_skim", {}))
        self.v24916_config = section
        self.v24916_enabled = bool(section.get("enabled", False))
        self.v24916_shadow_mode = bool(section.get("shadow_mode", True))
        self.v24916_generation_targeting_enabled = bool(section.get("generation_targeting_enabled", False))
        self.v24916_td_mask_enabled = bool(section.get("td_mask_enabled", False))
        self.v24916_combined_enabled = bool(section.get("combined_enabled", False))
        self.v24916_evidence = BoundedDemandEvidenceManager(max_entries=int(section.get("max_evidence_entries", 4)))
        # Explicitly reject the uncertified shortest-IMP activation.
        shortest_imp_oracle_enabled(section)
        self.v24916_fresh_baseline = dict((cfg or {}).get("v24916_fresh_baseline", {}))
        self.v24916_lineage_context = dict((cfg or {}).get("v24916_lineage_context", {}))
        self.v24916_force_fresh_path_epoch = bool(
            self.v24916_lineage_context.get("fresh_recovery_path_epoch_required", False)
            or self.v24916_fresh_baseline.get("force_fresh_path_epoch", False)
        )

    def _try_persistent_restore(self, diag, folder, snapshot, links, settings, seq):
        """Fresh EE baselines deliberately do not inherit a historical path epoch.

        This is narrower than disabling the persistent cache itself: the current
        run still publishes its newly enumerated immutable SQLite epoch and can
        reuse it later within the new lineage.  Only cross-run restore/import is
        suppressed at lineage start.
        """
        if self.v24916_force_fresh_path_epoch:
            from r1_15a2_two_mode_v238 import atomic_json
            from pathlib import Path
            atomic_json(Path(folder) / "V24916_FRESH_BASELINE_PATH_CACHE_POLICY.json", {
                "schema": "R1_15A2_V24916_FRESH_BASELINE_PATH_CACHE_POLICY_V1",
                "status": "HISTORICAL_RESTORE_SKIPPED_FRESH_ENUMERATION_REQUIRED",
                "state_hash": snapshot.get("state_hash"),
                "cross_run_restore_attempted": False,
                "legacy_import_attempted": False,
                "persistent_publication_after_fresh_enumeration": True,
            })
            return None
        return super()._try_persistent_restore(diag, folder, snapshot, links, settings, seq)

    def v24916_feature_state(self) -> dict[str, Any]:
        return {
            "enabled": self.v24916_enabled,
            "shadow_mode": self.v24916_shadow_mode,
            "generation_targeting_enabled": self.v24916_generation_targeting_enabled,
            "td_mask_enabled": self.v24916_td_mask_enabled,
            "combined_enabled": self.v24916_combined_enabled,
            "shortest_imp_oracle_enabled": False,
            "acceptance_authority_changed": False,
            "flowbundle_role": "READ_ONLY_TARGETING_AND_EVIDENCE_ONLY",
            "skim_role": "READ_ONLY_TARGETING_CONTEXT_ONLY",
        }

    def v24916_target_generation_rows(
        self,
        rows: Sequence[Any],
        target_zone_nos: Sequence[int],
        *,
        zone_field: str = "zone_no",
        delta_field: str = "delta",
    ):
        if not self.v24916_enabled or not self.v24916_generation_targeting_enabled:
            # Exact feature-off path: preserve values and order.
            return list(rows), {"status": "FEATURE_OFF", "row_count": len(rows)}
        factor = float(self.v24916_config.get("generation_outside_positive_factor", 0.25))
        targeted, audit = apply_generation_positive_damping(
            rows,
            target_zone_nos,
            outside_positive_factor=factor,
            zone_field=zone_field,
            delta_field=delta_field,
        )
        summary = recompute_generation_post_target_summary(
            targeted,
            zone_field=zone_field,
            delta_field=delta_field,
        )
        return targeted, {"status": "TARGETED", "audit": audit.__dict__, "post_target_summary": summary}

    def v24916_select_td_components(
        self,
        ordered_components: Sequence[str],
        pressure_by_component: Mapping[str, float],
    ):
        if not self.v24916_enabled or not self.v24916_td_mask_enabled:
            return list(ordered_components), {"status": "FEATURE_OFF", "selected": list(ordered_components)}
        selected, audit = select_td_components(
            ordered_components,
            pressure_by_component,
            max_active_components=int(self.v24916_config.get("td_max_active_components", 4)),
            minimum_pressure=float(self.v24916_config.get("td_minimum_pressure", 0.0)),
        )
        return selected, {"status": "TARGETED", "audit": audit.__dict__}
