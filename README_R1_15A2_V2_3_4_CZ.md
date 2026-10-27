# R1 15A2 V2.3.4 — náprava podle živého Visum COM preflightu

Stav: **OFFLINE_VERIFIED / LIVE_PREFLIGHT_BLOCKED**. V **živé** instalaci PTV Visum 2026 proběhla V2.3.3 read-only diagnostika 15. 10. 2026 (94 kontrol, 92 PASS, 2 FAIL). Tato verze V2.3.4 opravuje nepodloženou živou vlastnost `R1_DIRECTION` a hierarchický PrT path-link export. **V2.3.4 nebyla ve skutečném Visumu spuštěna.** Nenahrazuje skutečný test kalibrace ani žádný assignment.

## Reálná zjištění a jejich řešení

**1. `COUNTLOCATION.R1_DIRECTION`:** pro starší městské profily chybí v živém objektu, i když je `observation_direction=BOTH` pevnou součástí schválené referenční autority CSV. Přímé čtení chybějícího atributu bylo v aktivním 12D i v preflightu chybné. Nyní se pro 90 městských profilů směr `BOTH` přebírá POUZE z uzamčené CSV autority, živě se musí ověřit skutečný link i jeho fyzický protisměr `(LinkNo, ToNodeNo, FromNodeNo)` a oběma musí být povolen systém `C`. Nezavádí se ani nepřepisuje žádný UDA. Všech 498 profilů se jinak dál kontroluje vůči přesným ID, `R1_OBS_RPDI`, rolím, vahám a fyzickým hranám; nově preflight kontroluje i `R1_OBS_ID`, `R1_OBS_BASIS`, `R1_OBS_SCOPE`, `CODE`, `R1_ACTIVE` a celkový výběr aktivních 12D profilů. Pozorování se znovu nepřepočítávají.

**2. `CreatePrTPathLinkList.SaveToArray`:** živý COM vrací hierarchickou tabulku. Záhlaví trasy obsahuje `OrigZoneNo`, `DestZoneNo`, `PathIndex` a prázdná linková pole; dětské řádky obsahují `Index`, `LinkNo`, `FromNodeNo`, `ToNodeNo` a prázdné OD klíče. Původní exportér vyžadoval všech sedm polí vyplněných na každém řádku, a tedy by selhal. Nový `com.normalized_prt_pathlink_rows()` bezpečně převede **pouze existující linkové řádky** do struktury s úplným klíčem, kterou využívají původní kontrolory incidence a skutečných sekvencí. Kontroluje počátek a pořadí link indexů, kontinuitu `ToNodeNo -> FromNodeNo`, duplicity/vracení klíčů a chybné či osiřelé potomky; nezkonstruuje žádnou domnělou trasu. Podporuje i původní ploché řádky.

**3. `ZONE.POP_ZP_2022`:** živé Visum skutečně hlásí, že takový atribut neexistuje. Je explicitně chráněnou součástí podmínky pro ZAHR generation v balíku. **Tento blokátor stále platí.** Žádný existující populační atribut nebyl bez průkazu vybrán jako náhrada a ZAHR nebyl tiše vypnut. Preflight V2.3.4 obsahuje nové read-only pokusy o zpřístupnění skutečných produkčních/atrakčních formulí z aktuální Trip generation operace, aby bylo možné určit správný populační atribut / skutečný termín. Dokud tuto formuli a datovou autoritu nepotvrdíme, `apply=false` a LIVE gate je blokovaný.

**4. Další preventivní kontrola:** `LIST_INTERFACE:CreatePrTPathLinkList` nyní ověřuje skutečnou strukturu a bezpečný převod prvního částečného vzorku; samotné vytvoření listu už není důkaz správného exportu. Tento pětřádkový vzorek **nenahrazuje kompletní path coverage/parity test**.

## Další živá zjištění (není to schválení APPLY)

- PTV Visum 2026, Python 3.13.9, NumPy 2.3.3: dostupné prostředí s hostitelem předaným COM objektem.
- Všechny očekávané osobní DSegy, jejich 681×681 OD matice a `R1_OSRM_DIST_KM` (matice číslo 9697) jsou čitelné.
- Assignment procedury 17, 18, 19, 20 typu 101 jsou aktivní; poslední operace 20 zahrnuje všechny 12 osobních DSegů a LNV/NV. **Nejde však o automaticky schválené production bindingy.**
- PrT quality-list atribut `GAP` v objektovém katalogu existuje, ale zatím nemáme schválený způsob identifikace poslední dokončené iterace konkrétního assignmentu. Nesmí se nahrazovat nastavenou tolerancí.
- Run script v pozici 3 `14A COUTRY_ADD Preset` je ve snapshotu vypnutý, zatímco pozice 8 `Foreign Matrix Post Processing` je zapnutá. Nezapínali jsme jej automaticky, protože přednastavené hodnoty mohou být už uložené v `.ver`. Před novým běžným TG/TD je třeba zjistit, zda očekávaný COUNTRY_ADD profil skutečně existuje.
- Aktuální živý preflight eviduje 8 598 směrových linků; dřívější oddělený 12B0 export hlásil 8 594. Jde o odlišný okamžik / verzi modelu; staré topologické potvrzení se proto nesmí bez výhrady přenést na tento snapshot.

## Co spustit teď

1. Nejdřív **jen** `R1_15A2_VISUM_COM_PREFLIGHT_V2_3_4_INLINE.py`. Je zcela soběstačný, tichý, podporuje přímé vložení celého zdrojáku do Internal script a **čte model bez změn**. Ukládá podadresář `R1_15A2_COM_API_PREFLIGHT` výhradně vedle otevřené `.ver` pomocí `Visum.IO.CurrentVersionFile`.
2. Pošli nový `COM_API_PREFLIGHT.json`. V reportu hledáme zejména `APPROVED_COUNTLOCATION_RPDI_AND_ROLE`, `LIST_INTERFACE:CreatePrTPathLinkList`, `TG_LIVE_FORMULAS_POPULATION_PROBE` a původní `ZONE_ATTRIBUTE:POP_ZP_2022`.
3. S kalibračním masterem `R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_4.py` v této chvíli **neprováděj APPLY**. Dořešíme skutečný POP atribut nebo správnou formuli, assignment operation binding, dosažený GAP a full saved-path coverage/parity.

Konfigurace `R1_15A2_CONFIG_V2_3_4.json` má `apply=false`, prázdný seznam `supply.assignment_operations` a neschválený `supply.gap_readback.attribute=null`. Autorizované soubory κ, IDP, CSD408, CITY90, VDF a původní numerické jádro nebyly změněny. Živá data se v ZIPu nekopírují; výchozí chyby a vzorek `SaveToArray` jsou zaznamenány v `LIVE_PREFLIGHT_FINDINGS_V2_3_4.json` bez lokálních osobních cest.
