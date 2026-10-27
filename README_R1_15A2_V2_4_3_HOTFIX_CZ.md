# R1 15A2 V2.4.3 — overnight coupled-demand hotfix

Tato verze opravuje živý pád V2.4.2 před první kalibrační iterací.

## Co selhalo ve V2.4.2

`BASELINE_FULL_RECOMPUTE` předal novou podsložku do `execute_procseq`, ale podsložka ještě neexistovala. Zápis `20_PROCSEQ_EXECUTION.txt` proto skončil `FileNotFoundError`. Nebyla dokončena žádná demand iterace.

## Opravy

1. `r1_15a2_trial_adapter_v243.py` vždy vytvoří cílovou recompute složku před spuštěním Visum assignment/procedure sequence. Platí pro baseline, trial i rollback.
2. Nový entrypoint nevytvoří `FINAL_CALIBRATED_WORKING_COPY.ver`, pokud controller nemá ověřený `final_state_hash` nebo běh skončil chybou.
3. Kalibrační metodika V2.4.2 se nemění: společný demand cyklus `Generation -> FineCDF TD` se opakuje až 12 vnějších cyklů; vnitřní FineCDF má až 35 iterací / 180 TD vyhodnocení. ADDVAL1 je odemčen až po joint fixed point.

## Spuštění

Ve Visumu spusť přes `Scripts -> Execute script file`:

`R1_15A2_FULL_OVERNIGHT_COUPLED_V2_4_3.py`

V2.4.2 už nespouštěj.
