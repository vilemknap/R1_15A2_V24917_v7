# Live Visum acceptance — V2.4.9.5

Spusťte pouze z ověřeného/uživatelem zvoleného B_0000 nebo jiného accepted
checkpointu, nikdy z neověřeného in-memory stavu po pádu.

V2.4.9.5 je stále bounded trial release (`production_apply = false`).

Při prvním živém běhu ověřit zejména:

1. path export pokračuje přes transientní `RPC_E_CALL_REJECTED` retry se stejným
   bounded rozsahem a transientní chyba nespouští page-size fallback;
2. semantic restart nevyžaduje cross-run shodu raw `.ver` SHA;
3. Generation acceptance reportuje `severity_transition_guard.policy_scope = GENERATION`;
4. přechod v pásmu 19.5--20.5 se objeví jako `hysteresis_geh20`, ne jako
   `material_new_geh20`;
5. Generation nepřijme více než 3 material new GEH20, single increase > 2.0,
   total excess > 2.0 ani nový GEH30;
6. TD používá přísnější scope `TD`: max. 1 material new GEH20, single increase
   max. 1.0, total excess max. 0.75 a žádný nový GEH30;
7. observation-weighted mean GEH, LONG_COMPOSITE, fresh assignment a live 12D/11D
   zůstávají acceptance autoritou;
8. accepted checkpoint publikuje semantic sidecar a rollback zůstává fail-closed.

Pokud se objeví technická COM chyba mimo retry policy nebo selže rollback/readback,
běh se nepovyšuje na real-Visum PASS.
