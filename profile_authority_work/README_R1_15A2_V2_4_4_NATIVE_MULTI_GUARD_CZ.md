# R1 15A2 V2.4.4 — overnight calibration, native Visum Multi guard

Tato verze navazuje na V2.4.3 a opravuje pouze integrační hard-gate okolo Trip Distribution.

Samostatný FineCDF v1.7 zůstává v `reference_v17/` bitově identický. V integrovaném nočním běhu se ale jeho pevná tolerance na zachování marginál nepoužívá jako externí požadavek na konvergenci Visum Multi/Lohse-Schnabel. Skutečný výstup native Visum TD je autorita.

Marginální rozdíly se nadále kompletně zapisují do `MARGINAL_GUARD.csv`, `MARGINAL_WORST_ZONES.csv` a `MARGINAL_CONSTRAINT_INFERENCE.csv`, ale samy o sobě nezastaví FineCDF krok. Nadále zůstávají aktivní guardy na zmrazené P/A atributy, ADDVAL1, FOREIGN, b/c readback, chráněné vstupní matice, finiteness dat, skutečný IDP objective a následné živé assignment/GEH vyhodnocení.

Důvod: Visum Multi je iterativní balancing s vlastním `Maximum number of iterations` a `Quality factor`. Jeho výstup nemá být dodatečně nucen do přísnějšího externího strict-IPF kritéria.

## Spuštění

Otevřít baseline `.ver` a ve Visumu použít **Scripts → Execute script file**:

`R1_15A2_FULL_OVERNIGHT_COUPLED_V2_4_4.py`

Nespouštět z Procedure Sequence.
