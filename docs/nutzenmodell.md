# Nutzenmodell: den Wert interner Kommunikation messen

Profitabilität ist Nutzen ÷ Kosten. Die Kostenseite verteilt dieses Werkzeug
bereits centgenau über Treiber; dieses Dokument beschreibt die Nutzenseite —
speziell für den Referenzbereich **Interne Kommunikation im Banking**, aber
nach demselben domänen-neutralen Mechanismus.

## Grundprinzip: Nutzen ist eine Verteilung, wie Kosten auch

Ein Nutzenmaß ist technisch dasselbe wie ein Kostentreiber: ein Wert je
Kostenobjekt, der zu einer prozentualen Verteilung normalisiert wird. Mehrere
Maße werden gewichtet gemischt (z. B. Reichweite 30 % · Engagement 40 % ·
Wirkung 30 %). Das Ergebnis ist der **Nutzwert-Index**: eine Punkteverteilung
(Standard: 1.000 Punkte), die man den Kostenanteilen gegenüberstellt.

Daraus entstehen drei Kennzahlen je Objekt (Division, Segment, …):

| Kennzahl | Bedeutung |
|---|---|
| **Nutzwert-Punkte** | Anteil am Gesamtnutzen, größte-Reste-gerundet (Summe exakt) |
| **€ je Nutzenpunkt** | zugerechnete Kosten ÷ Punkte — „was kostet uns ein Punkt Wirkung hier?“ |
| **Effizienz-Index** | Nutzenanteil ÷ Kostenanteil × 100 — über 100: mehr Nutzen als Kostenanteil |

Der Index ist bewusst **relativ**, keine Euro-Rendite — außer das Nutzenmaß
ist selbst monetär (Client Profitability: Erträge je Segment ⇒ der Index ist
dann echte Profitabilität).

## Die Wirkungstreppe für interne Kommunikation

Vier Stufen, von leicht messbar zu beweiskräftig. Je höher die Stufe, desto
stärker die Aussage — und desto wichtiger, Messaufwand und Attribution ehrlich
zu halten.

### Stufe 1 — Reichweite (Output)
*Wurde die Botschaft zugestellt?*

- Erreichte Mitarbeitende (Unique Visitors je Division — die
  CPLAN-Tracking-IDs sind genau dafür gebaut: kanalübergreifende
  Unique-Messung, Views je Kanal, Aggregation auf Pack-/Cluster-Ebene)
- Öffnungs-/Zustellraten je Kanal, Townhall-Teilnahmen
- Abdeckung der Zielgruppe (erreicht ÷ Estimated audience size aus der
  Aktivität)

### Stufe 2 — Engagement (Outtake)
*Wurde sie beachtet und verarbeitet?*

- Lesetiefe/Verweildauer, Scroll-Tiefe
- Interaktionen: Klicks auf weiterführende Links/CTA, Likes, Kommentare,
  Shares, Digest-Abos
- Wiederkehrende Nutzung der Divisions-Kanäle

### Stufe 3 — Wirkung (Outcome)
*Hat sie Verständnis oder Verhalten verändert?*

- **Pulse-Checks**: 2–3 Fragen direkt an der Kommunikation („Kernbotschaft
  verstanden?“, „weiß, was zu tun ist“) — Zustimmung × Befragte als Punktwert
- Message-Recall in bestehenden Engagement-Umfragen, Alignment-Scores
- **Verhaltens-Proxys**: Abschlussquote von Pflichttrainings nach Kampagne,
  Tool-/Policy-Adoption, Anmeldungen, Rückgang von Rückfragen/Tickets zu
  kommunizierten Themen

### Stufe 4 — Geschäftswert (monetarisiert, optional)
*Was ist das in Euro — als transparente Modellannahme, nie als Scheinpräzision:*

- eingesparte Such-/Rückfragezeit × Stundensatz (z. B. Ticket-Rückgang ×
  Bearbeitungszeit)
- vermiedene Compliance-/Risikokosten (erreichte Frist- und Schulungsquoten)
- Engagement-Korrelate (Fluktuation, Absenzen) nur als Bandbreite mit Quelle

**Empfehlung:** Stufen 1–3 in den Nutzwert-Index mischen (Startgewichtung
30/40/30, je Bereich anpassbar); Stufe 4 separat als Szenario ausweisen.

## Woher die Daten kommen

- **CPLAN** liefert die Struktur: Aktivitäten mit Tracking-IDs, Divisionen,
  Zielgruppen, Audience-Bänder, Packs/Cluster — die Verteilschlüssel und die
  Zuordnung „welche Kommunikation zahlt auf welches Objekt ein“.
- **Die Analytics-Plattform** (Views-/Engagement-Reporting je Tracking-ID,
  z. B. eine Databricks-Pipeline) liefert die Messwerte der Stufen 1–2 als
  Export — eine Zeile je Metrik und Objekt genügt (`driver,object,value`).
- **Umfrage-/HR-Systeme** liefern Stufe 3 (Pulse, Trainings-, Adoptionsquoten).

## Nutzung im Werkzeug

Nutzenmaße nutzen dasselbe Dateiformat wie Treiber (`driver,object,value`):

```bash
profitability cost-benefit \
    --costs examples/internal_comms_costs.csv \
    --drivers examples/internal_comms_drivers.csv \
    --benefits examples/internal_comms_benefits.csv \
    --benefit-mix "reach:30,engagement:40,outcome:30"
```

Ausgabe je Division: Kosten, Kostenanteil, Nutzenanteil, Nutzwert-Punkte,
€ je Punkt und Effizienz-Index. `--out result.csv` schreibt das Ergebnis.

## Ehrlichkeitsregeln

1. **Attribution benennen**: Outcome-Metriken korrelieren, sie beweisen keine
   Kausalität — Formulierungen wie „nach der Kampagne“ statt „durch die
   Kampagne“, außer es gab ein Kontrolldesign (z. B. gestaffelter Rollout).
2. **Keine Zahl ohne Nenner**: Reichweite immer relativ zur Zielgruppe.
3. **Index ≠ Euro**: Der Nutzwert ist ein Vergleichsmaß zwischen Objekten
   desselben Bereichs; Bereiche untereinander vergleicht man nicht über den
   Index.
4. **Gewichte offenlegen**: Die Mischung (30/40/30) ist eine Entscheidung,
   kein Messergebnis — sie gehört sichtbar neben jedes Ergebnis.
