# LONG OD→profil incidence — čtecí offline kandidát

**Stav:** `OBSERVED_LONG_OD_PROFILE_ONLY` + `LOCAL_LINEAR_PROPOSAL_ONLY`, `LIVE_VISUM_NOT_RUN`. Modul `r1_15a2_long_profile_incidence_v24917.py` tvoří z předaných uložených tras `NATIVE_CL` a jejich průchodů linkami OD→profil expozici podle stejného pravidla, které WORK/SERVICE používají pro PrT path/path-link seznamy. Předané řádky musí být ze skutečného oficiálního exportu; zde je k dispozici jen syntetický test, nikoli aktuální `NATIVE_CL` trasy. Navazující lokální fit je pouze diagnostický a nezasahuje do aktivní kalibrace.

## Skutečný zdroj a výpočet

- Aktivní WORK/SERVICE základ `r1_15a2_core.build_actual_path_incidence()` počítá pro každou uloženou trasu průchod profilem včetně násobnosti. Nativní `NATIVE_CL` je v seznamu možných osobních segmentů, ale v současné konfiguraci `R1_15A2_CONFIG_V2_4_9_6.json` není v `path_export_dsegs` ani `mutable_dsegs`. Pro reálný LONG audit je proto potřeba samostatný **read-only** export této vrstvy; nepřidávat ji automaticky do měnitelných segmentů.
- Nový čistý modul přijímá pouze `NATIVE_CL` path/path-link řádky, schválené profily, osu zón, výslednou vozidlovou OD M9305 a pět vozidlových komponent M9291–M9295 po 20B. Vyžaduje shodu součtu komponent s M9305 po každé buňce a shodu součtu uložených tras s M9305 pro každý mezizónový pár. Kladné mezizónové trasy bez linků, osiřelé linky, chybné směry profilů, záporné/neúplné matice a nesprávný segment odmítá. Diagonální objem vykazuje zvlášť, protože nemusí mít síťovou trasu.
- Pro profil `p` a OD `o,d` je současná expozice `A[p,o,d] = Σ_trasa objem_trasy × počet průchodů profilem`. Komponentový průchod se získá z pozorovaného podílu `M929k[o,d]/M9305[o,d]`; pět komponent se musí na každém profilu sečíst na celkový LONG průchod. Výstup nese existující `ordered_zone_hash()` a `matrix_values_hash()`. Všechny hash hodnoty jsou diagnostické pro předaná data; bez živého načtení a shody assignment/path epochy nejsou autoritou aktuálního Visum stavu.

## Hranice interpretace

Výstup je **pozorované přiřazení vozidel k profilům pro jeden konzistentní vstupní snapshot**. Dodaný 19B V5 je pouze čtecí audit kandidáta κ: mapuje R1 zóny na rodičovské AMDY zóny a váží OD převod pomocí R1 osobních matic a pásem M9001. Dodaný 20A V2 popisuje realizační krok: v každé z pěti LONG komponent násobí OD buňky M9111–M9115 komponentově a pásmově specifickou κ podle **M9001**, s auditovaným komponentovým fallbackem při malé chybějící podpoře kontraktu, a zapisuje M9191–M9195. Samostatný 20B V7 pak z M9191–M9195 tvoří M9291–M9295 pomocí `BOUNDED_IPF`; finální M9305 musí odpovídat součtu pěti složek. κ není globální násobitel CL ani `2.8` z generační formule. Předané skripty ukazují zamýšlenou metodiku, ale samy nedokládají právě načtenou proceduru ve Visumu.

Citlivost produkčního koeficientu v zóně vyžaduje ještě průchod přes nativní TG/TD, právě popsaný převod `9111–9115 → 9191–9195`, směrově omezený návratový 20B `9191–9195 → 9291–9295` a finální `9305`. Samotný podíl komponent v M929x neprokazuje derivaci této sekvence. Živě se musí ověřit také skutečné vzorce 20B/9305 a totožná epocha tras a matic; dodaný TG export tyto trasy ani matice neobsahuje. Proto výstup nikdy neplní klíč `long_zone_profile_incidence` aktivního LSGEN a `long_generation_permitted` je vždy `False`. Navíc zůstává neověřený nativní filtr LONG OD párů `distance >= 100 km`.

## Navazující lokální zonální fit podle principu WORK/SERVICE

`r1_15a2_long_zonal_fit_v24917.py` nyní nad pozorovanou LONG incidencí staví čistý diagnostický návrh. Pro zónové log kroky `u_o` (produkce) a `v_d` (atraktivita) používá stejný první řád jako aktivní W/S:

`Δq_od/q_od ≈ u_o + v_d − g_LONG`, kde `g_LONG = 0.5×(Σ P_o u_o/P_total + Σ A_d v_d/A_total)`, a `ΔF_p ≈ Σ_od A[p,od]×(u_o+v_d−g_LONG)`.

`P/A` základ se bere z celé aktuální M9305 včetně intrazonálních cest, které nemají profilovou trasu; normalizace proto odpovídá celému LONG objemu. Profilové řádky, identita a váhy se přebírají z W/S problému; po jeho předpovědi se fituje zbylé reziduum. Solver je tentýž ohraničený `r1_15a2_zonal_count_fit_v24917.solve()`: tvrdá lineární bilance P/A, přesná oprava změn `exp(log_step)`, ridge a nulový krok u zón bez přímé expozice. Zónové meze se musí dodat explicitně z aktuálního referenčního a mobilitního kontraktu; modul si je nevymýšlí a nevydává žádné aplikační `candidate_rows`.

Je to **stejná lokální aproximace**, jakou W/S používají k výběru pokusu, nikoli analytická derivace celé TG→TD→20A→20B sekvence. Přesný účinek musí ověřit skutečný pokus ve Visumu; zejména 20B může změnu rozdělit mezi oba směry. `fit()` proto vždy vrací `LOCAL_LINEAR_PROPOSAL_ONLY`, `long_generation_permitted=False` a `native_filter_verified=False`. Aktivní LSGEN/adapter nejsou novým modulem zapojeny a nadále LONG zmrazují.

Export TG z momentálního modelu obsahuje `ADD_PROD_L = 4.38341115316211` ve všech 681 zónách; projektová pevná reference je `0.2`. Případný návrat na základní hodnoty se nesmí předpokládat, dokud nebude doložen aktuální snapshot po rollbacku.

## Ověření

`PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_long_profile_incidence.py tests/test_v24917_tdlong1_mask.py tests/test_core_deep.py tests/test_v24917_runtime_install.py` — **44 PASS, 0 FAIL**. Syntetické testy zahrnují opakovaný průchod linkou, obousměrný profil, rozklad pěti komponent, intrazonální objem a odmítnutí chybných zdrojů. Kompilace změněných souborů a `git diff --check` prošly. Projektový nástroj zapečetil 65/65 runtime souborů a ověřil 1 059 neměnných zdrojů. Testy neprokazují běh ve Visumu.

Po doplnění lokálního fitu: `PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_long_zonal_fit.py tests/test_v24917_long_profile_incidence.py tests/test_v24917_mobilityalloc1_solver.py tests/test_v24917_tdlong1_mask.py tests/test_v24917_runtime_install.py` — **36 PASS, 0 FAIL**. Testy ověřují přesný tvar normalizované matice `G`, zahrnutí intrazonálního objemu, reziduum po W/S, omezený solver, nelineární P/A, nulový krok bez expozice a odmítnutí chybné osy/profilu. Aktuální zapečetění je 66/66 runtime souborů; 1 059 původních zdrojů zůstalo beze změny.

Další ohraničený krok: na cílovém PC čtecím exportem získat `NATIVE_CL` path/path-link seznam a ve stejné assignment/path epoše M9291–M9295 a M9305; po kontrole parity lze změřit skutečnou OD→profil expozici a prověřit lokální zonální predikci na malém živém pokusu. Samostatně je nutné doložit nativní LONG filtr, obnovu rodiče a případný rollback `ADD_PROD_L` na základní hodnotu.
