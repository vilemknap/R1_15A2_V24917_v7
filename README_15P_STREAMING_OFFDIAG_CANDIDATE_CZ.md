# R1 15A2 — kandidát V2.3.7 / 15P: dávkový export tras + mezizónová parita

**Stav:** návrhový kandidát OFFLINE VERIFIED; **živý kompletní export ještě nebyl ověřen**.  Produkční `APPLY` **zůstává zakázaný**. Nejbližší doporučený krok je krátká sonda **15Q**, ne další 20+ minutový běh kalibrátoru.

## Co ukázal skutečný 15P

- 15P na Visumu 2026 úspěšně přečetl po 3 × 80 řádcích `IPrTPathLinkList` pro `NATIVE_CW` a `NATIVE_CW_noT`, včetně hierarchických rodičů a dětí; příslušná COM `SaveToArray` má `FirstObject, LastObject`.
- Diagonály čtyř matic: CW 24,6407 %, CW_noT 24,6698 %, CS 30,7861 %, CS_noT 30,8672 % celkového objemu. Samotné vnitrozónové cesty tedy vysvětlují hlavní část dřívějšího rozdílu součtů.
- **Pozor, verze modelu jsou rozdílné:** 15P běžel na `C:\Users\vilem_knap\Documents\VISUM\v45\2022\R1_2022_vraceny_zonalni_atributy_osrm_doplneno_local.ver`, zatímco starší `03D` pochází z jiného běhu `.ver` pod OneDrive `AKTUALNI`. Není korektní vydávat jejich objemy za párovou paritu ve stejném okamžiku.

## Co kandidát skutečně mění

- `r1_15a2_runtime_v1.py`: pouze cesta exportu, nikoli optimalizační jádro: ověřená COM signature, malé stránky, při prvním odmítnutí větší stránky fallback **pouze** na živě potvrzených 80, bez tichého návratu k neomezenému `SaveToArray` v produkci. `04_PATHLINK_READ_PROGRESS.json` se průběžně obnovuje.
- `r1_15a2_sequence_v23.py`: nový `consume_stream` procesuje jednu trasu/OD trh po druhé; nevytváří seznam všech hran jednoho DSeg v RAM. Udržuje původní výpočty a průkazné pořadí uložených tras. SQLite je kompletní důkazní skladiště, ne syntetický routing.
- `03D_DSEG_PATH_VOLUME_PARITY.csv`: nově uvádí maticový total, diagonálu, mezizónový součet, objem mezizónových uložených tras a jejich vzájemnou odchylku. Tolerance **1 %** nezměněna a stále může zabránit pokračování.
- Při selhání je volitelně zapnutý fail-fast. `apply=false` i ochrany 498 měření zůstávají zachované.

## Co dělat teď (krátký test)

1. Otevři **tu přesnou uloženou verzi `.ver`**, na které chceš skutečně stavět návrhovou kalibraci; nestřídej testovací `Documents` a produkční `OneDrive` `.ver` bez jasného záměru.
2. Rozbal **celý** ZIP do samostatné složky. Přes Visum **Scripts → Execute script file** spusť `R1_15A2_15Q_BOUNDED_PATHLINK_THROUGHPUT_SMOKE.py`, mimo Procedure Sequence.
3. 15Q přečte nejvýše **100 × 256 řádků** pro `NATIVE_CW` a pro `NATIVE_CW_noT` (max. 51 200 řádků celkem). **Nespouští** žádné přiřazení, nemění matice, `ADDVAL1`, zóny ani `.ver`. Ukládá výstupy vedle `.ver`.
4. Pošli soubor `R1_15A2_15Q_PATHLINK_PERFORMANCE/RUN_.../15Q_PATHLINK_THROUGHPUT_SMOKE.json`. Podle skutečné rychlosti ověříme, zda je full export časově a diskově přiměřený, anebo ještě potřebuje zrychlit.

### Až následně: kompletní DESIGN ONLY

V balíku zůstává `R1_15A2_DESIGN_ONLY_FIRST_RUN_V2_3_7.py`, ale jeho další plný běh **nedoporučuji bez vyhodnocení 15Q**: model má přes 5 milionů uložených řádků tras a link-level seznam může být řádově větší. Ani stránkování a ukládání na disk negarantuje krátkou dobu. Kompletní export je stále povinný pro případný Supply `APPLY`; nelze vynechat trasy nebo přepsat chybějící linky nejkratší cestou.

Diagnostické výstupy full návrhového běhu (pokud jej později schválíme): `04_PATHLINK_READ_PROGRESS.json`, `03A_PATH_EXPORT_SUMMARY.json`, `03B_DSEG_PATH_EXPORT_STATUS.csv`, `03D_DSEG_PATH_VOLUME_PARITY.csv`, `SUPPLY_PATH_SEQUENCE_DESIGN.json`.

## Bezpečnost a integrita

- `apply=false` je hard-locked ve vstupním skriptu. `supply.assignment_operations=[]`. Epsilon Visumu = 0,005. Žádný automatický `LoadVersion` návrhové větve.
- `r1_15a2_core.py`, `r1_15a2_multiblock.py`, pomocné skripty 11D/12D, zmrazené CSD408/CITY90, TG, impedance a VDF se nemění. **Výjimky vůči starším hashům:** záměrně změněné `r1_15a2_runtime_v1.py`, `r1_15a2_sequence_v23.py` a nová konfigurace.
- Nová větev prošla offline testy, nikoli full-scale COM zátěžovou zkouškou. Pokud se model od živého 15P změnil, ověř COM na aktuální `.ver`.
- Spouštěj výhradně **`VERIFY_PACKAGE_15P_STREAMING_20261016.py`**; staré historické `VERIFY_PACKAGE_V2_*` se vztahují na své původní distribuce a nejsou verifikátory této kandidátní verze.
