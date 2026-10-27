# Live Visum acceptance — V2.4.9.6

V2.4.9.6 je bounded trial release (`production_apply = false`). Spusťte jej v
nové Visum session z uživatelem zvoleného accepted checkpointu. Nepoužívejte
neověřený in-memory stav po pádu.

## Před startem

1. Nechte aktuální V2.4.9.4 běh korektně skončit nebo jej ukončete pouze přes
   bezpečný cooperative stop.
2. Otevřete poslední zvolený accepted `.ver`.
3. Spusťte
   `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_6.py` přes
   **Scripts → Execute script file**.
4. Raw SHA `.ver` není cross-run acceptance podmínka; semantic fingerprint ano.

## Povinné live kontroly

### Generation

- cycles 1–8 reportují `active_acceptance_stage = EARLY_EXPLORATION`;
- malé skutečné zlepšení weighted mean GEH může projít bez 0.1% minima;
- nemotónní přijetí je povoleno pouze při CAL zhoršení ≤2 % a prokázaném
  severity zlepšení;
- takové přijetí musí mít
  `exploration_nonmonotonic_accepted = true` a explicitní acceptance path;
- observation authority, P/A konzistence, coefficient envelopes a
  apply/readback zůstávají hard.

### Trip distribution

- minimum aggregate selected TD improvement je 0.25 %;
- maximum CAL weighted-mean-GEH degradation je 5 %;
- při kladné CAL ceně musí benefit/cost dosáhnout alespoň 1.5;
- GEH20/30 jsou v early stage soft diagnostics;
- GEH35 se reportuje jako warning;
- nový GEH40, single jump >15, absolute GEH >60 nebo protected <5 → >=20 jsou
  hard reject;
- `LONG_COMPOSITE` musí zůstat jedinou LONG acceptance komponentou;
- IPF tolerance se nesmí uvolnit.

### Checkpointy

Po každém accepted stavu ověřit:

- nový běžný accepted checkpoint + semantic sidecar;
- `current_exploratory_checkpoint` ukazuje na aktivní stav;
- `BEST_SO_FAR_CHECKPOINT.json` existuje a jeho `.ver` je fyzicky oddělený;
- best-so-far se změní pouze při zlepšení fixed-reference shared objective;
- nonmonotonic exploratory krok nesmí odstranit předchozí best checkpoint,
  dokud není nový best pointer durable.

### Fallback

V outer cycle 9 musí report přepnout na inherited V2.4.9.5 acceptance:

- Generation minimum 0.1 %;
- TD CAL degradation max. 0.5 %;
- GEH20 hysteresis budget;
- nový GEH30 opět hard zero-tolerance.

## Fail-closed podmínky

Běh se nepovyšuje na real-Visum PASS při:

- selhání rollbacku nebo readbacku;
- změně observation authority či frozen contextu;
- COM chybě mimo bounded retry policy;
- chybějícím semantic sidecaru;
- nesouladu current/best checkpoint pointeru;
- uvolnění nativní IPF tolerance;
- direct OD matrix write.
