# Metodický kontrakt V2.2

## Poptávka a routing

Generation guidance používá aktuální profil × OD incidence P jako lokální informaci pro změnu poptávky. Supply drží Q pevné a mění rozdělení tras P(A). P není Jacobian podle ADDVAL1: návrh ze skutečných tras musí být vyhodnocen novým assignmentem.

Profilové reziduum je M-O. Nadbytek navrhuje znevýhodnění aktuálních tras, deficit zvýhodnění profilové trasy nebo znevýhodnění skutečné uložené alternativy stejné OD/DSeg. Ostatní profily, IDP a regularizace rozhodují při celkovém vyhodnocení; lokální znaménko není zárukou výsledku.

## Přesný podporovaný vzorec

C a C_noT LINK: `100*TCUR_PRTSYS(C)+1000*ADDVAL1`. +1 ADDVAL1 = +10 ekvivalentních sekund. Neaktivní GENERAL člen se nepřičítá. C_noT connector/turn používá vlastní čas. LNV/NV nemají přímý ADDVAL1 člen.

## Společné vyhodnocení

J = wCAL * mean(GEH_CAL^2) / fixed_initial_CAL_scale + wIDP * fixed_initial_weighted_component_error + lambdaA * sum(((A-A0)/sigmaA)^2).

Počáteční CAL reference, komponentní IDP targety/váhy a původní A0 se během přepínání bloků nemění. Role VALIDATION/DIAGNOSTIC neřídí optimum. Původní podmínky přijetí konkrétního bloku jsou další nutnou podmínkou, takže zlepšení společného J samo nepřebíjí strukturální nebo komponentní ochrany.

## Zkoušení a commit

Každá alternativa začíná z identického PRE; všechny vyhodnocené alternativy mají nové assignment/diagnostics. Po pokusu následuje kontrolovaný rollback. Nejlepší přípustný uložený stav je znovu načten, porovnán s jeho přesným snapshotem a diagnostikou a teprve potom publikován. Chyba rollbacku není NO_CHANGE ani PASS.

Změna A je baseline-relative lattice. Supply backtracking zmenšuje sadu hran, nikoli jednotku na polovinu. T0_C+10*A musí zůstat kladné i při nízké kongesci. Konzervativní bundle rozpočet zohledňuje opakovaný výskyt stejné hrany v uložených trasách.

## Rozsah důkazu

Přesnost route evidence se vztahuje na exportované skutečné uložené trasy a ověřené objemy. Chybějící nepoužívaná alternativa se nevymýšlí. Pure-path probe bez uložené alternativy se nesmí interpretovat jako prokázaná citlivost. Offline COM-shaped a syntetické controller testy nejsou live COM kvalifikace.
