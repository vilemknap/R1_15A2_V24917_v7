# R1_15A2 V24917 – LONG Generation + LONG_COMPOSITE Distribution

**Vývojová větev:** `codex/v24917-unlock-long-zonal-tg-composite-td-20261030`.  
**Stav:** implementovaný opt-in, offline CI; `LIVE_VISUM_NOT_RUN` až do nového živého testu.  
**Výchozí implementace:** `codex/v24917-school-fp-link-guard-20261030` (`e161a78ef69c71a7759bf3c0d5a42c879aa062ed`).

## 1. Dva jednoznačně oddělené optimalizační mechanismy

### LONG Trip Generation – zónové produkce/atrakce

Mění pouze zónové parametry `ADD_PROD_L(z)` a `ADD_ATT_L(z)`. Pro návrh používá již existující `r1_15a2_long_cache_generation_v24917.py`, `r1_15a2_long_zonal_fit_v24917.py` a sdílenou aktuální `NATIVE_CL` OD/path/profile incidence. Řeší reziduum sčítacích profilů po WORK/SERVICE a bezpečně zmrazeném SCHOOL, vázané zónové kroky, P/A vyrovnání a příslušné mobility bandy.

Důležité: příspěvek `M9305` na profil je **lokální lineární návrh**, nikoliv domnělý analytický derivát TG→TD→20A→20B. Každý návrh musí projít **skutečným nativním** přepočtem, podporou LONG 80+ km, 12D/11D a původní akceptací / rollbackem. Nový readback navíc požaduje, aby se skutečně změnily hodnoty finálního vozidlového LONG OD `M9305`; pouhá změna ADD koeficientů nestačí. Při chybě nebo neúplné path-incidence se LONG zónové kroky stále fail-closed odloží.

`ADD_PROD_L` je v aktuální mobility authority ukotven na referenci `0.30`, s mezemi `0.15…0.45` a tvrdým maximem 10 % na jeden LONG kandidát. `ADD_ATT_L` má run-start referenci. Původní AMDY Tabulka 13 však obsahovala pro diaľkové cesty původně pevný člen `0.2`, nikoliv koeficient `ADD_PROD_L`; bez dodatečného ověření **skutečné** vazby `ADD_PROD_L → FP_3_LONG_*` ve zdrojovém .ver nebude zónová optimalizace plně funkční. Stejně nutno ověřit `ADD_ATT_L → FA_3_LONG`. Neprovádíme žádné automatické přepisování originálního .ver ani nativních produkčních formulí. V případě chybějící vazby není správné vypnout `MOBILITYZONE1`; její odmítnutí je bezpečná diagnostika.

### LONG Trip Distribution – společné `LONG_COMPOSITE` b/c

Jeden agregovaný IDP/AMDY referenční cíl `LONG_COMPOSITE`, **512 bodů** pro podmíněnou vzdálenost **100–200 km**, pro všech pět LONG vstupních matic `9111…9115`:
- společné `Δb` pro všech pět nezávislých výchozích `b_i`;
- jeden společný násobitel `c_i · exp(Δlog(-c))`, při `c_i < 0`;
- `a` je fixní; jednotlivé LONG vrstvy nedostávají pět nezávislých CDF cílů.

Nový výběr `LONG_COMPOSITE` do již existujícího W/S target poolu funguje také při TARGETED hledání i při `GLOBAL_IDP_FALLBACK`. Vlastní původní V24916 FineCDF modul a jeho chráněný SHA256 zůstaly **byte-identical**. Aktivace je na aditivní V24917 vrstvě pomocí kontextového předání vybraných cílů do původního referenčního loaderu. Všechny globální FineCDF metriky a hard akceptační pravidla zůstávají.

Nové LONG TD záměrně vyžaduje `DYNAMIC` a `TDJOINT1`: po každém návrhu `b/c` musí následovat nativní TD→20A/20B→OSRM LONG mask→OP17→OP18→OP19→OP20→nové skimy a **živě změřené** počty na kalibračních profilech. Reálné intenzity, nikoliv staré frozen-flow incidences, vstupují do 60% count + 40% IDP společného skóre; akceptace vždy až původní live GEH/11D kontrolou a rollbackem. To je výpočetně náročnější a neověřeno na Windows COM.

Podpora LONG: `M9697` = fixní OSRM, hranice **≥80 km**, nulový objem pod hranicí po maskování; objem mezi 80–100 km a nad 200 km je legální, 512bodová křivka 100–200 km podmíněná, bez přerozdělení ztraceného objemu. M9305 je **FORMULA**, nikoli datová matice pro `SetValues`. Zápisy do FORMULA jsou stále zakázané; skutečná source forma M9291–9295 se kontroluje živě.

## 2. Přesné přepínače

V této větvi `R1_RUN_OPTIONS.json` obsahuje:

```json
"long_generation_enabled": true,
"long_composite_td_enabled": true,
"td_joint_enabled": true,
"td_inner_mode": "DYNAMIC",
"td_count_weight": 0.6
```

Nové parametry `long_generation_enabled`, `long_composite_td_enabled` jsou nezávislé opt-in, výchozí hodnoty v `r1_15a2_demand_policy_v1.py` zůstávají FALSE pro zpětnou kompatibilitu. LONG TD bez `TDJOINT1` či bez `DYNAMIC` se odmítá ještě před zásahem do COM.

## 3. Bezpečné spuštění a diagnostika

1. Zdejší ZIP rozbalit **samostatně**, neprohazovat jednotlivé moduly se staršími balíčky.
2. Ve Visumu 2026 otevřít ověřený originál `R1_novy_start.ver`, nikoli neúspěšnou pracovní kopii.
3. Spouštět `01_SPUSTIT_V24917_TDJOINT1_SILENT.py`, který ukládá neskrývaný chybový stav a `R1_15A2_SILENT_DEBUG/SILENT_LATEST_DEBUG.zip`. Silent se týká Python informačních oken; nativní Visum dialogy nepřebírá.
4. Ověřit `BASELINE_FULL_RECOMPUTE`, masku a všechna OP17–20, poté **pouze omezený test** jedné změny LONG P/A a jedné společné LONG b/c, včetně nového assignmentu/skims, GEH/11D a rollbacku. Teprve po těchto důkazech dlouhý kalibrační běh.
5. Relevantní evidence: `TDLONG_COMPOSITE_TARGET_SCOPE.json`, `TDJOINT_SUMMARY.json`, `LONG_MASK_EXECUTION_PLAN.json`, `LONG_MASK_RESULT.json`, `LONG_SHARED_CACHE_INCIDENCE.json`, `LONGGUARD1_PARENT.json` a `SILENT_LATEST_DEBUG.zip`.

**Prozatím neprohlašujeme skutečnou kalibrační odezvu LONG ani finální konvergenci.** Offline testy kontrolují integraci, ale nenahrazují Windows COM / skutečný postup VISUM.
