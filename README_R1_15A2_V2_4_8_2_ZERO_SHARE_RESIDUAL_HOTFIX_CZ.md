# R1 15A2 V2.4.8.2 — zero-share residual hotfix

Release: `R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016`

This release is a narrow live-run hotfix on top of verified CP11/V2.4.8.1. It addresses the real `NATIVE_CW:1:7` blocker observed on 2026-10-16.

## What changed

A live-positive off-diagonal OD can already have enumerated path geometry while all saved DSeg path volumes are zero. V2.4.8.1 treated this as a mandatory re-enumeration. The real run proved that a fresh enumeration can return the identical path basis and the same zero-share condition.

V2.4.8.2 therefore:

- still forces re-enumeration when path geometry is genuinely absent;
- never invents a route split for zero-share relations;
- keeps zero-share OD volume in projection base marginals;
- excludes that relation from sparse path-guidance variables only if the aggregate zero-share residual for the DSeg is <= the existing DSeg path-volume parity tolerance (1%);
- fails closed if that tolerance is exceeded or path parity did not pass;
- leaves candidate acceptance unchanged: fresh Visum assignment + live 12D/11D diagnostics remain authoritative.

## Live evidence

V2.4.8.1 failed at `NATIVE_CW 1→7`. Fresh epoch hashes were identical to the restored epoch. For NATIVE_CW the unresolved interzonal residual was 11.7431 vehicles = 0.01014%, versus the existing 1% path parity tolerance.

## Run

Open the accepted baseline `.ver` and run `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_2.py` manually from Visum Scripts > Execute script file. The persistent cache in `%LOCALAPPDATA%\R1_15A2_PATH_CACHE_V248` is reused.

This package has not been executed against real Visum in this environment; production_ready remains false until the next live gate passes.
