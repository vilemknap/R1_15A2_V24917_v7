"""Reduced-evidence targeting support for V24916/PERF2C."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping, Sequence
import hashlib, json, math

from r1_15a2_demand_support_v24916 import *  # noqa: F401,F403
from r1_15a2_flowbundle_v24916p2c import ReducedFlowBundle

SCHEMA = "R1_15A2_V24916_PERF2C_DEMAND_SUPPORT_V1"


def _hash(v: Any) -> str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class GenerationTargetSet:
    zone_nos: tuple[int, ...]
    pressure_by_zone: tuple[tuple[int, float], ...]
    source_profiles: tuple[str, ...]
    target_hash: str


@dataclass(frozen=True)
class TDComponentPressure:
    pressure_by_component: tuple[tuple[str, float], ...]
    active_families: tuple[str, ...]
    diagnostic_only_components: tuple[str, ...]
    pressure_hash: str


def build_generation_target_zones(
    reduced_by_profile: Mapping[str, ReducedFlowBundle],
    residual_by_profile: Mapping[str, float],
    *,
    max_zones: int = 128,
    minimum_positive_residual: float = 0.0,
) -> GenerationTargetSet:
    """Build positive-pressure zones from reduced NATIVE FlowBundle evidence.

    Residual <= 0 contributes no upward Generation pressure. Profiles absent
    from evidence are ignored rather than guessed.
    """
    pressure: dict[int,float]={}
    used=[]
    for profile in sorted(residual_by_profile):
        residual=float(residual_by_profile[profile])
        if not math.isfinite(residual):
            raise ValueError(f"V24916_PROFILE_RESIDUAL_NONFINITE:{profile}")
        if residual <= float(minimum_positive_residual):
            continue
        red=reduced_by_profile.get(profile)
        if red is None or red.total <= 0:
            continue
        used.append(str(profile))
        # Allocate pressure by origin+destination contribution, normalized by total.
        for zone, o, d in zip(
            [z for z in _zone_order_from_reduced(red)],
            red.origin_totals,
            red.destination_totals,
        ):
            share=(float(o)+float(d))/(2.0*float(red.total))
            pressure[int(zone)]=pressure.get(int(zone),0.0)+residual*share
    ranked=sorted(pressure.items(),key=lambda kv:(-kv[1],kv[0]))[:max(0,int(max_zones))]
    # Return canonical zone-number order for stable membership while preserving ranking in pressure rows.
    zones=tuple(sorted(z for z,_ in ranked))
    payload={'zones':zones,'pressure':ranked,'profiles':used}
    return GenerationTargetSet(zones,tuple((int(z),float(v)) for z,v in ranked),tuple(used),_hash(payload))


def _zone_order_from_reduced(red: ReducedFlowBundle) -> tuple[int,...]:
    # The reduced payload intentionally stores no full matrix. Zone identities can
    # be recovered from retained rows only when complete; production callers must
    # pass zone order separately. This helper is kept fail-closed.
    zones=sorted({int(o) for o,_,_ in red.retained_od}|{int(d) for _,d,_ in red.retained_od})
    if len(zones)!=red.n_zones:
        raise RuntimeError("V24916_REDUCED_EVIDENCE_NEEDS_EXPLICIT_ZONE_ORDER")
    return tuple(zones)


def build_generation_target_zones_with_order(
    reduced_by_profile: Mapping[str, ReducedFlowBundle],
    residual_by_profile: Mapping[str, float],
    zone_order: Sequence[int],
    *,
    max_zones: int=128,
    minimum_positive_residual: float=0.0,
) -> GenerationTargetSet:
    zones=tuple(int(z) for z in zone_order)
    pressure:dict[int,float]={z:0.0 for z in zones}
    used=[]
    for profile in sorted(residual_by_profile):
        residual=float(residual_by_profile[profile])
        if not math.isfinite(residual): raise ValueError(f"V24916_PROFILE_RESIDUAL_NONFINITE:{profile}")
        if residual<=float(minimum_positive_residual): continue
        red=reduced_by_profile.get(profile)
        if red is None or red.total<=0: continue
        if len(zones)!=red.n_zones: raise RuntimeError("V24916_ZONE_ORDER_DIMENSION_MISMATCH")
        used.append(str(profile))
        for i,z in enumerate(zones):
            share=(red.origin_totals[i]+red.destination_totals[i])/(2.0*red.total)
            pressure[z]+=residual*share
    ranked=[kv for kv in sorted(pressure.items(),key=lambda kv:(-kv[1],kv[0])) if kv[1]>0][:max(0,int(max_zones))]
    selected=tuple(sorted(z for z,_ in ranked))
    payload={'zones':selected,'pressure':ranked,'profiles':used,'zone_order':zones}
    return GenerationTargetSet(selected,tuple((z,float(v)) for z,v in ranked),tuple(used),_hash(payload))


def build_td_component_pressure(
    family_pressure: Mapping[str,float],
    idp_error_by_component: Mapping[str,float],
    component_family: Mapping[str,str],
    *,
    diagnostic_only_components: Iterable[str]=(),
) -> TDComponentPressure:
    diagnostic={str(c) for c in diagnostic_only_components}
    rows=[]
    families=set()
    for comp in sorted(component_family):
        fam=str(component_family[comp]).upper()
        if comp in diagnostic or fam in {'LONG','SCHOOL','EXOG_EE'}:
            continue
        if fam not in {'WORK','SERV','SERVICE'}:
            continue
        fp=float(family_pressure.get(fam, family_pressure.get('SERV' if fam=='SERVICE' else fam,0.0)))
        err=float(idp_error_by_component.get(comp,0.0))
        if not math.isfinite(fp) or not math.isfinite(err):
            raise ValueError(f"V24916_TD_PRESSURE_NONFINITE:{comp}")
        value=max(0.0,fp)*max(0.0,err)
        rows.append((str(comp),value))
        if value>0: families.add('SERV' if fam=='SERVICE' else fam)
    payload={'rows':rows,'families':sorted(families),'diagnostic':sorted(diagnostic)}
    return TDComponentPressure(tuple(rows),tuple(sorted(families)),tuple(sorted(diagnostic)),_hash(payload))
