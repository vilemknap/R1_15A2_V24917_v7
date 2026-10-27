# R1 15A2 V2.4.8.4 — stable run-root hotfix

V2.4.8.3 v reálném Visum běhu selhala ještě před demand cycle při 11D baseline diagnostice.
CurrentVersionFile byl accepted checkpoint uvnitř předchozího V2481 RUNS stromu. Launcher z jeho
parent adresáře odvodil nový `R1_15A2_V2483_RUNS`, takže výsledný 11D mirror soubor měl přibližně
278 znaků a `shutil.copy2` skončilo Windows `FileNotFoundError [WinError 3]`.

V2.4.8.4 nemění path-incidence ani zero-share residual algoritmus. Mění pouze umístění nového runu:
- pokud source `.ver` leží pod `R1_15A2_*_RUNS`, vyhledá tento RUNS ancestor a použije jeho parent jako project base;
- jinak použije parent source `.ver` jako dříve;
- persistent cache zůstává `%LOCALAPPDATA%\\R1_15A2_PATH_CACHE_V248`;
- legacy run roots se hledají na stabilní project base;
- source `.ver` zůstává read-only authority a pracuje se na `WORKING_START.ver`.

Tím je odstraněno vnoření runů a související MAX_PATH pád, aniž by se oslabila cache kompatibilita
V2481/V2482 nebo acceptance authority fresh Visum assignment + live 12D/11D.
