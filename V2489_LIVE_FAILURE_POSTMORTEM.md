# V2489 live-run postmortem basis

Živý běh prokázal, že Generation byla přijata, ale TD zůstalo rozpracované. Plný downstream recompute selhal na 20B SILENT IPF pro `2_SERV_noE_noC`, matici 9189, s `max_rel_err=3.495787955651562e-06`. Následná rollback diagnostika narazila na WinError 3 při kopírování 11D evidence.

Oprava nemění IPF toleranci. Zmenšuje pouze TD parametrický krok a stabilizuje auditní cestu. A_0001 vznikl ve větvi se starými absolutními stropy 3/10, proto není autoritativní restart.
