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
from collections import Counter, OrderedDict
import math
from types import FunctionType
from typing import Any, Mapping

import r1_15a2_active_demand_evidence_v24916p2c as base


class _FlowBundleReads:
    """One build, owned NumPy buffers, shared links only, at most four retained."""

    def __init__(self, builder, epoch):
        self.builder = builder
        self.epoch = self._epoch_key(epoch)
        self.authority = self._authority_key()
        self.cache = OrderedDict()
        self.hits = self.peak = self.evictions = 0
        self.shared = None

    def _shared_links(self):
        builder = self.builder
        cfg = dict(getattr(builder, "cfg", {}).get("flowbundle") or {})
        audits = base.driver_profile_audit(
            builder._profile_rows(), int(cfg.get("max_profiles", 12)),
            float(cfg.get("min_profile_geh", 10.0)),
            float(cfg.get("min_profile_abs_residual", 300.0)))
        dsegs = builder._native_dsegs()
        uses = Counter(tuple(int(x) for x in key) + (str(dseg["code"]),)
                       for row in audits if row.get("selected")
                       for dseg in dsegs if str(dseg.get("family")) == str(row["_v24916_family"])
                       for key in base.profile_directed_keys(row["_source_row"]))
        return {key for key, count in uses.items() if count > 1}

    @staticmethod
    def _epoch_key(epoch):
        return (getattr(epoch, "epoch_hash", None), getattr(epoch, "assignment_epoch", None),
                getattr(epoch, "epoch", None), getattr(epoch, "zone_order_sha256", None))

    def _authority_key(self):
        adapter = getattr(self.builder, "adapter", None)
        manager = getattr(adapter, "readback_manager", None)
        return (id(adapter), id(manager), getattr(manager, "mutation_epoch", None),
                getattr(manager, "assignment_epoch", None),
                getattr(adapter, "path_epoch_index", None),
                tuple(getattr(adapter, "zones", ())))

    def check_epoch(self):
        if (self._epoch_key(self.builder._distance_epoch()) != self.epoch
                or self._authority_key() != self.authority):
            self.cache.clear()
            raise RuntimeError("V24917_FLOWBUNDLE_READ_EPOCH_CHANGED")

    def read(self, adapter, link, dseg, code):
        self.check_epoch()
        if self.shared is None:
            self.shared = self._shared_links()
        directed = tuple(base._as_int(link.AttValue(a))
                         for a in ("NO", "FROMNODENO", "TONODENO"))
        key = directed + (str(code),)
        if key in self.cache:
            self.hits += 1
            # The sealed parent increments this counter after each request.
            # Cancel the increment for requests served without COM GetValues.
            self.builder.telemetry["FLOWBUNDLE_MATRIX_GETVALUES_COUNT"] -= 1
            self.builder.telemetry["V24917_FLOWBUNDLE_READ_REUSE_HITS"] = self.hits
            self.cache.move_to_end(key)
            return self.cache[key]
        raw = base._read_flowbundle_matrix(adapter, link, dseg, code)
        self.check_epoch()
        if key in self.shared:
            import numpy as np
            # FlowBundle.Clear/Execute may overwrite the COM producer's buffer.
            raw = np.array(raw, dtype=float, copy=True)
            raw.flags.writeable = False
            if len(self.cache) >= 4:
                self.cache.popitem(last=False)
                self.evictions += 1
            self.cache[key] = raw
            self.peak = max(self.peak, len(self.cache))
            self.builder.telemetry["V24917_FLOWBUNDLE_CACHE_PEAK"] = self.peak
            self.builder.telemetry["V24917_FLOWBUNDLE_CACHE_EVICTIONS"] = self.evictions
        return raw


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

    def __init__(self, manager: Any, builder: "ActiveDemandEvidenceBuilder", reads=None):
        self._manager = manager
        self._builder = builder
        self._reads = reads

    def publish(self, **kwargs):
        if self._reads is not None:
            self._reads.check_epoch()
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
        previous_epoch = getattr(self, "_v24917_epoch", None)
        self._v24917_epoch = self._distance_epoch()
        reads = _FlowBundleReads(self, self._v24917_epoch)
        real_manager = self.manager
        proxy = _PublishProxy(real_manager, self, reads)
        # A private function namespace injects reads into the sealed parent
        # without changing module globals used by another builder/call.
        parent = base.ActiveDemandEvidenceBuilder.build
        namespace = dict(parent.__globals__, dist=self._v24917_epoch,
                         _read_flowbundle_matrix=reads.read)
        run = FunctionType(parent.__code__, namespace, parent.__name__,
                           parent.__defaults__, parent.__closure__)
        self.manager = proxy
        try:
            result = run(self, diag, context, folder, snapshot)
            reads.check_epoch()
            return result
        finally:
            self.manager = real_manager
            reads.cache.clear()
            if previous_epoch is None:
                del self._v24917_epoch
            else:
                self._v24917_epoch = previous_epoch

    @classmethod
    def from_parent(cls, parent: base.ActiveDemandEvidenceBuilder) -> "ActiveDemandEvidenceBuilder":
        obj = cls.__new__(cls)
        obj.__dict__.update(parent.__dict__)
        return obj


__all__ = ["ActiveDemandEvidenceBuilder", "EpochSkimIdentity", "safe_td_target_plan"]
