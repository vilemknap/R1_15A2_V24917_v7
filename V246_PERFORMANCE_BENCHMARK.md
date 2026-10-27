# R1 15A2 V2.4.6 performance benchmark

Status: **PASS_OFFLINE_EVIDENCE_ONLY**

## Measured offline synthetic controller

| Metric | V2.4.5 | V2.4.6 |
|---|---:|---:|
| assignment/recompute calls | 21 | 18 |
| accepted states | 3 | 4 |
| demand cycles | 3 | 3 |

Call reduction in this fixture: **14.3%**.
The final adaptive state is identical: **false**.
That difference is expected and explicitly acknowledged; it is not a regression by itself.

## Derived request-count reductions

- Path paging: 126,500 -> 15,813 requests if page 2048 is supported (87.5% fewer).
- Link reads: 74,583 -> 8,296 COM calls in the verified bulk design (88.9% fewer).

These are call-count derivations, not real PTV Visum wall-time measurements.

## Truth boundary

No real PTV Visum 2026 execution was performed in this environment. The first live run must use telemetry and compare quality, accepted states, rollback integrity and wall time against CP03.
