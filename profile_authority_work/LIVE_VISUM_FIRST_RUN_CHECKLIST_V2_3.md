# R1 15A2 V2.3 - first live design-only integration gate

1. Otevrit cisty accepted `.ver` se znamou autoritou 12D/11D.
2. Overit `Storage of paths = Save as routes`, aktualni assignment a
   konzistenci vsech 12 osobnich DSegu a freight LNV/NV.
3. Spustit `R1_15A2_SUPPLY_DEMAND_MASTER_V2_3.py` samostatne,
   s vychozim `apply=false` a bez volani uvnitr Procedure Sequence.
4. Predat `00_DSEG_INVENTORY.json`, `00_SUPPLY_ASSIGNMENT_PLAN.json`,
   `00_PREFLIGHT.json`, `SUPPLY_PATH_SEQUENCE_DESIGN.json`,
   official PrT path/path-link export, `SUPPLY_ACTUAL_ROUTE_STORE.sqlite`,
   a cely `RUN_STATUS.json`.
5. Overit: jednoznacny DSeg/O/D/PathIndex join, spojitost a poradi hran,
   dseg volume parity, profile path-flow parity, existenci overenych ON/OFF
   vetvi a presnou podobu kazde vybrane `actual_contiguous_sequence`.
6. Zkontrolovat proti skutecnym Link ADDVAL1 a VDF aktivni impedance vzorec
   `100 * TCUR_PRTSYS(C) + 1000 * ADDVAL1` pro C a C_noT a jeho 10 s jednotku.
7. Ujasnit live cisla/typy assignment operation, jejich skutecny DSeg set,
   mereny konvergencni gap a zamrazeni demand matic.
8. Pote nejprve jen JEDEN omezeny guarded APPLY kandidata,
   po kterem musi nasledovat porovnani hash matic, TG, TD,
   ADDVAL1 readback, fresh 12D/11D, converged assignment a exact rollback.
9. Jakkoliv nekompletni export, neshoda autorit nebo chybejici COM udaj
   znamena STOP bez zmeny produkcni `.ver`.

No real Visum 2026 COM run was executed when this release was prepared.
