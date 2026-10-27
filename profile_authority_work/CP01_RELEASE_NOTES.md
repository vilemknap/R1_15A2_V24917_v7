# R1 15A2 V2.4.5 / CP01 — checkpoint publication hardening

Status: **OFFLINE_REGRESSION_PASS / LIVE_VISUM_NOT_RUN**.

This is a bounded, additive continuation of the readback-verified CP00 V2.4.5.
It is not a new numerical model and does not claim completed real R1 calibration.

- Fixed the write ordering in `r1_15a2_overnight_controller_v240.py`: the supplementary rotating SLOT pointer is written/read back *before* publishing canonical `LATEST_ACCEPTED_CHECKPOINT.json`.
- On a pointer-publish exception, best-effort recovery restores the old SLOT without changing canonical LATEST; no .ver file is auto-deleted before both pointers have published.
- Added five atomicity regressions injecting failures before/after a SLOT write and before a LATEST write, plus successful recovery.
- Added `VERIFY_CHECKPOINTS_V245_CP01.py`, a read-only CLI verifier. It validates slot parity, canonical/slot consistency, `.ver` path containment, nonzero file size, and SHA-256 of actual bytes. Orphan .ver files are reported but never deleted.
- Added five negative/positive verifier tests (bad payload, mismatched pointer, escaped path, orphan, two-slot).

Test evidence: **532 passed** on Linux synthetic/COM-shaped fixtures; compileall PASS.
Actual PTV Visum 2026 COM, 681-zone network, native assignment, Windows GUI, overnight resource-stress, and full R1 convergence remain **NOT RUN**.

Before running the real calibration: extract the **complete** CP01 source tree in a new directory, do not mix it with CP00/V2.4.4, and keep CP00 as rollback authority. After a Windows run, use:

```
python VERIFY_CHECKPOINTS_V245_CP01.py "C:\path\to\RUN_...\CALIBRATION"
python VERIFY_CHECKPOINTS_V245_CP01.py "C:\path\to\RUN_...\CALIBRATION\SUPPLY_ROUTE_CHOICE"
```

Important: the Google Drive CP00/CP01 ZIPs in this conversation are **development source backups**, not the active Windows `.ver` runtime checkpoints. Mirroring Windows runtime `.ver` files requires access to the workstation or a separately configured Google Drive sync destination.
