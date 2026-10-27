# DŮLEŽITÉ: COMPLETE R2

Tento balík je runtime-complete revize `V24912_COMPLETE_R2`. Policy je vložena přímo v `r1_15a2_core.py`; live běh již nezávisí na pozdním importu `r1_15a2_guard_policy_v24912`. Před prvním zápisem launcher automaticky vytvoří a ověří `V24912_RUNTIME_BUNDLE_PREFLIGHT.json`.

# Live Visum acceptance — V2.4.9.12

Tato release **není** označena jako live-Visum otestovaná. Offline replay používá skutečné V2496 before/after diagnostiky, ale nenahrazuje nový Visum běh.

První live run musí znovu potvrdit native IPF, fresh trip generation / trip distribution, assignment, 12D/11D, parameter readback, rollback a semantic checkpoint integrity.

Očekávaný první průlom podle replay: Generation scale 1.0 nebo při TD realization scale přibližně 0.25. TD 0.5 má zůstat reject kvůli CAL cost >5 % a dalším severity hard/budget porušením.
