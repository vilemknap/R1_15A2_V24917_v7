# Změny V2.1 → V2.2

- Přidán `r1_15a2_supply.py`: přesné saved-route příspěvky, podmíněný kontrast alternativ stejného OD/DSeg, jednotlivé linky/skupiny hran, integrální kroky a pevná původní kotva.
- Přidán `r1_15a2_supply_visum.py`: strict směrové klíče, all-demand snapshot, schválené assignment-only operace, gap readback, očekávaná stará hodnota a návrat checkpointu.
- Přidán `r1_15a2_controller_v22.py`: společný supply/generation/TD controller, fixed-reference objective, vyhodnocení všech alternativ, nejlepší přípustný uložený kandidát, atomický accepted pointer a cyklové no-progress.
- Přidán nový master/config V2.2 a přiložené impedance/VDF exporty.
- Upraven EXISTUJÍCÍ `r1_15a2_runtime_v1.py`: callback nad skutečnými per-DSeg PrT path-list daty, možnost nebudovat generation incidence v supply exportu, exact DSeg scope/parity a kontrola neplatných matrix hodnot.
- Zachovány numerické soubory core/multiblock/Visum parameters, master V2.1 a oba 11D/12D helpery.
- Doplněny testy route parsing, CL/CF/EXOG scope, floor/units/prior, COM-shaped operation execution, rollback, zásahy mezi bloky, target/VALID izolace, resume a syntetický E2E controller.
- Staré release evidence zachováno pod `provenance/V21_*`; nové výsledky a manifest musí být čteny pro V2.2.

Neprovedeno: živý Visum assignment, produkční kalibrace R1, vytvoření chybějících LONG component targetů, změna kapacit/VDF, přímý OD write, nahrazení Visum assignmentu vlastním routingem.
