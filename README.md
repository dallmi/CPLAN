# Profitability

Werkzeugkasten für Kostenverteilung: rechnet beliebige Kostentreiber
(Headcount, Umsatz, Tickets, Quadratmeter, …) in **prozentuale Verteilungen**
um und verteilt damit Kosten **centgenau** auf Kostenobjekte (Abteilungen,
Produkte, Projekte, …).

Reines Python (Standardbibliothek, keine Abhängigkeiten), ab Python 3.10.
Excel-Unterstützung (.xlsx) ist optional und braucht `openpyxl`.

## Für jeden Bereich

Die Logik ist bewusst domänen-neutral: Kostenobjekte und Treiber sind frei
benennbare Größen. Derselbe Mechanismus trägt damit jeden
Unternehmensbereich — interne Kommunikation, Marketing, Client
Profitability im Banking, Facility, IT-Verrechnung usw. Ein „Bereich“ ist
einfach ein eigenes Paar aus Treiber- und Kostendatei.

Der Standard-/Referenzbereich ist **Interne Kommunikation im Banking**
(`examples/internal_comms_*.csv`): Kostenobjekte sind Divisionen
(Wealth Mgmt, Investment Bank, Retail & Corporates, Asset Mgmt), Treiber
sind erreichte Mitarbeitende, Comms-Aktivitäten, Intranet-Reichweite und
Townhall-Teilnahmen.

```bash
profitability allocate \
    --costs examples/internal_comms_costs.csv \
    --drivers examples/internal_comms_drivers.csv
```

## Kernidee

1. **Treiberwerte → Verteilung.** Aus beliebigen Rohwerten pro Objekt wird
   eine exakte Verteilung (Summe = 100 %). Intern wird mit Brüchen
   (`fractions.Fraction`) gerechnet — es geht keine Präzision verloren.
2. **Verteilung → Beträge.** Ein Betrag wird entlang der Verteilung
   aufgeteilt und nach dem **Größte-Reste-Verfahren** gerundet: Die
   Teilbeträge summieren sich immer exakt auf den Ausgangsbetrag
   (keine 99,99-%-Probleme, kein verlorener Cent).
3. **Treiber mischen.** Kostenzeilen können einen einzelnen Treiber nutzen
   (`headcount`) oder eine gewichtete Mischung (`headcount:70,revenue:30`).
4. **CSV oder Excel.** Ein- und Ausgabedateien dürfen `.csv` oder `.xlsx`
   sein — die CLI erkennt das Format an der Dateiendung.

## Installation

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"    # Entwicklung: pytest + openpyxl
.venv/bin/pip install -e ".[xlsx]"   # nur Nutzung inkl. Excel-Unterstützung
```

## CLI

Treiberwerte in Prozente umrechnen:

```bash
profitability distribute --drivers examples/drivers.csv
profitability distribute --drivers examples/drivers.csv --driver headcount --precision 4
```

Kosten verteilen:

```bash
profitability allocate --costs examples/costs.csv --drivers examples/drivers.csv
profitability allocate --costs examples/costs.csv --drivers examples/drivers.csv --out result.csv
```

Dasselbe mit Excel — beide Tabellen dürfen im selben Workbook liegen,
das Arbeitsblatt wird über `--drivers-sheet` / `--costs-sheet` gewählt
(ohne Angabe: das aktive Blatt). Endet `--out` auf `.xlsx`, wird Excel
geschrieben:

```bash
profitability allocate \
    --costs examples/profitability.xlsx --costs-sheet costs \
    --drivers examples/profitability.xlsx --drivers-sheet drivers \
    --out result.xlsx
```

(Ohne Installation geht auch `python -m profitability ...` aus dem Repo-Root.)

### CSV-Formate

`drivers.csv` — ein Wert je Treiber und Objekt (mehrfach vorkommende
Treiber/Objekt-Paare werden summiert, z. B. Monatswerte):

```csv
driver,object,value
headcount,IT,50
headcount,HR,10
headcount,Sales,40
revenue,Sales,1250000
```

`costs.csv` — eine Zeile je Kostenposition; `driver` ist ein Treibername
oder eine gewichtete Mischung:

```csv
cost,amount,driver
Office rent,120000.00,sqm
Shared platforms,50000.00,"headcount:70,revenue:30"
```

Für Excel gilt dasselbe Spaltenlayout (Kopfzeile plus Datenzeilen);
Groß-/Kleinschreibung der Kopfzeile ist egal, zusätzliche Spalten und
Leerzeilen werden ignoriert. `examples/profitability.xlsx` zeigt beide
Tabellen in einem Workbook.

Ergebnis (`allocate --out`): `cost,driver,object,share_percent,amount` —
die `amount`-Werte je Kostenposition summieren sich exakt auf den
Ausgangsbetrag.

## Python-API

```python
from decimal import Decimal
from profitability import Distribution, allocate

headcount = Distribution.from_values({"IT": 50, "HR": 10, "Sales": 40})
revenue = Distribution.from_values({"IT": 0, "HR": 0, "Sales": 1_250_000})

headcount.percentages()          # {'IT': 50.00, 'HR': 10.00, 'Sales': 40.00} (Summe exakt 100)
allocate(Decimal("100.00"), Distribution.equal(["A", "B", "C"]))
# {'A': 33.34, 'B': 33.33, 'C': 33.33} — Summe exakt 100.00

# Treiber gewichtet mischen (70 % Headcount, 30 % Umsatz):
mixed = Distribution.combine([(headcount, 70), (revenue, 30)])

# Fixanteil plus Rest pro rata (Overhead bekommt fix 10 %):
with_overhead = headcount.with_fixed({"Overhead": "1/10"})
```

Ganze Kostentabellen:

```python
from profitability import CostLine, allocate_costs

rows = allocate_costs(
    [CostLine("Rent", Decimal("120000.00"), "headcount")],
    {"headcount": headcount},
)
```

### Umgang mit Sonderfällen

- **Negative Treiberwerte** (z. B. Gutschriften im Umsatz): standardmäßig ein
  Fehler; per `negatives="zero"` (ignorieren) oder `negatives="absolute"`
  (Betrag verwenden) steuerbar — in der CLI via `--negatives`.
- **Negative Beträge** (Gutschriften) werden symmetrisch zu positiven
  Beträgen verteilt.
- **Rundung**: `--precision` bzw. `precision=` steuert die Nachkommastellen
  (Standard 2 = centgenau); die Summe stimmt bei jeder Präzision exakt.

## Tests

```bash
.venv/bin/pytest
```
