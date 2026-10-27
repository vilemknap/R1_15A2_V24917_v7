# PROFILE488 A0004 cycle-3 TD recovery — IOFIX1

## Scope

IOFIX1 generalizes the earlier telemetry-only Windows file-lock fix.

- Performance telemetry remains **best-effort / fail-open** because it is evidence only.
- Calibration state, rollback evidence, checkpoint pointers and path-cache metadata use **bounded retry then fail-closed** publication.
- Reviewed parent source files remain unchanged on disk; runtime bindings are patched by an overlay.

## Protected publication paths

- controller `atomic_json` (`RUN_STATUS.json`, `DEMAND_CYCLE_*`, block results, convergence evidence, checkpoint metadata);
- rollback transaction JSON evidence;
- two-mode/path-export JSON evidence;
- persistent path-cache JSON/text metadata;
- direct `os.replace` used for persistent cache directory promotion;
- helper evidence mirror publication;
- BEST_SO_FAR `.ver` temporary-copy promotion;
- performance `SUMMARY.json` and `EVENT_*.json` remain covered by the separate fail-open telemetry overlay.

All critical atomic files use unique temporary names and 16 bounded retries for transient Windows sharing/access errors (`winerror` 5/32/33 or equivalent EACCES/EPERM/EBUSY). After exhaustion the operation raises: critical state is never silently lost.

## Not silently masked

Actual `SaveVersion` failure, disk-full, permanent ACL failure, corrupt/partial `.ver`, semantic mismatch, checkpoint readback mismatch, model/COM failure, or scientific/acceptance failure remain terminal. IOFIX1 only hardens transient publication locks; it does not turn state persistence into best-effort behavior.

## Recovery boundary

The launcher still resumes from `ACCEPTED_B_0004_d26d01d6f9a5.ver`, skips already accepted generation for demand cycle 3, and resumes at the TD substep.

## Tests

- focused IO/recovery/telemetry tests: 9 passed;
- full package regression: 914 passed, 4 skipped.
