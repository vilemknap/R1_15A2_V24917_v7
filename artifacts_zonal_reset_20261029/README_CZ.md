# Reset zónových koeficientů pro nový běh

Zdroj: uživatelův `ZONE-2026-10-29-20-26-54.xlsx`, 681 zón. Zpracováno 29. 10. 2026.

| Koeficient | Nová reference pro nenulové hodnoty |
| --- | --- |
| ADD_PROD_W, ADD_ATT_W, ADD_PROD_S, ADD_ATT_S | 1 |
| ADD_PROD_SCH, ADD_ATT_SCH | 1 |
| ADD_PROD_L | 0,3 |
| ADD_ATT_L | 1 |
| ADD_SALARY | 1 |
| ZAHR_PROD_WORK, ZAHR_ATR_WORK, ZAHR_PROD_SERV, ZAHR_ATR_SERV | 1 |

Všechny původní nulové koeficienty zůstávají nulové: W/S po 30, ADD_SALARY 31 a ZAHR po 666. LONG produkce se mění z 4,3834111531621103 na 0,3 ve všech 681 řádcích. LONG atrakce již byla všude 1. Je ověřeno 8 853 koeficientových buněk; 5 169 hodnot se změnilo.

Tento explicitní reset nastavuje původně kladné ZAHR koeficienty na novou surovou počáteční hodnotu 1. Běžná kalibrace je nadále omezuje relativně k neměnné počáteční hodnotě nového běhu; nemění se její kód ani interpretace normalizované reference.

## Doporučené použití: samostatný Python COM skript

V kořeni GitHub ZIP archivu je `R1_RESET_ZONAL_COEFFICIENTS.py`. Stačí tento jediný soubor; nepotřebuje Excel, NumPy, celý kalibrační balík ani instalaci dalších knihoven. Krátký balíček `R1_RESET_ZONAL_COEFFICIENTS_SKRIPT.zip` ve stejné složce obsahuje skript a tento návod.

1. Otevři model ve Visumu a ulož jeho kopii. Skript spouštěj před novou kalibrací, mimo běžící kalibrační pokus.
2. Zvol **Scripts → Run script file** a vyber `R1_RESET_ZONAL_COEFFICIENTS.py`. Skript používá výhradně instanci `Visum` předanou hostitelem; nespouští ani nevyhledává jinou instanci.
3. Zkontroluje všech 681 unikátních zón, přiřazení COM indexů k NO a dostupnost všech 13 atributů. Pracuje se současnými živými koeficienty; zachová všechny jejich nuly.
4. Ještě před první změnou uloží zálohu a seznam plánovaných změn do `%LOCALAPPDATA%\R1DF\ZONAL_RESET\<čas_jedinečný_identifikátor>` (při chybějící LOCALAPPDATA použije systémovou dočasnou složku). Složka obsahuje `BEFORE.json`, `OBNOVA_KOEFICIENTU.att`, `CHANGES.csv` a `REPORT.json`. Záloha tak odpovídá živému modelu při spuštění, i když se od Excelu liší.
5. Zapíše jen změněné koeficientové atributy a všechny hodnoty znovu načte. Při úspěchu ohlásí `RESET_VERIFIED_NATIVE_RECOMPUTE_REQUIRED` a cestu k protokolu. Při chybě včetně částečného COM zápisu obnoví dotčené atributy a ověří všech 13 proti záloze. `ROLLBACK_VERIFIED` znamená ověřený návrat koeficientů; `ROLLBACK_UNVERIFIED_REOPEN_SAVED_MODEL` vyžaduje ručně znovu otevřít uložený model a nepokračovat v kalibraci. Skript sám nepoužívá LoadVersion.
6. Model sám neukládá a neprovádí TG/TD/assignment. Po úspěšném resetu spusť nový kalibrační běh podle bodu 4 níže. Původní výstupy modelu zatím neodpovídají novým koeficientům.

Opakované spuštění na již resetovaném modelu neprovádí žádné COM zápisy, ale znovu ověří a zazálohuje stav. Počet 5 169 změn platí pro přiložený Excel; jiný aktuální model může mít jiný počet změn.

## Alternativní použití: soubor atributů ve Visumu

1. Před importem ulož kopii modelu. Reset dělej před novým během, mimo rozpracovanou kalibraci.
2. Načti `RESET_ZONALNICH_KOEFICIENTU.att` jako soubor atributů zón. Aktualizuj existující zóny podle `NO`; soubor obsahuje pouze NO a 13 koeficientů. V tomto kroku se nepřepisují výstupy generování ani jiné vstupy.
3. V seznamu zón ověř LONG produkci 0,3, LONG atrakci 1 a ostatní koeficienty podle tabulky, s původními nulovými výjimkami. `RESET_ZONALNICH_KOEFICIENTU.csv` obsahuje stejných 681 řádků pro kontrolu nebo mapovaný import.
4. Spusť nový běh obvyklým kalibračním launcherem bez obnovení starého kalibračního checkpointu nebo jeho run-start referencí. Po změně koeficientů jsou dosavadní FP/FA, OD a diagnostiky výsledkem starého nastavení: nový výchozí stav musí vzniknout řádným nativním přepočtem TG → TD → 20A/20B → assignment a čerstvými diagnostikami v existujícím řetězci.

`ZONE_REFERENCNI_KOEFICIENTY_20261029.xlsx` je celý původní export s upravenými koeficienty. Ostatních 117 sloupců zůstalo přesně zachováno, včetně starých FP/FA. K aktualizaci modelu proto použij úzký `.att`, případně importuj z Excelu pouze NO a koeficienty.

Pro návrat slouží `OBNOVA_PUVODNICH_KOEFICIENTU.att` nebo nezměněný `ZONE_PUVODNI_PRED_RESETEM.xlsx`. Obnovovací ATT vrací koeficienty z tohoto exportu; po obnově je opět nutný přepočet, nevrací stav celého modelu.

## Rozsah resetu

Nemění se COUNTRY_ADD, COUNTRY_ADD_FOREIGN_CAL/MULT ani jejich klasifikace; jsou to samostatné vstupní/fixní faktory FOREIGN. Zachovány jsou masky, populace, mzdy AV_INCOME, identita a pořadí zón, geometrie i všechny ostatní údaje. Nezměněny jsou TD b/c, linkové ADDVAL1 i kalibrační kód a jeho meze.

Hraniční přechody mají navíc přímo kalibrované objemové vstupy `P09F4_PER_PRE_*` / `A09F4_PER_PRE_*`. Nejde o koeficienty s neutrální hodnotou 1. Export obsahuje pouze jejich současné objemy; bez původního modelu nebo jejich předkalibračního exportu nelze poznat a obnovit původní objemy. Zůstávají zachovány. Tento balíček tedy resetuje zónové koeficienty, nikoli veškerou historii změn modelu.

## Ověření a reprodukce

- Nezávislá kontrola všech 88 660 původních buněk, všech 8 853 koeficientů a všech 681 identit/pořadí zón prošla.
- Po zpětné záměně pouze změněných čísel je XML listu totožné s originálem. Ostatní součásti XLSX jsou bajtově shodné, včetně stylů, komentářů a metadat.
- Resetovací i obnovovací ATT a CSV souhlasí s Excelovými hodnotami. Druhé provedení resetu nic nemění.
- `AUDIT_RESETU.json` obsahuje počty a reference; `OVERENI.json` obsahuje výsledek kontroly a kontrolní součty; `ZMENY_PRED_PO.csv` všech 5 169 změn.
- Původní kalibrační logika se nemění. Přibyl samostatný ručně spouštěný COM reset a jeho regresní testy; SHA manifesty byly řádně aktualizovány. Výsledky offline testů jsou v `COM_SCRIPT_CHECKS.json` a přiložených protokolech.
- Import do živého Visumu a nativní přepočet nebyly provedeny (`LIVE_VISUM_NOT_RUN`).

Reprodukce standardním Pythonem bez dalších knihoven (soubory `.py.txt` jsou běžné spustitelné Python zdroje):

```text
python build_reset.py.txt ZONE_PUVODNI_PRED_RESETEM.xlsx vystup
python verify_reset.py.txt vystup
```
