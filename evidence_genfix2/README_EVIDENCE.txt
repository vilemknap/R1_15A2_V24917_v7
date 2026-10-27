GENFIX2 final release evidence

release_checks/: final three green suites, including 18 migrated audit scenarios.
BASELINE_GENFIX1_15_FAIL_3_PASS.log: historical reproduction on unchanged input.
ORIGINAL_AUDIT_GENFIX2_17_PASS_1_EXCEPTION_CONTRACT.log: unchanged original suite.
Its A10 requires a normal return, but the safe production behavior now raises
GENFIX2_SUPPLYMIX_RECOVERY_NOT_EQUIVALENT_MANUAL_REOPEN and accepts no state.
Only A10 is migrated, with explicit exception + no-acceptance assertions.
See AUDIT_A10_CONTRACT_DIFF.patch and original source .py.txt.
No live Visum or Windows COM session was tested.
