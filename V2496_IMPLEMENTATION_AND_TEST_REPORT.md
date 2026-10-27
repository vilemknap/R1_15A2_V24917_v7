# V2.4.9.6 implementation and test report

## Scope

Release V2.4.9.6 implements a stage-dependent acceptance regime for the first
eight coupled-demand outer cycles. The change is intentionally limited to
accept/reject policy and checkpoint authority. Demand mathematics, Visum-native
procedures, path export, restart semantics and parameter realization are
inherited.

## Implemented modules

- `r1_15a2_core.py`
  - early policy resolver;
  - continuous GEH20/30 severity metrics;
  - early catastrophic-only protected guard;
  - early GEH20/30 soft, GEH35 warning, GEH40 hard transition guard;
  - any-positive and nonmonotonic Generation acceptance paths.
- `R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py`
  - early TD Pareto acceptance;
  - 0.25% minimum selected improvement;
  - 5% CAL degradation cap;
  - 1.5 benefit/cost floor;
  - 20% component trade-off caps.
- `r1_15a2_supply_visum.py`
  - acceptance scope is passed explicitly; Supply is excluded from early mode.
- `r1_15a2_overnight_controller_v240.py`
  - shared-objective monotonicity bypass is restricted to explicitly reviewed
    nonmonotonic Generation acceptance.
- `r1_15a2_overnight_controller_v242.py`
  - runtime cycle/scope binding;
  - dedicated immutable best-so-far checkpoint and pointer;
  - current exploratory and best-so-far identities remain separate.
- `r1_15a2_safety_v2496.py`
  - exact policy locks, parent provenance and implementation hashes.
- launcher/config/tests/verifier/documentation for V2.4.9.6.

## Safety boundary retained

The early mode does not weaken:

- observation-set identity and observed values;
- CAL/VALID roles;
- coefficient envelopes and P/A consistency;
- frozen link, dseg, operations, ADDVAL, Generation and TD context;
- native IPF tolerance;
- fresh assignment and live 12D/11D authority;
- rollback/readback fail-closed behavior;
- semantic restart;
- same-range transient COM retry;
- direct OD write prohibition.

Catastrophic early guards are new GEH40, single-profile increase above 15,
absolute GEH above 60 and a previously protected GEH<5 profile reaching GEH20.

## Test coverage

Focused tests cover:

- tiny positive Generation improvement;
- nonmonotonic severity-improving Generation step;
- 2% Generation degradation cap;
- GEH20/30 soft, GEH35 warning, GEH40 hard;
- single-profile and absolute ceiling guards;
- protected-profile catastrophic guard;
- live-like 5.5% TD benefit / sub-1% CAL cost;
- scale-0.25-like TD benefit / approximately 2.6% CAL cost;
- benefit/cost rejection;
- 5% TD CAL cap;
- exact cycle-9 fallback;
- shared-objective bypass restriction;
- dedicated best-so-far checkpoint rotation;
- release safety and predecessor pins.

Pre-package results:

- focused: 71 passed;
- complete inherited + V2496 suite: 743 passed;
- compileall: PASS.

Final package gate additionally runs manifest verification, independent
mechanical policy reproduction, full pytest from a clean extraction, tamper
failure and cloud byte readback.

## Truth boundary

The release is offline-tested only. It is not production-ready and has not yet
completed a bounded real PTV Visum COM acceptance run.
