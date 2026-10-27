"""State-bound, bounded FlowBundle/skim evidence for V24916 over PERF2C.

No cross-run persistence is implemented. Evidence is valid only for an exact
identity including assignment and path-basis data.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, asdict
from typing import Any, Callable, Mapping, MutableMapping, Optional
import hashlib
import json

from r1_15a2_demand_evidence_v24916 import *  # noqa: F401,F403
from r1_15a2_flowbundle_v24916p2c import FlowBundleEvidenceIdentity, ReducedFlowBundle, canonical_hash
from r1_15a2_skim_v24916p2c import SealedSkimIdentity

SCHEMA = "R1_15A2_V24916_PERF2C_DEMAND_EVIDENCE_V1"


@dataclass(frozen=True)
class DemandEvidenceSnapshot:
    schema: str
    identity: FlowBundleEvidenceIdentity
    flowbundles: tuple[tuple[str, ReducedFlowBundle], ...]
    skim_identity: SealedSkimIdentity
    target_payload: Mapping[str, Any]
    complete: bool
    payload_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "identity": asdict(self.identity),
            "flowbundles": [(k, v.as_dict()) for k, v in self.flowbundles],
            "skim_identity": self.skim_identity.as_dict(),
            "target_payload": dict(self.target_payload),
            "complete": self.complete,
            "payload_hash": self.payload_hash,
        }

    def verify(self) -> None:
        if not self.complete:
            raise RuntimeError("V24916_EVIDENCE_INCOMPLETE")
        payload = {
            "schema": self.schema,
            "identity": asdict(self.identity),
            "flowbundles": [(k, v.as_dict()) for k, v in self.flowbundles],
            "skim_identity": self.skim_identity.as_dict(),
            "target_payload": dict(self.target_payload),
            "complete": True,
        }
        if canonical_hash(payload) != self.payload_hash:
            raise RuntimeError("V24916_EVIDENCE_PAYLOAD_HASH_MISMATCH")


class BoundedDemandEvidenceManager:
    """Small in-memory LRU keyed by the complete state identity.

    The cache is scoped to a single Python/Visum run. It stores only reduced
    FlowBundle payloads and therefore never owns full OD matrices.
    """

    def __init__(self, *, max_entries: int = 4):
        self.max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[str, DemandEvidenceSnapshot] = OrderedDict()
        self.capture_count = 0
        self.hit_count = 0
        self.miss_count = 0
        self.invalidate_count = 0

    def clear(self, reason: str = "UNSPECIFIED") -> None:
        self._entries.clear()
        self.invalidate_count += 1

    def get(self, identity: FlowBundleEvidenceIdentity) -> DemandEvidenceSnapshot | None:
        key = identity.identity_hash
        snap = self._entries.get(key)
        if snap is None:
            self.miss_count += 1
            return None
        try:
            snap.verify()
        except Exception:
            self._entries.pop(key, None)
            self.miss_count += 1
            raise
        if snap.identity != identity:
            self._entries.pop(key, None)
            self.miss_count += 1
            return None
        self._entries.move_to_end(key)
        self.hit_count += 1
        return snap

    def publish(
        self,
        *,
        identity: FlowBundleEvidenceIdentity,
        flowbundles: Mapping[str, ReducedFlowBundle],
        skim_identity: SealedSkimIdentity,
        target_payload: Mapping[str, Any],
    ) -> DemandEvidenceSnapshot:
        ordered_fb = tuple(sorted(((str(k), v) for k, v in flowbundles.items()), key=lambda kv: kv[0]))
        payload = {
            "schema": SCHEMA,
            "identity": asdict(identity),
            "flowbundles": [(k, v.as_dict()) for k, v in ordered_fb],
            "skim_identity": skim_identity.as_dict(),
            "target_payload": dict(target_payload),
            "complete": True,
        }
        snap = DemandEvidenceSnapshot(
            schema=SCHEMA,
            identity=identity,
            flowbundles=ordered_fb,
            skim_identity=skim_identity,
            target_payload=dict(target_payload),
            complete=True,
            payload_hash=canonical_hash(payload),
        )
        snap.verify()
        key = identity.identity_hash
        self._entries[key] = snap
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        self.capture_count += 1
        return snap

    def require_current(self, identity: FlowBundleEvidenceIdentity) -> DemandEvidenceSnapshot:
        snap = self.get(identity)
        if snap is None:
            raise RuntimeError("V24916_EVIDENCE_NOT_CURRENT")
        return snap

    def telemetry(self) -> dict[str, int]:
        return {
            "V24916_EVIDENCE_CAPTURE_COUNT": self.capture_count,
            "V24916_EVIDENCE_HIT_COUNT": self.hit_count,
            "V24916_EVIDENCE_MISS_COUNT": self.miss_count,
            "V24916_EVIDENCE_INVALIDATE_COUNT": self.invalidate_count,
            "V24916_EVIDENCE_CACHE_ENTRIES": len(self._entries),
        }
