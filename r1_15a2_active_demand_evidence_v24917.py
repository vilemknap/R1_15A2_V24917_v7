# -*- coding: utf-8 -*-
"""V24917 fix of the V24916 active FlowBundle evidence builder.

Defect in r1_15a2_active_demand_evidence_v24916p2c.ActiveDemandEvidenceBuilder.build:
``self.manager.publish(..., skim_identity=dist, ...)`` referenced an undefined
name ``dist``.  Every evidence build therefore raised NameError after all the
FlowBundle COM work had been done; Generation targeting fell back to
GLOBAL_PATH_ONLY_FALLBACK and the TD component mask to GLOBAL_IDP_FALLBACK in
every cycle.  Passing the dynamic skim epoch directly would also fail, because
DemandEvidenceSnapshot requires ``skim_identity.as_dict()``.

The sealed V24916 file stays byte-identical (runtime manifest unchanged).  This
subclass publishes the snapshot with a small identity object wrapping the
current DynamicSkimEpoch summary.  Everything else is inherited.
"""
from __future__ import annotations

from pathlib import Path
import math
from typing import Any, Mapping

import r1_15a2_active_demand_evidence_v24916p2c as base


class EpochSkimIdentity:
    """Hashable, JSON-ready skim identity built from DynamicSkimEpoch.summary()."""

    def __init__(self, epoch: Any):
        summary = epoch.summary() if hasattr(epoch, "summary") else {
            "epoch_hash": str(getattr(epoch, "epoch_hash", getattr(epoch, "identity_hash", ""))),
        }
        self._payload = dict(summary)
        self.epoch_hash = str(self._payload.get("epoch_hash", ""))

    def as_dict(self) -> dict:
        return dict(self._payload)

    def __eq__(self, other):
        return isinstance(other, EpochSkimIdentity) and other._payload == self._payload

    def __hash__(self):
        return hash(self.epoch_hash)


def safe_td_target_plan(plan: Mapping[str, Any]) -> dict:
    """Fail to GLOBAL_IDP_FALLBACK instead of making unsupported TD selections.

    The sealed V24916 target builder is intentionally not edited.  This layer
    applies solely to the evidence published by V24917 and retains the full
    FineCDF fallback when no positive network attribution is available.
    """
    out = dict(plan or {})
    def positive_finite(value):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return False
        return math.isfinite(number) and number > 0.0

    pressure = out.get("family_pressure") or {}
    evidenced = {str(fam) for fam, info in pressure.items()
                 if positive_finite((info or {}).get("evidence_weight", 0.0))}
    positive = {str(row.get("component")) for row in out.get("alignment_rows", []) or []
                if str(row.get("family")) in evidenced
                and positive_finite(row.get("alignment_score", 0.0))}
    selected = [str(c) for c in out.get("active_components", []) or [] if str(c) in positive]
    out["active_components"] = selected
    out["targeting_evidence_families"] = sorted(evidenced)
    out["status"] = "ACTIVE" if selected else "GLOBAL_IDP_FALLBACK"
    out["reason"] = ("POSITIVE_FLOWBUNDLE_EVIDENCE" if selected else
                     "NO_POSITIVE_FLOWBUNDLE_EVIDENCE" if not evidenced else
                     "NO_POSITIVE_ALIGNED_COMPONENT")
    out["safetyfix1_no_zero_evidence_targeting"] = True
    out["global_11d_evaluation_required"] = True
    return out


class _PublishProxy:
    """Manager proxy that substitutes the undefined ``dist`` at publish time."""

    def __init__(self, manager: Any, builder: "ActiveDemandEvidenceBuilder"):
        self._manager = manager
        self._builder = builder

    def publish(self, **kwargs):
        kwargs["skim_identity"] = EpochSkimIdentity(self._builder._v24917_epoch)
        # SAFETYFIX1: sanitize the TD mask at the production publication
        # boundary, keeping the sealed V24916 evidence/math file byte-exact.
        # With zero family weight the legacy score is zero and an >= 0
        # threshold used to select alphabetical components as if attributed.
        payload = dict(kwargs.get("target_payload") or {})
        if "td_targets" in payload:
            payload["td_targets"] = safe_td_target_plan(payload["td_targets"])
            kwargs["target_payload"] = payload
        return self._manager.publish(**kwargs)

    def __getattr__(self, name):
        return getattr(self._manager, name)


class ActiveDemandEvidenceBuilder(base.ActiveDemandEvidenceBuilder):
    def build(self, diag: Mapping[str, Any], context: Mapping[str, Any], folder: Path,
              snapshot: Mapping[str, Any]):
        self._v24917_epoch = self._distance_epoch()
        real_manager = self.manager
        proxy = _PublishProxy(real_manager, self)
        # The inherited body references the bare global ``dist`` only as the
        # keyword argument value; provide it as the epoch so the name resolves,
        # and let the proxy replace it by a valid identity object.
        base.dist = self._v24917_epoch
        self.manager = proxy
        try:
            return super().build(diag, context, folder, snapshot)
        finally:
            self.manager = real_manager
            try:
                del base.dist
            except AttributeError:
                pass

    @classmethod
    def from_parent(cls, parent: base.ActiveDemandEvidenceBuilder) -> "ActiveDemandEvidenceBuilder":
        obj = cls.__new__(cls)
        obj.__dict__.update(parent.__dict__)
        return obj


__all__ = ["ActiveDemandEvidenceBuilder", "EpochSkimIdentity", "safe_td_target_plan"]
