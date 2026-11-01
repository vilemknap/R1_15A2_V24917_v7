# Scénáře 2025–2070: opravená pracovní místa a fallback na 2022 (V2)

Aktuální revize z 1. 11. 2026 používá **nově dodané opravené sešity 2040, 2050, 2060 a 2070**, list `vstupy_prod_att_R1`. Ověřeny jsou správné veličiny i roky: NUM_PM a NUM_PM_SMEAR nyní odkazují na své příslušné prognózní horizonty. Evidence je v `validation/CORRECTED_WORKPLACES_EVIDENCE.json`. Historický audit v `artifacts_scenario_zero_audit_20261101` popisuje staré vstupy před touto opravou.

## Pravidlo fallbacku

Pro všech pět let a všech 14 importovaných raw atributů platí:

- **Kladná platná prognózní hodnota:** importovat ji beze změny, i když je malá nebo nižší než 2022.
- **Prognóza přesně 0 a reference 2022 >0:** použít původní nenulovou hodnotu 2022.
- **Chyba, prázdná, záporná nebo nečíselná prognóza:** použít referenci 2022. Je-li reference nulová, zůstane nula.
- **Prognóza 0 i reference 0:** ponechat nulu, nejde o fallback nenulové hodnoty.

Tím se podle rozhodnutí uživatele obnoví i malé původní hodnoty, například POP_ZP 4 místo prognózní nuly. Pravidlo se týká zónových atributů; strukturální nuly nákladních OD matic se nemění. Zónová data se nezaokrouhlují.

Referenci skript **uloží před prvním zápisem** z otevřené kopie kalibrovaného modelu 2022. Soubor je v roční složce `reference_2022/<hash_cesty_modelu>.json`. Je svázán s konkrétní .ver, NO zón a úplným raw snímkem a má kontrolní SHA. **Další importy používají stejnou referenci, nepovažují předchozí prognózu za nový rok 2022.** Přepočet a export kontrolují její nezměněný obsah.

První import nové instalace proto vždy spusť v nové roční kopii z 2022. Při opakování zachovej `reference_2022`, `logs` a `IMPORT_CURRENT.json`. Když aktualizuješ existující starší instalaci V1 ve stejné složce, lze referenci obnovit z nejstarší úspěšné předimportní zálohy pro stejnou .ver. Pokud záloha chybí, skript před zápisem zastaví import a vyžádá novou kopii 2022. Z již přepočtené prognózy se reference automaticky nevytvoří, pokud existuje záznam předchozího importu.

## Co spustit ve Visumu

Rozbal **celý GitHub ZIP** a zachovej strukturu. `scenario_tools` musí zůstat vedle původních `r1_15a2_*.py`. Ve Visumu se používá stávající objekt Visum/COM; skripty nevytvářejí novou instanci, nenačítají ani neukládají .ver samy.

Pro každý rok vytvoř přes Save as samostatnou .ver **vždy z kalibrovaného 2022**, s daným rokem v názvu, například `R1_2040_PRACOVNI.ver`. Nespouštěj nástroje souběžně s kalibrací. Ve složce `scenario_tools/ROK` spusť postupně:

1. `01_IMPORT_ZONES_AND_FREIGHT_ROK.py` — ihned po preflightu zapíše raw atributy a LNV/NV, zachová kalibraci, ověří zpětné čtení. Pak ulož vlastní .ver.
2. `02_RECOMPUTE_TG_TD_AND_ASSIGNMENT_ROK.py` — původní TG, jednotné TD, LONG maska, 20A/20B a přiřazení/skimy. Po PASS ulož vlastní .ver.
3. `03_EXPORT_MATRICES_ROK.py` — vytvoří novou složku `EXPORT_<datum_čas>` se třemi maticemi a manifestem. Předchozí export nepřepíše.

Místo ROK zvol 2025, 2040, 2050, 2060 nebo 2070. Například pro 2040 se používá `01_IMPORT_ZONES_AND_FREIGHT_2040.py`. Výstupem jsou `R1_2040_OA_CAL_WORK.mtx`, `R1_2040_LNV.mtx`, `R1_2040_NV.mtx` a `EXPORT_MANIFEST.json`.

Když Visum drží Python moduly jiné kopie balíčku, přepočet ohlásí `PRELOADED_MODULE_FROM_OTHER_PACKAGE`. Ulož scénář po importu, znovu spusť Visum a otevři tuto uloženou scénářovou kopii. Staré moduly se za běhu nemažou. Launchery kontrolují vlastní SHA, přepočet také původní runtime manifest.

## Zónové vstupy a protokoly

Mapuje se podle **OSRM_MATRIX_ID/NO**, nikoli názvu nebo pořadí. Vyžadováno je přesně 681 zón NO 1..681. Zápis používá jejich skutečné COM klíče. Allowlist raw atributů:

`NUM_VS, NUM_PUP, POP_ZP, E_C, E_NC, NE_C, NE_NC, PRENOC_SVK, AV_INCOME, NUM_PM, NUM_PM_SMEAR, NUM_PUP_PLACES, NUM_STUD_VS_PLACES, POP_CENTRALITY_TERM`.

Všechny čtyři nově dodané prognózní sešity jsou nyní hlavním zdrojem svých let, **včetně 2070**. Starší samostatný výpis 2070 a staré CSV 2040 již jejich hodnoty nepřebíjejí. Numerické zdroje a SHA jsou v `INPUT_SOURCES.json` a ročních `SCENARIO.json`.

2025 nadále používá dříve dodaný samostatný výpis a AV_INCOME z pracovního sešitu 2025. Posledních pět raw atributů v něm chybí, takže je nechá z 2022; nový opravený sešit 2025 nebyl dodán. Z pracovních Excelů se neimportují kalibrační ADD_*/ZAHR_* koeficienty. Zachovají se i ADD_SALARY, TD a/b/c, ADDVAL1 a definice operací.

V `logs/.../FALLBACKS_KEPT_2022.json` je **každý skutečný fallback**: zóna, atribut, prognózní hodnota nebo značka chyby, reference 2022, použitá hodnota a důvod. `REFERENCE_2022.json` v témže logu dokládá původ reference. Původní stav a nákladní matice se zálohují před zápisem. Statická `ZONE_SOURCE_FALLBACKS.csv` popisuje chybné/prázdné zdrojové buňky; nuly proti nenulové živé referenci doplní importer do skutečného protokolu.

Náhled podle dříve dodaného exportu 2022 z 31. 10. (živý protokol může při odlišné referenci mít jiné počty):

| Rok | Nuly nahrazené kladnou referencí | Chybějící/chybné vstupy s ponechanou referencí | Celkem fallback buněk |
| --- | ---: | ---: | ---: |
| 2025 | 6 | 3898 | 3904 |
| 2040 | 116 | 1 | 117 |
| 2050 | 105 | 53 | 158 |
| 2060 | 105 | 52 | 157 |
| 2070 | 105 | 52 | 157 |

Podrobný náhled je v `validation/FALLBACK_2022_PREVIEW.csv`, souhrn a kontroly v `validation/FALLBACK_AUDIT.json`. V náhledu nezůstala žádná nula proti kladné referenci 2022 a žádná kladná platná prognózní hodnota se nezměnila. Podezřelé koeficientové měřítko NUM_PM_SMEAR z předchozí verze vstupů už v těchto čtyřech opravených zdrojích nebylo nalezeno.

## Nákladní matice a export

Nadále **MC_MEAN zaokrouhlené po OD buňkách na celá vozidla**, při polovině nahoru (Decimal ROUND_HALF_UP), bez dalšího vyrovnávání objemu. Původní a výsledné součty i odchylky jsou v SCENARIO.json. Nákladní CSV zůstala bajtově shodná s předchozím balíčkem:

| Rok | LNV | NV |
| --- | ---: | ---: |
| 2025 | 25 769 | 35 769 |
| 2040 | 30 922 | 43 560 |
| 2050 | 32 951 | 46 530 |
| 2060 | 35 996 | 50 848 |
| 2070 | 40 046 | 56 498 |

Zapisují se pouze existující DATA matice LNV a NV, žádné heuristiky podle starého součtu. OA se pro export sčítá v NumPy ze 12 unikátních komponentních DSeg matic. Formát je Visum `$O`, **vozidla/den**. LNV/NV jsou celočíselné, OA má 6 desetinných míst pro zachování drobných toků. Do modelu se kvůli exportu nepřidává další DSeg či agregovaná matice. RPDI→den/večer/noc zde dosud není aplikováno.

## Přepočet a chybové stavy

Použit původní v7 mechanismus `r1_15a2_long_post_td_mask_v24917.execute_sequence`, tedy OSRM 9697 / R1_OSRM_DIST_KM **≥80 km bez horní meze**, po TD i po 20A/20B, s povoleným úbytkem objemu a bez renormalizace. Zachován je původní rozsah assignmentů 17/18/19/20 a ověřuje se finální GAP ≤0,005. Původní ACTIVE příznaky se vracejí zpět. Kontroluje se shoda agregace 9305 s komponentami 9291–9295.

Při částečné chybě importu se obnoví celý vlastněný předimportní stav a ověří se jeho obsah. Neověřený rollback znamená ruční znovuotevření uložené kopie. Selhání nativního přepočtu nevytvoří PASS a blokuje export; model se automaticky neobnovuje přes LoadVersion. V případě chyby je třeba ručně otevřít uloženou scénářovou kopii.

Export vyžaduje aktuální V2 import a úspěšný přepočet. Ověří referenci, model, raw a kalibrované hodnoty, TD parametry, ADDVAL1, operace, zóny, LONG podporu a otisky matic. Výstupy se publikují jako celá sada atomicky; rozpracovaný export nemůže získat PASS manifest. Žádný skript neposílá výstupy dalším lidem.

## Ověření

Přesné příkazy, výsledky testů a SHA jsou ve `validation/CHECKS.json` a `SCENARIO_TOOLS_SHA256.json`. Pokryté jsou opravené zdroje, nulové i chybové fallbacky, neměnnost reference při opakování, migrace zálohy V1, částečné COM zápisy/rollback, zastaralé důkazy, LONG support a export. **LIVE_VISUM_NOT_RUN**: zde není Windows COM ani otevřený model; offline testy nenahrazují živý běh. Původní kalibrační knihovny a jejich runtime/release manifesty zůstávají beze změny.
