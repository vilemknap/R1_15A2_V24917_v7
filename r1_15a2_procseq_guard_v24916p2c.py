"""Procedure Sequence guard for V24916 shadow/targeting integration."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping, Sequence
import hashlib, json

SCHEMA = "R1_15A2_V24916_PERF2C_PROCSEQ_GUARD_V1"


def _hash(v: Any) -> str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode()).hexdigest()


@dataclass(frozen=True)
class ProcedureSequenceGuardResult:
    passes: bool
    inventory_hash: str
    forbidden_active_scripts: tuple[Mapping[str, Any], ...]
    checked_operations: int


def guard_candidate_sequence(
    operations: Sequence[Mapping[str, Any]],
    *,
    allowed_script_ids: Sequence[str] = (),
) -> ProcedureSequenceGuardResult:
    allowed={str(x) for x in allowed_script_ids}
    forbidden=[]
    canonical=[]
    for i,op in enumerate(operations):
        row={
            'index':int(op.get('index',i)),
            'type':str(op.get('type',op.get('operation_type',''))),
            'active':bool(op.get('active',False)),
            'id':str(op.get('id',op.get('comment',op.get('name','')))),
        }
        canonical.append(row)
        typ=row['type'].upper()
        if row['active'] and ('SCRIPT' in typ or typ in {'PYTHON','JAVASCRIPT'}) and row['id'] not in allowed:
            forbidden.append(row)
    return ProcedureSequenceGuardResult(
        passes=not forbidden,
        inventory_hash=_hash(canonical),
        forbidden_active_scripts=tuple(forbidden),
        checked_operations=len(canonical),
    )
