# Metodická specifikace V2.1

## 1. Actual-path incidence

Z uložených Visum paths se pro profil `a`, OD/DSeg `k` a route `r` sestaví:

`B[a,k] = sum_r q[k,r] * I(a in r)`.

Opakovaný průjezd stejným směrovým profilem má multiplicitu > 1. Cesty nejsou rekonstruovány Dijkstrou.

Lokální lineární guidance řeší bounded regularizovaný problém:

`min_x 0.5 ||W(Bx-t)||² + 0.5 x'Λx + ||Γx||₁`.

`x` není nová OD matice. Slouží pouze jako lokální informace, které současné OD relace pomáhají nebo škodí CSD profilům.

## 2. Projekce do generation

Pro guidance `Δq_ij` se vytvoří marginály:

`ΔP_i = sum_j Δq_ij`, `ΔA_j = sum_i Δq_ij`.

MARGINALS projector udržuje stejný celkový produkční a atrakční přírůstek. Výsledné log kroky se materializují přes přesné TG parametry.

WORK attraction:

`ADD_ATT_W * NUM_PM_SMEAR * (1 + (AV_INCOME*ADD_SALARY-1000)/2700) * NOT_ZAHR + POP_ZP*ZAHR_ATR_WORK*ZAHR_SUSED/100`.

`ADD_SALARY` je nízkodimenzionální income-gradient efekt; zbytek nese `ADD_ATT_W`. Po bounds se znovu spočítá přesný realizovaný log efekt a P/A gap.

## 3. Komponentní b,c

Každé Visum stratum má vlastní `b,c`. Pro čerstvé model–target bin rozdíly:

- signed short/middle shape signal řídí `Δb`;
- mean distance a signed tail řídí `Δc`;
- `c_b_compensation` brání nekontrolovanému posunu mean při shape zásahu;
- trust-region bounds omezují absolutní krok;
- line-search scale se aplikuje jednou.

Každý kandidát se vyhodnocuje po plném TG/TD/assignment řetězci.

## 4. Bloky

- `GENERATION`
- `TD_COMPONENT_WORK`
- `TD_COMPONENT_SERVICE`
- `TD_COMPONENT_SCHOOL`
- `TD_COMPONENT_LONG`

Defaultně se na jedno spuštění přijme nejvýše jeden blok.

## 5. Acceptance

### Generation

Primární je CAL-only `mean(GEH²)`, se stejnou observation authority, protected-profile guardem, severity guardem a globálním IDP guardem.

### TD

Primární je komponentní objective:

`J_c = w1*L1_c + w2*|mean_model-mean_target|/mean_target + w3*RMSE_share`.

Selected aggregate se musí zlepšit, žádná selected komponenta nesmí nepřípustně degradovat, nonselected komponenty mají samostatný limit a CSD CAL objective se nesmí zhoršit nad limit.

VALIDATION není v návrhu ani rozhodnutí.
