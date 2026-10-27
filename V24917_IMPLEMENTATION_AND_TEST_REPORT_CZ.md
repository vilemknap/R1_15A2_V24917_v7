# V24917 – cílené a hrubší dorovnání objemu (TG) – implementace a testy

## Diagnóza výchozího stavu

Data pocházejí z vašeho běhu: `GENERATION_BLOCK_RESULT.json` a preview pro scale 1.0 z cyklu 1, start z `BEST_SO_FAR_0018`. Model/sčítání byl 0,265 a vážené GEH 60,1.

| Krok řetězce | SERVICE | WORK |
|---|---:|---:|
| Navedení OD převedené na marginály, produkce | +1 338 (0,65 %) | +576 (0,36 %) |
| Konzervativní P/A (bere se menší strana) | +725 | +287 |
| Měkké tlumení + strop 2,0 | 820 z 1 602 řádků tlumeno, 90–100 zón na stropu | 52–55 zón na stropu |
| Implementováno | +725 | +286 |

V součtu jde o +1 011 cest za cyklus. Součet modelu na profilech se tím posune z 680 na 683 tis., tedy o 0,4 %.

Strukturní příčina: projekce MARGINALS zachovává součty zón, nikoli účinek na profilech. Cesty zóny, které vedou mimo sčítané profily, ředí relativní změnu marginálu. Navíc rodinný globální krok působí na všechny zóny stejně.

V24916 navíc obsahovala chybu ve FlowBundle. Volání `ActiveDemandEvidenceBuilder.build` předávalo `publish(..., skim_identity=dist)`, kde `dist` není definované. Výsledkem byl NameError, a to až po všech FlowBundle COM voláních. Cílení TG i maska TD proto v každém cyklu spadly na fallback.

## Implementace (bez změny jediného souboru V24916)

| Soubor | Účel |
|---|---|
| `r1_15a2_zonal_count_fit_v24917.py` | Omezený LS fit zónových log-násobků P/A na rezidua všech CAL profilů. Používá incidenci cest a dvojitě omezený log-lineární model účinku. Zóny bez expozice zůstávají na 0. FISTA. |
| `r1_15a2_targeted_generation_v24917.py` | Politika, fáze (CATCH_UP < 0,80 ≤ REFINE), obálka [0,25; 5], režim návrhu TARGETED_ZONE_DIRECT (bez rodinného globálního kroku) a patch `r1_15a2_multiblock` v paměti. |
| `r1_15a2_trial_adapter_v24917.py` | Nahrazuje návrh rodičovského `generation_design` fitem. Preview/apply běží pod fázovým overlay. Při chybě fitu se použije původní návrh (fallback). |
| `r1_15a2_active_demand_evidence_v24917.py` | Oprava publikace FlowBundle evidence. |
| `r1_15a2_runtime_delta_v24917.py` | Konfigurace přidává pouze `v24917_targeted_generation` a `v24917_release_identity`. Validace V24916 běží nad zbytkem konfigurace. |
| `r1_15a2_v24917_runtime.py` | Instaluje: patch multiblock, nefatální TG bránu, řídké TD + předčasný konec, DIAGFAST V2 s DIRECT guardem. |
| `01_SPUSTIT_V24917_TARGETED_CATCHUP.py` | Launcher. Načte zapečetěný launcher V24916, přesměruje adaptér a delta konfigurace a doinstaluje V24917. |
| přenesené moduly | `r1_15a2_generation_gate_nonfatal_v1.py`, `r1_15a2_demand_policy_v1.py`, `r1_15a2_diagfast_*`, `helpers/R1_1?D_DIAGFAST_V1.py` |
| manifesty | `DIAGFAST_V1_BASE_MANIFEST.json`: 1 059 původních souborů V24916 (SHA archivu zachováno). `DIAGFAST_V1_RELEASE_MANIFEST.json`, `V24917_RUNTIME_MANIFEST.json`. Manifest V24916 platí beze změny. |

### Model fitu

Proměnné jsou `u` (PROD) a `v` (ATT) pro každou zónu a rodinu WORK/SERVICE. Model účinku:

- Δ_p = Σ_od a_{p,od} · (u_o + v_d − g_f)
- g_f = ½ (Σ P u / P_f + Σ A v / A_f)

Minimalizuje se Σ w_p² (r_p − Δ_p)² + λ‖x‖² + μ (Σ P u − Σ A v)², za omezení lo ≤ x ≤ hi. Váhy jsou w_p = √(2·váha / max(100, obs+model)), chráněné profily (GEH < 5) mají váhu ×3. Ridge λ = 0,02·medián diagonály GᵀW²G.

Meze se počítají z aktuálních koeficientů a obálky. Ve fázi CATCH_UP platí ±(ln 1,5; ln 0,8), ve fázi REFINE limity stupňů. Nakonec proběhne zděděné P/A vyrovnání, zděděný salary joint design a brána `generation_apply_gate`.

## Testy (offline)

- Celá sada V24917 (`tests` + `diagfast_tests`): **1 194 PASS, 4 SKIP, 2 FAIL**. Obě selhání (`capsys`, MAX_PATH tmp) se stejně objevují i na nezměněném V24916 a souvisí s lokálním test runnerem (pytest zde není dostupný).
- Nové testy V24917 (18) a přenesené testy DIAGFAST/TG brány/TD politiky (138):
  - fit:
    - cílení;
    - nulová změna u neexponovaných zón;
    - snížení u přetížených zón;
    - rovnoměrné reziduum → rovnoměrný růst;
    - P/A rovnováha;
    - meze.
  - politika a fáze;
  - obálka:
    - [0,25; 5];
    - ZAHR násobek;
    - měkké pásmo v REFINE;
    - salary beze změny.
  - návrh end-to-end s reálnou konfigurací balíku:
    - koeficient nad původní strop 2,0;
    - celkový účinek ≤ +50 %;
    - brána projde.
  - fáze REFINE se stupňovým limitem a tlumením;
  - zděděný režim bez politiky nezměněn;
  - oprava FlowBundle publish;
  - delta konfigurace přidává jen 2 sekce;
  - adaptér: nahrazení návrhu, overlay a fallback;
  - launcher v izolovaném procesu:
    - všechny patche;
    - integrita DIAGFAST PASS;
    - manifest V24917 PASS;
    - manifest V24916 stále PASS.
- Syntetický test (681 zón, 487 profilů, model/sčítání 0,245): jeden fit trvá < 1 s a zasáhne 621 zón. Lineární predikce poměru je 0,245 → 0,30 za cyklus. Skutečný multiplikativní účinek +50 % je větší.

## Revize SKIMFIX1

První živé spuštění skončilo chybou `V24916_DYNAMIC_SKIM_EXPECTED_6_ACTIVE_PRT_SKIMS_FOUND_0`. Příčinou byl pevný kód `com.SKIMS_PRT = 103` ve V24916. Nový modul `r1_15a2_skim_optype_v24917.py` zjistí kód z živé sekvence procedur pouze čtením. Postup:

1. proměnná prostředí `R1_PRT_SKIM_OPERATION_TYPE`;
2. operace s COM objektem `PrTSkimMatrixParameters`;
3. jediný typ (mimo TG/TD/skript/skupina/přiřazení), který má právě 6 aktivních operací.

Kód se nastaví do `com.SKIMS_PRT` pro dané sezení. Kontrola výstupních matic DIS podle DSEG zůstává beze změny. Nový test pokrývá: živý případ, potvrzení konstanty, nejednoznačnost (selže uzavřeně), override.

## Revize D11FIX1

Živý běh 02:48 skončil při `BASELINE_DIAGNOSTICS` chybou „11D component files incomplete“. `_dynamic_11d_overlay` ve V24916 přesměrovala `summary_path` do složky `11D_DYNAMIC_ASSIGNMENT_SKIM_<label>` bez tří CSV souborů 11D. Ty ale potřebuje `build_td_signals_from_11d`.

Modul `r1_15a2_dynamic_11d_files_v24917.py` proto:

1. soubory nejdřív zkopíruje ze statického 11D běhu;
2. po rodičovském overlay přepíše souhrnné CSV dynamickými řádky;
3. přepíše také baseline CSV dynamickými podíly v pásmech (`DynamicFamilyMetrics` na čerstvých DIS skimech, pouze při přesné shodě pásem, jinak zůstanou statická pásma s auditem);
4. TD signály sestaví znovu.

Cílové podíly zůstávají beze změny. Statická kontrola nedefinovaných jmen ve všech runtime modulech našla jedinou další chybu, už opravenou `dist`.

Skim: druhý běh (02:42) potvrdil kód typu operace 103 (`V24916_CONSTANT_CONFIRMED`). Chyba z 02:28 tedy pocházela z neaktivních skimů v tehdejším .ver, detekce kódu zůstává jako pojistka.

## Revize D11FIX2

Běh `RUN_20261025_020826` prošel baseline včetně dynamického 11D. První TG kandidát (scale 1.0, WORK +34,7 tis., SERVICE +60,1 tis. cest) se zapsal a přepočítal. Diagnostika AFTER ale spadla na `WinError 3`, protože cesta k CSV souboru 11D ve složce `TRY_01\DIAGNOSTICS\11D_DYNAMIC_ASSIGNMENT_SKIM_AFTER` přesáhla MAX_PATH. Rollback byl ověřen a živý stav odpovídá poslednímu přijatému.

Oprava:

- dynamické 11D pracuje v krátké složce `%LOCALAPPDATA%\R1DF\D11\<uuid8>`, kterou lze přepsat proměnnou `R1_D11_SHORT_ROOT`;
- vyhledávání a kopírování používají rozšířené cesty (`os.walk` na `\\?\`, `critical_copy_if_file`, `critical_atomic_json`);
- výsledky se zrcadlí do stromu běhu, chyby zrcadlení se jen zaznamenají.

## Revize TDFIX1 – první živé výsledky a oprava TD

`RUN_20261025_030431` přijal 5 TG kroků:

| Cyklus | Přijatý krok | Poměr model/sčítání | Vážené GEH | Profily s GEH ≥ 20 |
|---|---|---:|---:|---:|
| start | – | 0,267 | 60,05 | 429 |
| 1 | 0,5 | 0,296 | 57,76 | 423 |
| 2 | 0,25 | 0,312 | 56,55 | 413 |
| 3 | 0,25 | 0,331 | 55,20 | 400 |
| 4 | 0,5 | 0,376 | 52,03 | 373 |
| 5 | 0,5 | 0,419 | 49,27 | 356 |

Plný krok 1,0 guardy vždy odmítly (`NEW_SEVERE_GEH_PROFILE`, `PROTECTED_PROFILE_GUARD_FAILED`). V cyklu 5 nefatální brána zachytila `GENERATION_EFFECT_PROJECTION_ERROR_TOO_LARGE`.

TD v cyklu 5 spadl na `QUALITY_OPERATION_NOT_ACTIVE_PRT`. `NoDirectMatrixWriteTDAdapter._execute_dynamic_realization` totiž četl gap až po opuštění `activate_operation_plan`. Oprava je v `r1_15a2_finecdf_gapfix_v24917.py`, metoda se nahrazuje v paměti.

Politika TD: periodický EVERY_N se ve fázi CATCH_UP vynechává (`td_during_catchup=false`), běží jen při TG plateau. U ADD_ATT_W/DOMESTIC je mez domény zúžená o 0,06 kvůli společnému salary designu.

## Stav

`real_visum_tested = false`. První živý běh ukáže skutečnou rychlost dohánění a míru zamítání velkých kroků guardy (backtracking).


## Revize ROSTER248 (25. 10. 2026)

- `r1_15a2_profile_roster_v24917.py`: nahrazuje zapečetěný seznam 488 profilů seznamem z
  `authorities/R1_PROFILE_ROSTER_V24917.json` (248 = 196 CSD + 52 CITY; tabulka 256 bez 8 profilů s nulovým modelem). Patche v paměti:
  preflight (`_profile488_authority`, `_live_profile488_compatibility`, konstanty), fresh0
  (`CURRENT_*`), DIAGFAST (`HELPERS['12D']`, `reference_namespace` s kontrolou hashe roster
  helperu), config (`expected_12d_rows/calibration/validation` = 248/248/0 + sekce
  `v24917_profile_roster`; validátor V24916 dostane config s vrácenými 488 hodnotami),
  brána 11D/12D (obal nad PROFILE488 adaptérem, ověří skutečných 248/248/0).
- `helpers/R1_12D_PROFILE_ROSTER_V24917.py` generuje `tools/build_profile_roster_v24917.py`
  z původního 12D helperu: jiné konstanty, CSV, `ROSTER_NOS`; `read_countlocations` bere
  jen roster (další CountLocations v modelu nevadí). Výpočet 12D beze změny.
- Řádky rosteru jsou byte-identické s řádky autority 488 (test).
- Volba `tg_catchup_enabled` (výchozí v balíku false): TG jen REFINE. `td_every_n_cycles` = 2.
- Testy: 1198 PASS, 2 FAIL (předexistující prostředí), 4 SKIP. Živý běh: LIVE_PENDING.


## Revize TDBLEND1 + RELAX1 (25. 10. 2026)

- `r1_15a2_td_count_blend_v24917.py`:
  - vnitřní metrika FineCDF (patch `DynamicFamilyMetrics.evaluate`): reziduum složky
    `[sqrt(0.35/J_ref)·r_idp ; sqrt(0.65/Q_ref)·q(M_ref + ΔM_c)]`, Q = vážený průměr GEH²
    s jmenovatelem zmrazeným na začátku etapy; ΔM_c lineárně z FlowBundle incidence
    (`v24917_last_incidence` z generation_design), kappa `92xx/91xx`, pásmové faktory
    `9221/9222/9225`, V_fam `9226/9222`, Symmetrize = (T+Tᵀ)/2. V režimu DYNAMIC se scitani měří
    a ΔM_c jen rozděluje změřenou změnu. Vnitřní guardy FineCDF uvolněny
    (rmse +0,03, chyba průměru +0,05).
  - `FROZEN_PATHS`: `NoDirectMatrixWriteTDAdapter.execute` spouští jen TD (izolovaná sekvence),
    epocha skimů = aktuální epocha vnějšího adaptéru.
  - vnější přijetí (`VisumAdapter.block_gate` pro `TD_FINECDF_SOFT_REFERENCE`): blend 65/35 na
    živých 12D/11D; měkké důvody původní brány nahrazeny, tvrdé ponechány; IDP max ×1,25.
  - zrychlení: `_generation_counts_cfg` (≤3 pokusy TG), `_td_realization_scales` (≤3),
    `_finecdf_budget_for_cycle` (≤60 vyhodnocení, pokračování příště).
- RELAX1 (`r1_15a2_targeted_generation_v24917.py`): REFINE krok +25 %/−20 %, měkké pásmo
  0,4–3,0, tlumení 0,5, ridge 0,01.
- Testy: 1203 PASS, 2 FAIL (předexistující prostředí), 4 SKIP. Živý běh: LIVE_PENDING.


## Revize LSGEN1 (25. 10. 2026)

- `r1_15a2_long_school_generation_v24917.py`: `activate(visum)` (spouští launcher před preflightem,
  aby všechny snapshoty měly stejný katalog) přidá ADD_PROD_L/ADD_ATT_L/ADD_PROD_SCH/ADD_ATT_SCH do
  `mb.GENERATION_ATTRS` (snapshot, reference, rollback). `design()` — druhý ohraničený LSQ na reziduu
  po fitu W/S: SCHOOL zónově přes WORK incidenci × podíl M9225/M9226 (dvojitě omezená normalizace +
  bilance P/A), LONG jeden globální krok se sloupcem NATIVE_CL objemu profilu × FP_LONG/ΣM9111..9115.
  `rows_at_scale()` řádky ke stejnému pokusu TG; adapter je zapíše po W/S (`apply_add_candidate`,
  readback) a přidá do preview.
- Bez atributů v modelu je modul neaktivní (beze změny chování).
- Testy: 1205 PASS, 2 FAIL (předexistující prostředí), 4 SKIP. Živý běh: LIVE_PENDING.

- LSSENS1: LONG/SCHOOL citlivější — krok ±10 %/cyklus, SCHOOL 0,67–1,5, LONG 0,5–2× reference,
  ridge 0,05; volby `ls_*` v R1_RUN_OPTIONS.json / env `R1_LS_*`. Testy 1206 PASS.

- AUDITFIX1 (živý běh 25. 10. 16:09, LIVE_API_PREFLIGHT_FAILED / APPROVED_COUNTLOCATION_RPDI_AND_ROLE):
  kontrola `r1_15a2_live_api_audit` počítá za „použité“ všechny 920001–920444 a aktivní 912xxx v modelu
  a porovnává je s rosterem → s 248 profily nesedí. Roster nyní auditu podstrčí proxy `com`, jejíž
  `collection_items(..., "CountLocations")` vrací jen profily rosteru (jako roster 12D helper). Jiné moduly
  beze změny. Test 1207 PASS.

- BLENDFIX1 (živý běh 25. 10. 16:26, RUN_20261025_162648_922993, FAILED po 257 s v BASELINE diagnostice):
  `AttributeError: 'types.SimpleNamespace' object has no attribute 'outer_adapter'`. Vzorec TD blendu
  (65 % sčítání / 35 % průzkum) byl napojen na `DynamicFamilyMetrics.evaluate`; tu ale volá i dynamická
  11D diagnostika (`_dynamic_11d_overlay`, `publish_dynamic_files`) s holým `SimpleNamespace(epoch)`.
  Oprava: blend jen pro živý TD bridge (`is_td_inner_bridge`), diagnostika 11D má čistou metriku průzkumu;
  selhání založení blendu → TD stage jen podle průzkumu (varování, žádný pád); selhání vnějšího blendu →
  ponechá se rozhodnutí V24916.
- Ve stejném běhu: `ModuleNotFoundError: r1_15a2_diagfast_parity_v1` v inline paritě DIAGFAST (soubor
  v balíčku je, manifest PASS) → celý běh by jel v pomalém LEGACY 12D/11D. Oprava: `importlib.invalidate_caches()`
  na startu a předem načtené líně importované moduly DIAGFAST přes absolutní cestu (`preload_modules`,
  výsledek v V24917_RUNTIME_STATUS.json → v24917.diagfast.preload).
- Testy: V24917 43 PASS (5 nových BLENDFIX1), DIAGFAST 138 PASS, V24916/FineCDF 114 PASS.

- IZPEN1 – páka na vnitrozónové cesty velkých zón (25. 10. večer):
  * Problém: b/c je společné pro všech 681 zón; 15 zón (8 okresních 611–618 + Modra 503, Močenok 578,
    Neded 481, Trstice 533, Tešedíkovo 584, Vlčany 539, Devínska N. V. 196) drží 72–99 % cest WORK+SERVICE
    uvnitř zóny, ty nikdy nejdou do sítě.
  * Model: TD 16 nativních vrstev počítá s maticí odporu M9002 = kopie M9001 (M9001 se nikdy nemění –
    κ pásma AMDY, autorita OSRM, ochrana matic). Pro vybrané zóny jen diagonála M9002 dostane přirážku
    p_z ∈ [0; 15] min. Jednorázové nastavení: `R1_ADD_INTRAZONAL_IMPEDANCE_MATRIX.py` (založí M9002,
    přepne UTILITYFUNCTION 16 vrstev, 4_FOREIGN zůstává na M9001), pak uložit .ver.
  * Výběr zón (zmrazen na startu běhu): 9101–9110, podíl vnitrozónových > 0,70 a produkce > 5000,
    plus zóny, které už přirážku mají (restart z checkpointu). Volby `iz_*` v R1_RUN_OPTIONS.json.
  * Hledání (v každém TD kroku po vnitřním hledání b/c, b/c pevné): stejný cíl 65 % sčítání / 35 % průzkum.
    Jeden sondovací běh TD (+2 min všem zónám) dá celý Jacobián – změna řádku/sloupce zóny z se přiřadí z,
    sdílené buňky napůl, zbytek vyrovnání podle |ΔT_zz|; omezený ridge Gauss-Newton krok (≤ 5 min),
    zpětné zkracování kroku na skutečných bězích TD, nejvýš 3 iterace (≈ 7–13 běhů jen operace TD).
    Mez: podíl vnitrozónových cest vybrané zóny neklesne pod 0,40 (`iz_min_intrazonal_share`).
  * Realizace: přirážka je parametr TD jako b/c – škáluje se se stejným krokem realizace
    (p = p_rodič + s·(p_cíl − p_rodič)), plné přiřazení, stejné vnější rozhodnutí 65/35, návrat při
    zamítnutí (hook `restore_td_parameters`), uložena v každém snapshotu (`v24917_iz_penalty`, state_hash
    beze změny), v checkpointu .ver je M9002. Bez nastavení M9002 je páka neaktivní (beze změny chování).
  * Chyba hledání přirážek → přirážky beze změny, běh pokračuje (V24917_IZ_SEARCH_ERROR.json).
  * Výstupy: DEMAND_CYCLE_xx_TD_FINECDF/V24917_IZ_PENALTY/V24917_IZ_SEARCH.json,
    REALIZATION/TD_REALIZATION_ATTEMPTS.json (iz_penalty_rows), konzole „R1 V24917 IZ: …“.
  * Testy: 17 nových (syntetický gravitační model: 1 i 2 velké zóny, mez podílu, mez kroku, realizace
    přijatá/zamítnutá s návratem, hooky, volby). Celkem tests 1093 PASS / 4 SKIP, DIAGFAST 138 PASS.

- IZPEN1 SETUPFIX1 (25. 10. 17:19): nastavovací skript padal `GRAVITATIONPARAMETERS: Could not find attribute
  with ID UTILITYFUNCTION` – ve Visumu 2026 je „Utility function“ atribut objektu vrstvy
  (TripDistributionDStratParameters), ne gravitačních parametrů. Skript i kalibrátor hledají odkaz nejdřív na
  objektu vrstvy, pak na gravitačních parametrech, pak podle seznamu atributů (UTIL/IMPED); když nic, vypíší
  dostupné atributy. Opakované spuštění skriptu: M9002 z prvního pokusu se pozná jako kopie a ponechá.

- ICONG1 – odpor TD ze zatížené sítě v pozdější fázi (25. 10. 17:45):
  * Dosud TD vždy počítala s pevným časem OSRM (volná síť); skimy z přiřazení sloužily jen k délkám cest
    proti průzkumu. Nově se mimo diagonálu M9002 po přechodu do pozdější fáze skládá odpor ze zatížené sítě.
  * Start: poměr model/sčítání na kalibračních profilech ≥ 0,80 (`ic_start_model_obs_ratio`), volitelně
    od cyklu `ic_start_cycle`; po startu zůstává zapnuto.
  * V každém kroku TD (před vnitřním hledáním b/c) se z aktuálního přiřazení přečte skim jedné společné
    vrstvy (`ic_skim_dseg` = NATIVE_CW: TTC tCur 9872, TT0 t0 9871; jednotky s/min se poznají samy, skim
    musí patřit k aktuální epoše přiřazení – kontrola hashe DIS):
      RATIO (výchozí): U = OSRM · clip(tCur/t0; 1; 4)   – geometrie OSRM (schválené buňky AMDY) + zpoždění
                                                           z kongesce podle Visumu
      ABSOLUTE:        U = tCur [min], omezeno na OSRM/4 … 4·OSRM
    MSA: B_nový = (1 − λ)·B + λ·U, λ = 0,5; diagonála = vnitrozónový čas M9001 (+ přirážky IZPEN1);
    buňky bez trasy zůstávají OSRM. Změna pod 0,2 % → bez zápisu (konvergováno).
  * Je to krok konzistence modelu, ne kandidát kalibrace: zapíše se, provede se plné přiřazení, nový stav
    se stane rodičem kroku TD, který hned potom přepočte b/c (a přirážky) na novém odporu. Selhání →
    návrat na rodiče. Odpor je ve snapshotu (`v24917_ic_base_sha`), návraty ho obnoví, checkpoint .ver ho
    obsahuje; restart z checkpointu ho přebírá z M9002.
  * Volby `ic_*` v R1_RUN_OPTIONS.json; výstupy V24917_CONGESTED_IMPEDANCE/…json, konzole „R1 V24917 IC: …“.
  * Testy: 8 nových (jednotky, neplatné buňky, RATIO/ABSOLUTE, start a „zůstává zapnuto“, MSA dvou kroků,
    zachování přirážek, návrat při selhání, restart, zapojení do kroku TD).

- SKIMFIX2 (25. 10. 17:43): start padal `V24917_PRT_SKIM_TYPE_NOT_IDENTIFIABLE` – v modelu je aktivních
  13 operací skimů PrT (103, pozice 24–36: C + EXOG_EE_* + šest nativních), V24916 vyžadovala přesně 6.
  Nyní stačí ≥ 6: typ 103 se potvrdí, plán skimů po přiřazení i realizace TD spouští všechny aktivní
  skimy, šest nativních matic DIS se dál ověřuje přesně podle kódu vrstvy. Test 1 nový.

- CALLSIG1 (živý běh 25. 10. 17:53, RUN_20261025_175302, pád v 1. cyklu před TG):
  `_generation_counts_cfg() got an unexpected keyword argument 'outer_cycle'` – obal TDBLEND1 (omezení pokusů TG)
  měl signaturu (cfg), řídicí smyčka volá (cfg, outer_cycle=…). Všechny obaly TDBLEND1 přijímají *args/**kwargs.
  Ve stejné kontrole nalezeno: patch V24916 volá vnitřní hledání TD přes vlastní import
  (`r1_15a2_active_controller_patch_v24916p2c.targeted_run_finecdf_inner`), takže hledání přirážek IZPEN1
  by se nespustilo – nyní je obalen i tento vstup. Nový test volá obalené funkce přesně jako řídicí smyčka
  se skutečnou konfigurací běhu (tests/data/EFFECTIVE_CONFIG_RUN_20261025_175302.json).

- AUDIT1 (25. 10. 18:15) – systematická kontrola švů mezi moduly:
  * Signatury všech obalů řídicí smyčky proti skutečným voláním (force100, patch V24916, politika TD):
    po CALLSIG1 v pořádku; test se skutečnou konfigurací běhu.
  * Funkce importované pod vlastním jménem: nalezen a opraven vstup `targeted_run_finecdf_inner` (CALLSIG1);
    návraty (`restore_td_parameters`) živý tok bere z `inplace_transaction_v24915p2`, který je obalen.
  * Opraveno: přirážky vypnuté + odpor z kongesce zapnutý → prázdný vektor přirážek shodil zápis M9002.
  * Zpevněno: párování profilů incidence ↔ konfigurace přes kanonické číslo sčítacího místa
    (920001 / '920001' / '920001.0'); konzole hlásí pokrytí („count term on N/248 profiles“), takže tichá
    ztráta vlivu sčítání v TD je hned vidět.
  * Ověřeno proti živým datům: pole `api_approved_observations` (edge_key, direction), atributy
    VOLVEH_DSEG(…,AP), existence všech matic řetězce 9101–9117, 9201–9217, 9221–9226, 9871/9872, 9002.
  * Runner v1.9: Jacobián po složkách z vlastního rezidua (delší reziduum OK), CSV zápisy ignorují nové klíče.
  * Nový integrační test celého kroku TD se skutečnými moduly (force100 + patch V24916 + TD blend + IZPEN1/ICONG1
    + politika TD, skutečná konfigurace): b/c + přirážky realizovány a přijaty 65/35, přeskočení lichého cyklu,
    přepočet odporu před TD, selhání → návrat b/c i přirážek, všechny JSON zápisy řídicí smyčky.
  * ruff (pyflakes) bez nedefinovaných jmen; pyright bez chybných přístupů k atributům modulů.

- FASTASSIGN1 (25. 10. 19:10) – rychlé přiřazení v pokusech TG (`r1_15a2_fast_trial_assignment_v24917.py`):
  * Op 20 startuje z existující zátěže (princip preloadu, potvrzeno uživatelem). Zkušební přiřazení bloku
    GENERATION proto vypne pro jedno spuštění resety (op 1, 15) a preloady (op 17–19); op 20 začíná
    z ustálené společné rovnováhy rodiče. Gap gate op 20 beze změny.
  * Návrat po pokusu, adopce vítěze, realizace TD, výchozí stav a checkpointy dál běží plným postupem
    AMDY (deterministický, hash diagnostik rodiče se reprodukuje přesně jako dosud).
  * Adopce vítěze z rychlého pokusu: kontrola shody hashe pokus↔adopce se nahrazuje novým rozhodnutím
    na plném přiřazení (block gate + sdílená cílová funkce). Nepotvrdí-li to, stav se vrátí a blok TG
    se zopakuje s plnými pokusy (`COLD_RETRY`), aby nevznikl falešný plateau.
  * Plán se odvozuje z auditovaného plánu PERF1 (u živé sekvence FULL_SEQUENCE_FALLBACK kvůli aktivním
    skimům 31–36); typy a pozice vypínaných operací se ověřují proti živé sekvenci, jinak původní plán.
  * Testy (11): živá sekvence 43 operací (plán + přepnutí ACTIVE a přesné obnovení), fail-closed při
    jiném typu, zákaz vypnutí op 20, tok pokus warm / návrat a adopce cold, opakování bloku po
    nepotvrzené adopci, vypnutí volbou, TD nikdy warm, volby, instalace na živé moduly.

- STEP1 (25. 10. 19:50) – vypočtený krok TG a přijetí na místě (`r1_15a2_step_search_v24917.py`):
  * Náhrada `force100._generation_update_once_impl` (vypínatelná `ts_enabled`). Předpověď zátěží profilů:
    lineárně z odezvy zonálního fitu + LONG/SCHOOL (`v24917_step_model` v kontextu návrhu, mapováno přes kanonické
    číslo sčítacího místa) se škálou `rho` naučenou z měření (EMA, meze 0,2–1,5), po odmítnutém pokusu sečnou.
  * Výběr s: skutečné `core.acceptance_decision` (konfigurace adaptéru, scope GENERATION) na předpovězených řádcích
    12D pro mřížku 20 hodnot; vybráno největší předpovězené zlepšení váženého GEH, guard musí projít i v s·1,15.
  * Pokus: stejné kroky jako `_evaluate_candidate` (zápis, plné přiřazení, perzistence, freeze, 12D/11D, block gate,
    sdílená cílová funkce); přijatý pokus je novým stavem (`accepted_state_changed`), odmítnutý: rodičovské parametry
    zpět zápisem COM a další pokus; plný ověřený rollback jen na konci neúspěšného bloku nebo po chybě.
  * Testy (10): model kroku lineárně/sečnou, učení rho, výběr plného kroku, guard se skutečnou konfigurací
    (chráněný profil), integrace se skutečnými funkcemi řízení: 1. pokus odmítnut → 2. ze sečny přijat
    na místě (2 přiřazení, žádný rollback, parametry složeny od rodiče), vyčerpání → jeden ověřený rollback
    na identického rodiče, chyba → rollback + NOT_A_PLATEAU, instalace a přepínač, volby, model z fitu.
- PERF3 (25. 10. 19:50) – `r1_15a2_perf_v24917.py`: odložené ZIPy pracovních složek 12D/11D u pokusů STEP1
  (odmítnutý se nezipuje, chyba zipuje), SHA-256 cache podle inode/velikosti/času + hard link BEST_SO_FAR,
  cache M9002 ve snapshotu (zneplatnění zápisem přirážek/odporu a LoadVersion, ověření každý 25. snapshot),
  měření času etap (V24917_TIMING.json pro bloky TG/TD + konzole). Testy (10) + test celého řetězu instalace
  v čistém procesu (pořadí: měření → STEP1 → FASTASSIGN1 → původní blok).

- COMBUSY2 (25. 10. 19:55) – `r1_15a2_combusy2_v24917.py`, živý pád RUN_20261025_181651 cyklus 3
  (`DIAGFAST_COM_BUSY_EXHAUSTED: com_error(-2147418111)` v 11D adopce, pak rollback spadl na `visum.Net.Zones`):
  minimální rozpočet opakování pro všechna `com_call_with_retry` (900 s, prodleva až 2 s), COM message filter
  (RetryRejectedCall, fail-open), opakování rollbacku a celého bloku TG/TD od identického rodiče (kontrola
  snapshotu). Testy (9).

- BNDGEN1 (25. 10. 20:15) – hraniční přechody X1–X31:
  * `R1_BOUNDARY_X_PA_UPLIFT_DRY_RUN.py` / `_APPLY.py`: P09F4/A09F4 16 nezahraničních vrstev zón 650–680 × FACTOR (3),
    kontrola jmen X1..X31, záloha gz JSON, readback, návrat při chybě, ochrana FOREIGN, odmítnutí opakovaného
    navýšení, bez uložení .ver.
  * `r1_15a2_boundary_generation_v24917.py`: páka (rodina, přechod) – sloučení sloupců PROD+ATT zonálního fitu
    po normalizaci rodiny, společné řešení s domácími W/S, meze fáze + obálka ZAHR ×[0,25; 5] reference,
    řádky 10 atributů na (rodina, zónu) ve stejném pokusu (náhled/zápis/snapshot/rollback), aktivace rozšiřuje
    `mb.GENERATION_ATTRS`. Volby `bd_enabled`, `bd_zones` (rozsahy "650-680").
  * Testy (11): katalog, meze, slučování sloupců a rovnováhy, společný fit zvedne podhodnocený přechod,
    řádky ve škále, aktivace, skript (nanečisto, ×3 jen přechody, ochrana FOREIGN, odmítnutí opakování,
    návrat při chybě zápisu, kontrola jmen), adaptér `_fit_with_boundary` a model kroku STEP1.

- SUPPLYMIX1 + TDCATCHUP3 (25. 10. 22:30):
  * `R1_RUN_OPTIONS.json`: `td_during_catchup = true`, `td_every_n_cycles = 3` (schváleno uživatelem).
  * `r1_15a2_supply_mix_v24917.py`: páka ADDVAL1 (route choice) v cyklech poptávky. Obal
    `force100._generation_update_once` (nejvnější, vně demand policy); po bloku TG, je-li cyklus na řadě,
    blok nabídky na přijatém rodiči: `adapter.supply_design` (V2.4.9.13 sekvence ON/OFF z uložených cest,
    dočasně `min_attribution_coverage = sp_min_attribution_coverage`), výběr jedné větve na řídicí profil
    (nejvyšší GEH, bez překryvu úseků, rozpočet úseků), sloučený kandidát na stupni žebříku,
    v DOHÁNĚNÍ jen přetížené profily. Pokus: `apply_supply` (plná validace `check_addval_change`),
    `_assign_candidate(SUPPLY_ADDVAL1)`, `assert_freeze` (matice/generace/TD beze změny, jen zapsané
    ADDVAL1), 12D/11D, `block_gate` ve scope SUPPLY_ADDVAL1 (`supply_route_choice_acceptance`, cyklus
    nabídky = vnější cyklus) + sdílená cílová funkce scitani. Přijetí na místě (`accepted_state_changed`
    phase SUPPLY, checkpoint), odmítnutí: obnova ADDVAL1 zápisem, menší krok bez profilů zhoršených na
    stejné straně; konec bez přijetí → `_rollback_candidate` (ověřený). Chyby: před zápisem záznam,
    po zápisu ověřený návrat, neshoda diagnostik po návratu → plný přepočet z rodičovských parametrů.
  * Plán PERF1 pro SUPPLY_ADDVAL1 nahrazen studeným řetězem (reset op 15 → op 20 + skupiny, skimy přes
    dynamický refresh); bez ověřitelného resetu se blok neprovede (nikdy warm op 20 → přesný návrat).
  * Volby `sp_*` (validace v `r1_15a2_demand_policy_v1.py`, prostředí `R1_SP_*`).
  * Testy (17): plánování cyklů, režim řidičů, výběr větví (jedna na profil, znaménka, práh GEH, překryv,
    rozpočet), slučování kandidáta a žebřík, studený plán (+fail-closed), integrace se skutečným gate
    a rollbackem: přijetí 1. pokusu na místě (1 přiřazení), přestřel → menší krok přijat (2 přiřazení),
    špatný směr → vyřazení profilu a přesný návrat, chyba návrhu bez zápisu, chyba přiřazení → ověřený
    návrat, plný přepočet po neshodě diagnostik, obal TG (cyklus, složka, zrušení stacionarity),
    dočasné pokrytí, volby. Řetěz instalace: SUPPLYMIX1 vně demand policy, plán označen.
  * Sada: 1190 passed, 4 skipped; diagfast_tests 138 passed.

- TDROLLBACK1 (26. 10. 00:40) – `r1_15a2_td_rollback_tolerant_v24917.py`, živý pád RUN_20261025_232921 cyklus 1
  (`V242_TD_ROLLBACK_NOT_IDENTICAL` → `V24916_FINECDF_ROLLBACK_FAILED_MANUAL_REOPEN`): obal `force100._rollback_td_all`;
  po neúspěchu přesné kontroly ověří přesný návrat parametrů (vše kromě matic/TD; TD přes `_td_expected_freeze`,
  přirážky do 1e-6) a numerickou ekvivalenci zatížení profilů (0,5 voz. / 1e-4 rel., vážený GEH 0,01); pak přijme
  přepočtený stav jako rodiče (`accepted_state_changed`), jinak původní chyba. Testy (6).

- TDSPLIT1 + SEVRELAX1 (26. 10. 01:00):
  * `r1_15a2_intrazonal_penalty_v24917._realize_with_penalty`: plán realizace = společně (měřítka TD) → jen b/c
    (1; 0,5) → jen přirážky (1; 0,5); přírůstek přirážky na zónu oříznut na `iz_max_cycle_change_min` (2,5 min);
    záznam `kind` / `selected_kind`. Volby `iz_split_realization`, `iz_max_cycle_change_min`.
  * `r1_15a2_severity_relax_v24917.py`: obal `_generation_counts_cfg` a `_td_acceptance_cfg_for_cycle`; v per-call
    konfiguraci zvýší `max_single_profile_geh_increase` na 25 a `max_high_geh_increase` na 15 (early exploration
    i supply route choice; jen uvolňuje, zapečetěná konfigurace a startovní validátory beze změny).
  * Testy (6): oříznutí přirážek, b/c samotné po odmítnutí společných, přirážky samotné, vše odmítnuto → návrat,
    uvolnění rozpočtu skutečným `core.acceptance_decision` (+17 GEH zamítnuto/přijato), instalace obou obalů.

- GATEFIT1 (26. 10. 02:10) – `r1_15a2_step_search_v24917.py`, živý pád RUN_20261026_011631 cyklus 1
  (`V245_GENERATION_TRIAL_ERROR_NOT_A_PLATEAU:GENERATION_GATE:GENERATION_PA_GAP_WORK;..._SERVICE` při kroku 0,85):
  brána `generation_apply_gate` (V2.1) se vyhodnotí na náhledu před zápisem, krok se zmenšuje ×0,75 do průchodu;
  bez průchodného kroku → `PRE_APPLY_GATE_NO_FEASIBLE_SCALE` (plato, bez přiřazení); chyba brány z `apply_generation`
  → zamítnutí a menší krok místo pádu. Testy (3).


- AUDIT1 = RBCONS1 + SEVRELAX2 (26. 10. 03:30) – kontrola konfliktů mezi hranicemi, kritérii a variantami kroku:
  * Horizont: `early_exploration_acceptance.through_outer_cycle = 12`; od cyklu 13 `core` přechází na zděděný
    kontrakt V2.4.9.5 (skok 2,0, max 3 nové GEH20, TD 1,0) a SEVRELAX1 přestal působit. `severity_relax.relax` při
    `sev_extend_early_horizon` prodlouží horizont v per-call konfiguraci na `coupled_demand.max_outer_cycles`.
    Test: stejný krok přijat v cyklu 12, zamítnut v 13, po prodloužení přijat. Volba `sev_protected_after_hard_geh`
    (0 = beze změny) pro hranici chráněných profilů.
  * `r1_15a2_rollback_consistency_v24917.py` (RBCONS1): obal `perf1.count_profile_signature` – očekávaný počet
    profilů z aktivního seznamu (`expected_12d_rows`, 248) místo zapečetěných 498, chyba čtení → `passes=False`
    (nikdy výjimka; podpis se čte i při zachycení read-back balíčku). Obal `base.rollback_and_verify` – jen při
    `INPLACE_ROLLBACK_DIAGNOSTICS_DIFFER` s přesným snímkem: nová diagnostika, porovnání (0,5 voz. / 1e-4 / GEH 0,01),
    při shodě vrací diagnostiku rodiče; neshoda snímku, jiné chyby, větší odchylka → původní chyba.
  * `intrazonal_penalty.search`: meze kroku i line-search omezeny na `p_parent ± iz_max_cycle_change_min`
    (dříve až 3 × 5 min, realizace pak ořízla na 2,5), sonda ≤ mez.
  * Prověřeno bez nálezu: STEP1 prediktor i brána používají stejnou per-call konfiguraci (vč. uvolnění),
    pořadí obalů SUPPLYMIX/demand policy vůči stacionaritě, plán SUPPLY (cold op15) vs. FASTASSIGN (jen GENERATION,
    pod STEP1 neaktivní), měřítka realizace TD, brána P/A vs. zmenšování kroku.
  * Testy: `test_v24917_rbcons_audit.py` (13), IZ mez (1), install chain rozšířen. Sada 1227 passed / 4 skipped,
    diagfast 138 passed.

- BDPA1 (26. 10. 04:30) – `r1_15a2_boundary_pa_v24917.py`, živý běh 26. 10. cyklus 1: STEP1 odmítl všechny kroky
  0,85 → 0,064 branou `GENERATION_PA_GAP_*` (relativní mezera ~1,0–1,15 nezávislá na kroku). Konflikt kritérií:
  zonální fit vyvažuje P/A celého kroku včetně sloučených hraničních proměnných BNDGEN1 (koeficient b_P − b_A),
  `_constrain_generation_projection` a `generation_apply_gate` vidí jen domácí/ZAHR řádky.
  * Adaptér ukládá okraje hraničních zón z problému před sloučením (`bd["margins"]`), náhled i zápis běží v
    `bdpa.scope(bd)`.
  * Obal `mb._constrain_generation_projection`: zděděné vyvážení jen domácí strany vypnuto (tolerance ∞), nahrazeno
    `subset_rebalance` – domácí + hraniční změny stejného měřítka, zeslabují se jen řádky tlačící přebytek
    (monotónní, smíšená znaménka řeší), hraniční kroky beze změny.
  * Obal `mb.design_generation_candidates`: `estimated_pa_delta_by_family` = domácí + hraniční (čte brána), části
    zvlášť v souhrnu. STEP1 log brány doplněn o `_internal`/`_boundary`.
  * Testy (5 + rozšíření adaptéru): živý konflikt reprodukován (bez opravy brána selže na všech měřítkách / produkce
    sražena), s opravou průchod a produkce zachována; bez okrajů beze změny.

- BALANCE1 (26. 10. 05:00) – oprava diagnózy BDPA1: živé `V24917_BOUNDARY_STEPS.json` ukazuje P ≈ A přechodů, příčinou
  je slabá měkká penalizace rovnováhy ve `zf.solve` (živě SERVICE P +63 967 / A −2 361, WORK P +31 053 / A −178).
  * `zf.solve`: `balance_mode` HARD (výchozí) – FISTA s projekcí na box ∩ nadroviny Σ P u = Σ A v po rodinách
    (`project_box_hyperplanes`, bisekce multiplikátoru, nosiče rodin disjunktní); SOFT ponechán volbou. Výstup
    `solution["balance"]`. Čas projekce na živé velikosti ~7 s / 4000 iterací.
  * `bdgen.merge_pa`: sloučená proměnná přechodu má koeficient rovnováhy 0 (P i A zóny škáluje stejně, symetrické vstupy).
  * `R1_RUN_OPTIONS.json`: `bd_enabled` false (rozhodnutí uživatele – kalibrace přechodů prozatím vypnuta).
  * Testy (3 nové): přesná rovnováha a meze, projekce na náhodných datech, návrh projde branou bez zeslabení.

- INTADDVAL1 (26. 10. 24:00) – `r1_15a2_supply_mix_v24917.py`: živě 5/5 pokusů SUPPLYMIX `ADDVAL1_READBACK_FAILED`
  (mřížka 0,5 vs. celočíselný atribut Visum, ValueType 1). `addval_integer(adapter)` čte
  `Net.Links.Attributes.ItemByKey("ADDVAL1").ValueType` (neznámý → celé číslo), `snap_integer` zaokrouhlí každou
  změnu od nuly na celé ADDVAL a přepočte identitu kandidáta. Zděděná fáze supply po cyklu 100 má stejné omezení
  (mřížka 0,5) – zatím neaktivní. Testy (2).

- LONGTRIP1 (27. 10. 00:15) – rozhodnutí uživatele: více dlouhých cest a znovu přechody.
  `bd_enabled` true, `td_count_weight` ponechán 0,65 (uživatel), nová volba `td_max_survey_degradation` (1,0–3,0, výchozí 1,25, nastaveno
  1,5) nahrazuje pevnou konstantu `OUTER_MAX_IDP_RATIO` ve vnějším rozhodnutí TD blendu. BDPA1: hraniční změna P/A
  ze středního okraje (symetrické vstupy, konzistentní s nulovým koeficientem rovnováhy ve fitu). Testy upraveny.

- MOBILITY1 (27. 10. 00:45) – `r1_15a2_mobility_guard_v24917.py`: pojistka hybnosti vůči průzkumu mobility (uživatel ±25 %).
  Z TG vzorce (FP = ADD_PROD·H·osoby/2,8) je R = ΣFP/Σ(FP/ADD_PROD) poměr modelové a průzkumové hybnosti (domácí zóny).
  Po zonálním fitu v `generation_design` se kroky produkce rodiny tlačící R ven společně zeslabí (bisekce) na hranici
  pásma; mimo pásmo se nesmí vzdalovat. Chyba čtení FP → varování, pojistka neaplikována (záznam). Volby `mg_*`.
  Testy (5). Také: `td_max_survey_degradation` vráceno na 1,25 (soulad s průzkumem).
