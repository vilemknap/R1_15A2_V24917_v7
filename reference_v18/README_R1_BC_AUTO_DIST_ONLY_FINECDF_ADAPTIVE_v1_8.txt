R1 2022 - FINE IDP CDF KALIBRACE B/C - v1.8 ADAPTIVE, SILENT
================================================================

AUTORITA
--------
V1.8 zachovava beze zmeny:
- vsech 512 bodu puvodnich IDP CDF,
- LONG frozen mixture,
- opravenou M9001/M9697 preflight autoritu,
- nativni Visum Trip Distribution jako jedinou autoritu OD vysledku,
- ochranu P/A, ADDVAL1, FOREIGN a dalsich vstupu,
- combined native TD verification pred prijetim slozeneho b,c kroku.

CO JE NOVE PROTI v1.7
----------------------
1. Line search rozlisuje bloky, ktere maji predikovany prostor ke zlepseni,
   a bloky na lokalnim plateau. Stabilni blok uz nevynucuje zbytecne mensi
   alpha kroky pro ostatni bloky, ale nesmi se zhorsit mimo puvodni guardy.
2. Trust radius po uspesnem kroku muze rust rychleji; po neuspechu se stale
   zmensuje a zustava omezeny hard bounds.
3. ITERATION_HISTORY obsahuje predicted_objective a predicted_active.
4. Pri integraci do 15A2 V2.4.6 lze solver spustit v progresivnim budgetu.
   Raný MAX_ITERATIONS/TD_EVALUATION_BUDGET znamena pouze pokracovani demand
   cyklu, nikdy konvergenci ani odemceni Supply.

CO SE NEMENI
------------
- P/A, a, FOREIGN M9116, sit, konektory a ADDVAL1;
- primarni 512bodovy objective;
- nativni Multi output a parameter readback;
- rollback pres obnovu b,c a novy native TD, bez prime opravy OD bunek;
- hard stop pri chybe, nekonzistentnim readbacku nebo poskozeni chranenych dat.

POUZITI
-------
V produkcnim workflow V2.4.6 nespoustej tento soubor samostatne. Spust:

  R1_15A2_FULL_OVERNIGHT_ADAPTIVE_V2_4_6.py

Integracni bridge vybere tento soubor relativne k baliku, overi jeho SHA-256
a SCRIPT_ID a nastavi budget podle vnejsiho demand cyklu.

SAMOSTATNY FORENSIC RUN
-----------------------
Samostatny run je urcen jen pro specialni distribution-only audit nad
OSRM_AMDY_INPUTS_PATCHED_TD_STALE.ver. V takovem pripade spust soubor primo
pres Scripts > Execute script file. Vysledek neni hotovy vehicle/assignment
scenar a nenahrazuje coupled 15A2 workflow.

OMEZENI VALIDACE
----------------
- offline a COM-shaped testy jsou soucasti hlavni V2.4.6 sady;
- skutecny PTV Visum 2026 COM run v tomto prostredi proveden nebyl;
- adaptivni search muze zvolit jinou posloupnost parametru nez v1.7;
- vsechny live acceptance a rollback guardy zustavaji povinne.
