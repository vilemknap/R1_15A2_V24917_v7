LONG OD -> profil, 2026-10-29

Kompletni zdroj je v koreni GitHub ZIPu. Pouzijte celou kopii, nikoli jednotlive soubory bez odpovidajicich SHA manifestu.

Navod a hranice: LONG_OD_PROFILE_INCIDENCE_REPORT_CZ.md
Vysledky: LONG_INCIDENCE_CURRENT_20261029.json a evidence_long_incidence_current_20261029/
Patch zahrnuje kod, testy, dokumentaci, manifesty a atributy; generovane dukazy jsou samostatne.

Cteci API existujiciho V24917 adapteru: adapter.long_profile_incidence(diag, novy_prazdny_adresar). Samo nespousti Visum ani assignment. Neni automaticky volano v kazdem kalibracnim kroku.

48 cilenych testu; hlavni sada 1834 proslo, 4 preskoceny; DIAGFAST 138; audit 18. Vse offline. Zivy Visum nebyl testovan.
LONG Generation i spolecne LONG TD fitovani zustavaji zmrazene do overeni skutecne odezvy. Maska OSRM >=80 km nema horni mez.
