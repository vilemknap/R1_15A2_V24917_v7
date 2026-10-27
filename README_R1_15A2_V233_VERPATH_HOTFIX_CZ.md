# R1 15A2 V2.3.3 - COM PREFLIGHT HOTFIX: zapis vedle otevreneho .ver

## Co se opravilo

Diagnostika `R1_15A2_VISUM_COM_PREFLIGHT_V2_3_3.py` i modul
`r1_15a2_live_api_audit.py` nyní odvozují **vystupni adresar** ze
zdokumentovane read-only vlastnosti `Visum.IO.CurrentVersionFile`.
Vraci uplnou cestu k aktualne otevrenemu souboru Visum verze (.ver).

Vystupy vznikaji **vedle otevreneho souboru .ver**, ve slozce
`R1_15A2_COM_API_PREFLIGHT/RUN_.../`. V korenove slozce je `LATEST_RUN.txt`.

**NEPOUZIVA SE** `Visum.GetPath(2)` jako vystupni adresar, protoze jde o
volitelne nastaveni projektovych adresaru a nemusi se shodovat s adresarem .ver.
Nepouziva se `__file__`, `cwd`, `%LOCALAPPDATA%` ani zadny automaticky fallback.

Pokud COM nevrati plnou cestu k otevrenemu souboru, soubor neexistuje, nejde
o `.ver`, nebo do jeho slozky neni povolen zapis, skript skonci bez toho,
aby zapisoval na nejakou jinou lokaci. Zmenu modelu neprovadi.

## Pouziti

V aktualnim Visumu otevri cilovy *.ver a vloz kompletni obsah samostatneho
preflight `.py` jako Internal script. Zadna dodatecna konfigurace cest.
Po skonceni najdes `COM_API_PREFLIGHT.json` v podslozce vedle aktualniho `.ver`.

Technicky zdroj: PTV Visum 2026 COM Reference,
https://cgi.ptvgroup.com/vision-help/VISUM_2026_COM-Help/VISUMLIB~IIO~CurrentVersionFile.html

Omezeni: offline testy s COM fixtures; beh ve skutecnem Visum 2026 zatim nebyl proveden.
