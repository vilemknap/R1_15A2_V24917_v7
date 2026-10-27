# V2.3 zmeny proti V2.2

- Nova `ActualSequenceRouteCollector` zalozena na overenem V2.2 `ActualRouteCollector`.
- Ulozene path sekvence z official PrT listu v SQLite evidence se zachovanym
  DSeg/OD/PathIndex, Vol(AP), serazenymi linky a CAL class atribuci.
- Parovani ON/OFF pouze ve stejnem DSeg a OD marketu.
- Diverge/rejoin kotvy nad skutecne spolecnymi uzly a selekce realne
  kontiguitni vetve kolem sčítacího profilu, bez Dijkstry a bush aproximace.
- Volume-weighted agregace opakovanych identickych sekvenci napric markety.
- Candidate ON i OFF s obema signy pro over/under counted profiles.
- Pri nedostupne OFF alternative explicitne oznaceny ON-only probe.
- Kontiguitni shortening a CAP-SPLIT `[8,4,2,1]` se zachovanim alespon
  jednoho samostatneho kandidata pri omezenem maximalnim poctu pokusu.
- All-saved-path exact direct-cost impact vcetne opakovanych hran,
  ostatnich CAL, protected CAL a mimo-CAL paths. VALID nikdy neurcuje vyber.
- Original V2.2 checkpoint, ten-seconds-unit, frozen demand, COM readback,
  shared ledger, TG/TD a exact rollback jsou dedeny beze zmen.
- Prod live COM gate zustava nesplnen; jde o offline verified development release.
