# Audit nul a měřítka zónových atributů pro 2040–2070

**Nalezeno 160 buněk v 66 zónách v každém roce, kde je prognóza nula a reference 2022 kladná. Navíc je prokázaný nesoulad sloupců ve zdrojových vzorcích NUM_PM/NUM_PM_SMEAR.** Tyto vstupy je potřeba vyřešit před použitím předchozího importního balíčku pro prognózy. Tento audit data ani importéry nepřepisuje.

## Co bylo porovnáno

Nový `vstupy_prod_att_R1_hodnoty.xlsx`: listy pro 2040, 2050, 2060, 2070. Referencí je uživatelem dříve dodaný export modelu 2022 **`ZONE-2026-10-31-03-39-29.xlsx`**, list Zones. Nejde o nový živý odečet raw atributů z checkpointu TD02; pokud byly raw vstupy 2022 po tomto exportu ručně změněny, referenci je třeba aktualizovat.

Prověřeno 14 raw atributů používaných novým importérem × 681 zón × 4 roky = **38 136 buněk**. Zóny se párují podle OSRM_MATRIX_ID/NO, ne podle názvu či pořadí. Referenční NO a OSRM_MATRIX_ID souhlasí. Duplicitní historické hlavičky h_* v pracovních listech nejsou součástí tohoto raw importu; kalibrační ADD_*/ZAHR_* se neporovnávají jako plánované vstupy, protože se neimportují.

## Nuly proti kladné referenci

| Rok | Buňky s 2022 >0 a prognózou 0 | Zóny | Z toho NUM_PM_SMEAR | Chybějící hodnoty při kladné referenci |
| --- | ---: | ---: | ---: | ---: |
| 2040 | 160 | 66 | 55 | 0 |
| 2050 | 160 | 66 | 66 | 11 |
| 2060 | 160 | 66 | 66 | 10 |
| 2070 | 160 | 66 | 66 | 10 |

Celkem jde o **640 ročních buněk**. Shodný celkový počet neznamená shodné atributy: pro 2040 je navíc nulových 11 NUM_PUP_PLACES; od 2050 jsou některé z těchto buněk prázdné, zatímco nulových NUM_PM_SMEAR přibylo 11. Prázdná hodnota se v dosavadním importéru zachová z 2022, skutečná numerická nula se zapíše. Tento rozdíl je rozhodující.

Úplný seznam je v [ZERO_OVER_POSITIVE_2022.csv](ZERO_OVER_POSITIVE_2022.csv), jeden řádek = rok × zóna × atribut. Obsahuje název, referenci, prognózu i příznaky zóny. Chybějící/neplatné buňky s kladnou referencí jsou zvlášť v [MISSING_OVER_POSITIVE_2022.csv](MISSING_OVER_POSITIVE_2022.csv). Všechny nalezené nuly mají v referenci **NOT_ZAHR=1**; nelze je vysvětlit prostě jako nulování zahraničních zón.

### Domácí vnější zóny 608–618

Malacky, Rohoznik, Stupava, Piestany, Senica, Velky Meder, Myjava, Nitra, Nove Zamky, Topolcany a Kolarovo. Mají NOT_ZAHR=1 a AMDY_EXTERNI_ZONA=1, tedy domácí vnější zóny. Ve všech čtyřech prognózách mají proti kladné referenci nuly NUM_VS, NUM_PUP, E_C, E_NC, NE_C, NE_NC, PRENOC_SVK a NUM_PM. Pro 2040 navíc NUM_PUP_PLACES; pro další roky se zde místo nul vyskytují i prázdné hodnoty.

Příklad **615 Nitra**:

| Atribut | Reference 2022 | 2040 | 2050 | 2060 | 2070 |
| --- | ---: | ---: | ---: | ---: | ---: |
| POP_ZP | 135 837 | 131 441,89 | 125 940,16 | 118 980,20 | 114 116,57 |
| NUM_PM | 62 866 | 0 | 0 | 0 | 0 |
| E_C | 49 986 | 0 | 0 | 0 | 0 |
| NUM_PM_SMEAR | 81 148 | 0,90615 | 0 | 0 | 0 |

Obyvatelstvo zůstává vysoké, ale navazující veličiny mizí. Samotný audit neprokazuje, že každá nula vznikla z chybějícího lookupu; klíč `ZONE 403` v kontrolované externí cache existuje. Rozpor vyžaduje kontrolu autoritativních prognózních zdrojů, ne náhradu nuly domnělou hodnotou.

### Pracovní místa a NUM_PM_SMEAR

Nulové NUM_PM_SMEAR mají také domácí zóny s kladným NUM_PM, například Malacky IP (54→0 při NUM_PM 54), Duslo (1000→0 při NUM_PM 1000), Hlavná stanica (2669→0 při NUM_PM 2669). Pole NUM_PM_SMEAR je podle uloženého TG kontraktu vstupem domácí pracovní atrakce; takový pokles může odstranit tuto část atrakce.

Vedle nul bylo nalezeno **545 zón v 2040 a 534 zón v každém dalším roce**, kde referenční NUM_PM_SMEAR ≥100, ale prognóza je kladná a <2. Tyto případy jsou v [LOW_NUM_PM_SMEAR_SCALE.csv](LOW_NUM_PM_SMEAR_SCALE.csv). Jde o popisný filtr měřítka, nikoli o novou kalibrační mez nebo automatický důkaz chyby každé jednotlivé hodnoty.

### Malé legitimní nuly nelze vyloučit

Zóna **641 Od Zavarského** má POP_ZP 4→0 a s ním E_C/E_NC/NE_C/NE_NC 1→0 a PRENOC_SVK přibližně 0,619→0. To může být záměr demografické prognózy. Proto nebylo automaticky použito pravidlo „každá nula = vrať rok 2022“.

## Konkrétní chyba ve zdrojových odkazech

V původních velkých pracovních Excelech ze stejného zadání byla zkontrolována cesta ze sloupců BH/BI listu `Zony_sloucene_43_amdy_koeficien` do externího listu `PROGNOZA zde`. Jde o původní vzorce a uložené hlavičky externí cache, bez otevření či přepočtu externího sešitu.

| Cílový rok | Sloupec načítaný do NUM_PM_SMEAR | Jeho uložená hlavička | Sloupec načítaný do NUM_PM | Jeho uložená hlavička |
| --- | --- | --- | --- | --- |
| 2040 | MF | **K_2025** | MM | **NUM_PM_SMEAR_2026** |
| 2050 | MG | **K_2026** | MN | **NUM_PM_SMEAR_2030** |
| 2060 | MH | **K_2030** | MO | **NUM_PM_SMEAR_2040** |
| 2070 | MI | **K_2040** | MP | **NUM_PM_SMEAR_2050** |

Příklad pro Nitru, rok 2040: `BH616`, označené `NUM_PM_SMEAR_2040`, používá `IFERROR(XLOOKUP(E616, ... E:E, ... MF:MF), 0)`, přičemž MF2 v externím listu je `K_2025`. `BI616`, označené `NUM_PM_2040`, načítá MM, jehož hlavička je `NUM_PM_SMEAR_2026`. Záměna veličiny i ročního horizontu je tímto doložená. Přesné původní vzorce, názvy souborů, SHA, reference externích XML částí a cache hodnoty jsou v [SOURCE_FORMULA_EVIDENCE.json](SOURCE_FORMULA_EVIDENCE.json).

Tato evidence vysvětluje řádový nesoulad hodnot pracovních míst. Neprokazuje správnou náhradní prognózu pro 2060/2070 a neopravňuje doplnit ji odhadem. Vzorce často obsahují IFERROR(...,0); z pouhé výsledné nuly nelze rozlišit věcnou nulu a potlačenou chybu zdroje. Převod na hodnoty tento problém neopravuje.

## Dopad na předchozí balík

Nové values-only listy ve všech 14 raw atributech souhlasí s již připravenými importními vstupy. **Nalezené nuly nevznikly zaokrouhlením v Pythonu ani při párování zón.** Soubor [DIFFERENCES_VS_PUBLISHED_IMPORT.csv](DIFFERENCES_VS_PUBLISHED_IMPORT.csv) má pouze hlavičku, bez rozdílů. Zaokrouhlení MC_MEAN se týká nákladních matic, nikoli těchto zónových atributů.

Dosavadní importér rozlišuje platnou numerickou nulu od prázdné/chybové buňky. Chybné/prázdné vstupy nechá z 2022, ale skutečné nuly a kladné hodnoty typu 0,906 zapíše. Předchozí zelené programové testy proto nejsou potvrzením správnosti těchto zdrojových prognózních hodnot. V tomto kroku nebyl vydán upravený importní balík.

Další ohraničený krok je opravit výběr **správné veličiny a správného roku** v autoritativním zdroji pracovních míst a vyřešit zóny 608–618. Pro prokázaně chybějící hodnoty lze po stanovení pravidla ponechat referenci 2022; takové doplňování musí být označené jako fallback, nikoli vydávané za novou prognózu. Automatické kopírování NUM_PM do NUM_PM_SMEAR by bez ověření prostorového rozdělení nebylo podložené.

## Ověření

`analyse.py.txt --package .` znovu provede porovnání z archivovaných malých CSV; při počáteční přípravě lze dodat oba původní XLSX argumenty. **25 kontrol dat prošlo**, viz CHECKS.json. To znamená konzistenci výpočtu auditu, nikoli schválení zdrojových nul. SUMMARY.json obsahuje přesné počty; INPUTS.json SHA zdrojů a normalizovaných tabulek. Kontrola publikace a změn souborů je v PACKAGE_CHECKS.json.

Importní CSV, nákladní matice, runtime kód, kalibrační nastavení a původní manifesty zůstaly beze změny. Živý Visum/COM: **NOT_RUN**.
