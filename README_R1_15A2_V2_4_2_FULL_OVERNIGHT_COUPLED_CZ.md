# R1 15A2 V2.4.2 — FULL OVERNIGHT COUPLED DEMAND

## Co je metodicky opraveno

V2.4.2 nepovažuje Trip Generation a Trip Distribution za dvě nezávislé kalibrační fáze.
Tvoří **jeden společný demand-calibration blok**.

Jeden vnější demand cyklus probíhá takto:

1. **Trip Generation / P-A kalibrace**
   - z živých CAL profilů se navrhují nové kalibrační koeficienty produkcí a atrakcí;
   - používají se existující TG aktuátory modelu:
     `ADD_PROD_W`, `ADD_ATT_W`, `ADD_SALARY`, `ADD_PROD_S`, `ADD_ATT_S`,
     `ZAHR_PROD_WORK`, `ZAHR_ATR_WORK`, `ZAHR_PROD_SERV`, `ZAHR_ATR_SERV`;
   - kandidát se skutečně zapíše do izolované pracovní kopie;
   - provede se plný downstream přepočet a assignment;
   - generation krok se hodnotí primárně podle CAL dopravních profilů / GEH. IDP zde není veto,
     protože distribuce je ihned následující subkrok stejného demand cyklu.

2. **Trip Distribution / b,c kalibrace proti IDP**
   - P/A koeficienty jsou v tomto subkroku zmrazené;
   - jako vědecká autorita je použita přesná uživatelem dodaná
     `R1_BC_AUTO_DIST_ONLY_FINECDF_PATCHED_v1_7.py`, SHA-256
     `2160f79fbd5de1645635327cb46e4a7daf6a14304af3e683d4f5dce98ebccf82`;
   - kalibruje 16 komponentních b,c; `FOREIGN` M9116 zůstává fixní;
   - primární cíl jsou původní 512bodové IDP CDF + pomocné mean-distance kritérium;
   - každý numerický krok používá native Visum Trip Distribution;
   - po nalezení nejlepšího b,c se provede celý downstream Procedure Sequence + assignment,
     aby vznikl skutečný síťový stav.

3. **Opakování společného demand cyklu**
   - po změně b,c se kalibrátor vrátí znovu k Trip Generation;
   - demand blok je konvergentní až tehdy, když v *tomtéž vnějším cyklu* není přijata
     ani změna P/A koeficientů, ani změna b,c.

4. **ADDVAL1 / route-choice kalibrace**
   - odemkne se až po společném fixed pointu TG+TD;
   - během supply fáze jsou TG a TD parametry zmrazené;
   - každý kandidát ADDVAL1 je ověřen skutečným finálním assignmentem op20 a živými intenzitami;
   - dvourežimová path cache slouží jen k návrhu kandidáta, ne jako acceptance authority.

Schéma:

```
BASELINE full recompute
   ↓
┌──────────── SPOLEČNÝ DEMAND CYKLUS ────────────┐
│ TG: nové P/A kalibrační koeficienty            │
│        ↓                                        │
│ full downstream + assignment                   │
│        ↓                                        │
│ TD FineCDF: b,c proti 512bodovým IDP           │
│        ↓                                        │
│ full downstream + assignment                   │
└────────────── ↺ dokud TG i TD stojí ───────────┘
   ↓
ADDVAL1 / route choice / op20
   ↺ do konvergence nebo časového limitu
   ↓
FINAL working-copy state
```

## Důležitá odlišnost od samostatné v1.7

Dodaná v1.7 je distribution-only kalibrátor a ve svém vlastním standalone rollbacku může obnovovat
výstupní matice. V integrované V2.4.2 se její vědecká a optimalizační logika zachovává, ale **nepoužíváme
přímý SetValues zápis výsledných OD matic**. Rollback TD probíhá:

`obnovit b,c → znovu spustit native TD → numericky ověřit regenerované matice`.

Tím zůstává integrovaný noční runner v režimu bez přímých OD write operací.

## Ochrany běhu

- Původní vstupní `.ver` se nekalibruje přímo. Běh nejprve vytvoří `WORKING_START.ver`.
- `LoadVersion` se nepoužívá pro candidate rollback.
- Zamítnutý kandidát se vrací obnovením kalibrovaných parametrů a reálným přepočtem.
- Při neověřeném rollbacku se běh zastaví fail-closed.
- Všech 498 pozorování zůstává samostatných; CAL/VALID role se nemění.
- `epsilon = 0.005` zůstává zachováno.
- Celá eligible linková síť je dostupná pro supply kalibraci. `max_edges=12` je pouze lokální limit
  velikosti jednoho ADDVAL1 trialu, nikoli globální limit počtu linků kalibrovaných za noc.
- Globální noční rozpočet je 36 000 s (10 h).
- Pokud čas/STOP nastane dřív, než je společný demand blok konvergentní, **ADDVAL1 se neodemkne**.
- `STOP_REQUESTED` lze vytvořit v aktivním `RUN_...` nebo v nadřazené runs složce.

## Jak spustit

1. Nepoužívej V2.4.0 ani V2.4.1.
2. Rozbal celý ZIP do samostatné složky.
3. Otevři ve Visumu 2026 správnou uloženou baseline `.ver` s funkční Procedure Sequence.
4. Nespouštěj současně jinou kalibraci v téže instanci Visumu.
5. Přes **Scripts → Execute script file** spusť:

```
R1_15A2_FULL_OVERNIGHT_COUPLED_V2_4_2.py
```

Nezařazuj master skript jako operation do Procedure Sequence.

Výstupy vzniknou vedle vstupní `.ver` v:

```
R1_15A2_V2_4_2_FULL_OVERNIGHT_COUPLED_DEMAND_RUNS/RUN_.../
```

Průběh sleduj přes `00_PROGRESS.json`, konečný stav přes `00_RESULT.json` a
`00_FINAL_STATUS.txt`.

## Co ráno poslat zpět

Primárně:

- `00_RESULT.json`
- `CALIBRATION/RUN_STATUS.json`
- poslední `DEMAND_CYCLE_XX_RESULT.json`
- `CALIBRATION/DEMAND_CONVERGED.json`, pokud vznikne
- `CALIBRATION/SUPPLY_ROUTE_CHOICE/RUN_STATUS.json`, pokud se supply fáze odemkla
- případné `ROLLBACK_*.json` / chybový log

Velkou SQLite route cache není nutné posílat, pokud si ji výslovně nevyžádám.

## Stav validace balíku

Offline/regresní validace není náhradou živého Visum běhu. V2.4.2 zatím nebyla kompletně odjeta
na produkčním PTV Visum 2026. První noční běh je proto současně první živý integrační test této
coupled-demand orchestrace.
