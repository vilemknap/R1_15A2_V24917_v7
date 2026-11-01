# Potvrzený checkpoint TD02 pro pracovní scénáře

Dodaná metadata ukazují na **`ACCEPTED_A_0003_d18f2c796ad6.ver`** z běhu `RUN_20261101_113344_232959`. `path_epoch_checkpoint.live_state_hash` se přesně shoduje s přijatým TD02: `3b7afe0b9ced0c93a679dcffe9a088c8a3107f95acf59cab182b928ffbe3c58e`. Počet přijetí 3, slot A; nejde o doklad rozpracovaného cyklu 3.

Úplná cesta:

```text
C:\Users\vilem_knap\R1F_742748e4\R1_15A2_V16_RUNS\RUN_20261101_113344_232959\CALIBRATION\CHECKPOINTS\ACCEPTED_A_0003_d18f2c796ad6.ver
```

Zachovat samostatnou kopii `.ver`, příslušného `.ver.semantic.json` a dodaného ukazatele. Dva checkpointové sloty kalibrátoru rotují a LATEST se přepisuje; pro scénáře použít právě tento konkrétní checkpoint po TD02.

SHA-256 uvedené v metadatech: `57f394374213b80946fb693ce527f567de41589e08eaf999f1910ae65a746d00`. Velikost podle metadat: 535329519 bajtů. Samotný .ver payload ani sémantický sidecar zde nebyly dodány; jejich skutečné bajty a SHA proto tento audit nezávisle neověřoval. Čitelný JSON zachovává data s konci řádků LF; původní bajty včetně CRLF jsou bezeztrátově archivovány v `.json.gz.b64` a mají vlastní vstupní SHA v CHECKPOINT_CONFIRMATION.json.

Předchozí audit a postup dodávky jsou v `artifacts_td02_working_delivery_20261101/REPORT_CZ.md`; jejich tehdejší údaj „název checkpointu nedodán“ tento nový důkaz doplňuje. Z tohoto přijatého pracovního stavu lze připravovat přenos parametrů do samostatných modelů 2025, 2040 a 2070, poté jejich vlastní přepočet a schválené RPDI→den/večer/noc výstupy. Matice, scénářové přepočty ani exporty zde ještě nebyly vytvořeny. Zůstávají potřebné cílové modely, převodní koeficienty, jednotky a formáty exportů.

Výsledek: **9 kontrol metadat PASS**; přesné podmínky jsou v CHECKPOINT_CONFIRMATION.json. Produkční soubory a manifesty zůstaly beze změn. Visum/COM: NOT_RUN.
