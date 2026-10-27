# R1 15A2 V2.3.5 – živá náprava POP_ZP a vazeb TG

## Rozhodující živý důkaz

Ve formulích `FP_*` / `FA_*` vrácených z aktuálního PTV Visum 2026 přes Attribute List se používá **`[POP_ZP]`**, nikoli `POP_ZP_2022`. Například `FA_1_WORK`: `[POP_ZP]*[ZAHR_ATR_WORK]*[ZAHR_SUSED]/100`. Stejné pravidlo platí pro WORK a SERVICE zahraniční produkci. Ve `FP_4_FOREIGN`, `FA_4_FOREIGN` se používá `[POP_ZP]*[COUNTRY_ADD_FOREIGN_CAL]` (FOREIGN parametr nesmí být zaměněn za ZAHR pracovní/obslužnou větev).

Z 681 zón je 655 tuzemských, 15 zahraničních sousedních `ZAHR_SUSED>0`, z nich však jen **6 má `POP_ZP>0`**. Zbylých 9 sousedních zahraničních zón nemá přes tuto formuli nenulový aktuátor a proto se nezahrnují do příslušných generačních kandidátů.

## Opravené součásti V2.3.5

- **Aktivní kontrakt:** `authorities/R1_TG_PARAMETER_DEPENDENCY_CONTRACT_V2_3_5.json` a `R1_15A2_CONFIG_V2_3_5.json` požadují `POP_ZP` (real), nikoli neexistující `POP_ZP_2022`; navíc požadují skutečně existující `FP_*` a `FA_*` zónové atributy.
- **Runtime výběr zahraničních zón:** testuje `NOT_ZAHR`, `ZAHR_SUSED`, `POP_ZP`, neprovádí přepočet populace a nevyplňuje chybějící atributy nulou.
- **Oprava dvou vrstev formule:** TG může číst zónový atribut `[FP_*]` / `[FA_*]`. Proto se kontroluje přesná vnější reference, nebo bezpečně ověřená inline formule. Nesmí se požadovat řetězec `ZAHR_PROD_WORK` přímo uvnitř vnějšího `[FP_*]` odkazu.
- **Preflight:** nový inline `R1_15A2_VISUM_COM_PREFLIGHT_V2_3_5_INLINE.py` vyžaduje `POP_ZP` a vypíše skutečný počet funkčních zahraničních zón, aniž by vyžadoval přesně šest v jiném modelu.
- Zdroje autorizovaných **498 CountLocations** (462 CAL + 36 VALID), κ, IDP, VDF, geometrie a cestová incidence nebyly měněny.

## Důležité omezení

Vnější `[FP_*]`/`[FA_*]` reference se kontrolují přímo v živém COM. **Vnitřní formule UDA pocházejí z dodaného forenzního exportu.** Ten u FORMULA sloupce neuměl současně vrátit ID atributu, a proto je uchován jako časovaný důkaz, nikoli falešně deklarovaná živá vazba jednoho řádku na jeden atribut. Pokud se mezitím změnily formula UDA, audit nutno zopakovat. Původní diagnóza `EVIDENCE_ONLY_NOT_AUTOMATIC_CLEARANCE` neznamená neúspěch čtení, jen správné odmítnutí autom. schválení.

Produkční APPLY zůstává **NEPOVOLENÝ (`apply=false`)**: seznam assignment operací je prázdný, dosažený `GAP` dosud nemá závaznou vazbu na konečnou iteraci, a zůstávají zvlášť požadovaná QA potvrzení CSD kolizí i CITY obousměrných pozorování. To nová oprava populace nemění. Master se spouští externě, nikoli uvnitř běžící Procedure Sequence. Inline diagnostika je tichá, pouze čte a zapisuje report **vedle právě otevřeného `.ver`**.

Při prvním kontrolním běhu spusť **jen preflight V2.3.5** a pošli nový `COM_API_PREFLIGHT.json` – zaměříme se na `ZONE_ATTRIBUTE:POP_ZP`, `ZONE_FOREIGN_POPULATION_ACTUATOR_SCOPE`, 12D autoritu, path-link export a výsledky interního TG/TD auditu. V reálném Visumu s upraveným kódem dosud neběželo ani APPLY, ani kompletní preflight.
