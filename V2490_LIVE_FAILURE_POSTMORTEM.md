# V2.4.9.0 — basis z posledního živého V2.4.8.9 běhu

Běh `RUN_20261016_233441_498675` vyšel z bezpečného B_0000. Generation search skončil bez přijaté Generation změny kvůli existujícím hard guardům (mj. `NEW_SEVERE_GEH_PROFILE`), poté TD skončilo jako `FAILED_BUT_ROLLBACK_VERIFIED` na `V242_TD_UNREQUESTED_PARAMETER_CHANGE`.

Tento pád nebyl důkazem, že survey křivku nelze přesně napasovat; šlo o příliš striktní exact-hash/read-back kontrolu b,c. Současně vizuální i metodický audit ukázal druhý problém: survey mobility CDF nemá být hard equality target. Modelové křivky mají strukturální omezení a sampling uncertainty survey reference.

V2490 proto odděluje dvě autority:

- technický integrity contract: frozen context + metadata exact, b/c pouze úzká numerická COM read-back tolerance;
- metodický TD contract: survey CDF jako soft directional reference, material aggregate improvement + bounded component trade-offs + nezměněné síťové hard guardy.

Nativní 20B/IPF tolerance se neuvolňuje. Soft TD rejection pouze zmenšuje parametrický krok; pokud žádný bezpečně realizovaný krok materiálně nepomůže, obnoví se parent a TD je bounded plateau. Ne-IPF technické chyby a IPF exhaustion zůstávají fail-closed.
