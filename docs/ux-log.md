# ux-Log — Laufhistorie CPLAN Studio

Archiv des `GEPRUEFT`-Blocks aus `.ux.md`, ausgelagert am 2026-08-06. Grund: die
`.ux.md` wird bei jedem Loop-Lauf vollstaendig gelesen, und die Historie war auf
462 der 553 Zeilen gewachsen — 83 % der Datei.

**Der `ux`-Loop liest diese Datei nie.** Sie ist Nachschlagewerk fuer Michael.

Reihenfolge unveraendert, so wie die Eintraege entstanden sind: Laeufe mit
Datum, dazwischen die Befunde, Lehren, Waechter-Test-Anpassungen und offenen
Punkte, die zum jeweils darueberstehenden Lauf gehoeren. Zeitraum 2026-07-28
bis 2026-07-30, rund 20 Laeufe.

---

```
2026-07-28  Persona A, Studio Overview/Activities/Planning/
            Analytics + Anlege-Formular. 3 Runden.
            Sprosse 1 gruen, Sprosse 3 gruen (nach Reparatur).
            Sprosse 2 offen: 375px Ueberlauf in Analytics
            (Tabelle 16px) und Planning (Segment 13px);
            ob 375px gilt, ist nicht entschieden.
            Sprosse 4: 1 von 4 gruen.
              A1 neue Aktivitaet     rot (Griff richtig,
                 aber per Ausschluss geraten)
              A2 unvollstaendige      GRUEN
              A3 als Vorlage nutzen   rot (geraten)
              A4 mehrere Kanaele      rot (falsches Ziel)
            ABBRUCH Runde 3: Einstiegspunkt auf dem
            Startbildschirm ist eine IA-Entscheidung.

2026-07-28  Persona B: 3 von 3 gruen.
2026-07-28  Persona C: 0 von 5. Persona D: 0 von 4.
            Gesamt ueber alle vier Personas: 4 von 16.
            Uebergabe an build, danach erneuter Lauf.

2026-07-29  Nach dem build-Durchgang, 8 zuvor rote Aufgaben
            erneut geprueft, diesmal mit Vollseiten-Screenshot.
              C4 Feld-Systematik   ROT -> GRUEN (Sprunglink)
              D3 Weisse Flecken    ROT -> GRUEN (Nullzeilen)
              A1 A3 A4 C3 C5 D1    weiter rot
            Gesamt geschaetzt 6 von 16.
            ABBRUCH: was oberhalb der Falz steht, ist eine
            Layout-Entscheidung des Nutzers.

2026-07-29  Nach dem IA-Umbau (Overview = Steuerung fuer D,
            Planer-Nacharbeit unter Planning).
              D1 strategische Abdeckung  ROT -> GRUEN
              D4 Kollisionen             ROT -> GRUEN
              A2 B3 kurz regressiert, durch Signalzeilen
                 auf Overview wieder GRUEN
              B1 unveraendert GRUEN
              A1 A4 weiter rot: Overview hat bewusst keine
                 Handlungsecke mehr
              C4 weiter rot: Feldsicht liegt zwei Klicks tief
            ABBRUCH: beides sind Entscheidungen des Nutzers.

2026-07-29  Nach Anlege-Knopf auf Overview und dritter,
            feldbezogener Signalzeile:
              A1 anlegen        ROT -> GRUEN
              A4 mehrere Kanaele ROT -> GRUEN
              C4 Feldsicht      ROT -> GRUEN
              D1 Kontrolle      weiter GRUEN
            8 von 8 nachgeprueften Aufgaben gruen.
            Nicht nachgeprueft: A3 B2 C1 C2 C3 C5 D2 D3.

2026-07-29  Namenstest fuer den vierten Reiter, ohne Bild,
            nur Reiternamen plus Aufgabe, Selbsteinschaetzung
            der Sicherheit 1-5:
              Analytics          C4 richtig/2  D1 FALSCH/2
              Health             C4 richtig/2  D1 FALSCH/3
              Quality & Coverage C4 richtig/4  D1 richtig/4
            "Health" ist schlechter als "Analytics" — es
            schickt D auf Planning. Grund laut Agenten:
            Analytics und Health benennen Methode bzw.
            Zustand, Quality & Coverage benennt zwei Fragen.
            Umbenannt. Danach im Bild geprueft: C4 D3 gruen,
            D1 Griff richtig, C5 weiter rot.
            Der Reitername taucht jetzt in allen Antworten
            als benannter Ersatzweg auf, statt "auf gut
            Glueck" — genau sein Zweck.

2026-07-29  Overview auf Sammelkacheln umgebaut (Muster aus
            dem SiteOwnerDashboard, auf Haus-Tokens und
            Satzschreibung portiert): Volume, Timing,
            Coverage, Quality.
              D Ueberblick ohne Klick  Klarheit 4 von 5,
                drei belastbare Aussagen in 10 Sekunden
              D1 D3 C4 Griff jeweils richtig
            Befund aus dem Lauf, sofort behoben: Coverage
            zeigte nackte Zaehler. "4 Zielgruppen erreicht
            sagt mir nicht, ob das 4 von 5 oder 4 von 20
            sind." Jetzt "3 of 4 Audiences next 30d" — die
            Luecke zwischen Zaehler und Nenner IST der
            weisse Fleck.

2026-07-29  Offene Punkte abgearbeitet:
            - jede Kennzahl traegt jetzt eine Bezugsgroesse
              (Anteil am Portfolio bzw. Zielwert), keine
              erfundenen Trends
            - Feldabdeckung listet ALLE Formularfelder statt
              nur der fehlenden Pflichtfelder. Sofortiger
              Fund: Business area und Partner team sind in
              allen 400 Datensaetzen leer — vorher
              unentdeckbar. Erklaert auch 108 gegen 89.
            - Sprunglink je Kachelgruppe, damit "Open
              strategic coverage" nicht mehr auf der
              Division-Karte sitzt
            - Kanal x Zielgruppe / Kanal x Pillar als
              Kreuztabelle unter Coverage & channel mix.
              Bewusst nur Mengen: Wirksamkeit braucht
              Ergebnisdaten, die CPLAN nicht erfasst.
            D-Ueberblick weiterhin Klarheit 4 von 5.
            C5 Griff noch daneben — Kreuztabelle liegt zwei
            Klicks tief, Unterseite dafuer umbenannt.

2026-07-29  Vorperioden-Vergleich eingebaut. Nur fuer Werte,
            die aus start_date kommen — Vollstaendigkeit und
            Pack-Abdeckung sind Bestandswerte, und niemand
            hat festgehalten wie der Bestand vor 30 Tagen
            aussah. Ein Delta darauf waere erfunden.
            Erster Anlauf: Klarheit 2 von 5, SCHLECHTER als
            ohne Deltas. Ursache: Richtung nur ueber Farbe
            codiert — Verstoss gegen die Hausregel, dass
            Farbe nie alleiniger Traeger ist. "Bei +3 sehe
            ich nicht, ob Anstieg gut oder schlecht ist."
            Nachgebessert: Richtung im Wort (+3 worse,
            -3 better, +5 more), ein Gesamturteil ueber
            allem, einheitlicher Vergleichszeitraum, keine
            Null-Chips. Danach 3 von 5.

2026-07-29  Eigene Runde fuer den Trendrand. Monate ab dem
            laufenden sind gestrichelt umrandet, Beschriftung
            kursiv, eigener Legendeneintrag, plus Fussnote
            mit dem echten Medianvorlauf.
            GELOEST: Deutung des Abfalls jetzt Sicherheit
            4 von 5. "Kein echter Rueckgang, sondern ein
            Erfassungs-Artefakt" — und ausdruecklich:
            "ohne die Fussnote haette ich einen Einbruch
            gemeldet."
            Gesamturteil D von "Nein, nur gemischt" auf
            "Ja, gemischt, leicht besser". Klarheit 3 von 5.

2026-07-29  Zufluss statt Bestand. Korrektur einer eigenen
            Fehleinschaetzung: ich hatte "braucht Datenmodell-
            aenderung" behauptet, ohne zu pruefen. Das Modell
            traegt source_created_at fuer alle Datensaetze —
            damit ist die Qualitaet des ZUFLUSSES vergleichbar,
            auch wenn der BESTAND es nicht ist. Neu:
              Complete on intake, 30 neue, vs 30 davor
              New with a pack, dito
              Created in last 30d im Volume
            Alle Kennzahlen so formuliert, dass mehr = besser,
            weil "-14 worse" neben "-10 better" den Leser
            rechnen laesst. Verdikt fuehrt mit einem Wort.

2026-07-29  BESITZER GEWECHSELT. Der Nutzer hat die Overview dem
            Planer zugesprochen, D nur noch gelegentlich. Damit ist
            die Praemisse der vier Sammelkacheln hinfaellig: sie
            waren fuer jemanden gebaut, der das Portfolio ein paar
            Mal im Jahr in einem Blick braucht.
            LEITFRAGE  "Wie steht mein Plan fuer die naechsten
                       Wochen - und wo muss ich ran?"
            BUDGET     ueber der Falz 1 Verdikt, 6 Zahlen,
                       2 Signale, 1 Liste
            Gemessen vorher/nachher: Zahlen ueber der Falz 23 -> 9
            (6 Kennzahlen plus ihre Bezugsgroessen), Kacheln 4 mit
            16 Zeilen -> 6 Zahlen, Baender 4 gleichrangig -> 2
            gerankt plus Restzeile, Seitenhoehe 2,7 -> 1,44
            Bildschirme, Verdikt-Kleingedrucktes 441 -> 0 Zeichen
            ausser dem Still-filling-Vorbehalt.
            Die Kennzahl ist jetzt selbst der Weg (Kachel = Knopf),
            deshalb konnten die vier "Open ->"-Links entfallen.

BEFUND      893px leere Karte. Channel load war 1065px hoch fuer
            172px Inhalt, weil das zweispaltige Raster sie auf die
            Hoehe der 17-zeiligen Nachbarliste streckte. Das ist
            gemessen die groesste Einzelquelle des Ueberladen-
            Eindrucks gewesen - nicht die Zahl der Kennzahlen.
            Liste auf 8 gekappt mit Rest-Fusszeile, Karten sizen
            auf eigenen Inhalt.

BEFUND      app.js enthielt 4 literale NUL-Bytes (Trennzeichen in
            Map-Schluesseln der Kreuztabelle). grep behandelt die
            Datei damit als binaer und meldet STILL keine Treffer -
            jede grep-gestuetzte Pruefung, auch die eigene
            Preflight, uebersah die zentrale Datei des Studios.
            Ersetzt durch ' '. Verhaltensgleich.

BEFUND      Ein einzelner Wert ohne Leerzeichen (getestet mit einem
            deutschen Kompositum in activity_name, channel,
            lead_team) trieb das Dokument bei 1280px auf 2698px
            Breite. Ursache: Grid- und Flex-Kinder haben
            min-width:auto und weigern sich, unter ihren Inhalt zu
            schrumpfen. .list-row/.list-title/.chip klemmen jetzt.

BEFUND      Ein Portfolio von genau 1 las sich an drei Stellen als
            Bug: "1 activities", "1 activities are incomplete",
            "the 1 days before". Jetzt ein plural()-Helfer.

BEFUND      Leere Auswahl zeigte " of 0 activities" (Fragment) und
            "0% of the portfolio is complete" (falsch - nichts ist
            unvollstaendig, wenn nichts existiert). Ausserdem
            listete das Idle-Signal alle neun Kategorien auf.
            Bezugsgroessen sind jetzt an rows.length gebunden, das
            Idle-Signal schweigt bei leerer Auswahl und nennt sonst
            hoechstens drei.

LEHRE       Die Restzeile eines Caps braucht das Ziel des naechsten
            zurueckgehaltenen Befunds, nicht ein festes. Erste
            Fassung schickte bei zwei belegten Slots den Daten-
            steward auf planning:board, obwohl der gekappte Befund
            auf data-quality lag - genau die Strandung, vor der die
            Lehre weiter unten warnt.

WAECHTER    Zwei Tests zogen mit, beide einzeln begruendet:
            - test_studio.py::test_kit_compliance_pass: die drei
              Donut-Centre-Zusicherungen (centerSub, 'mentions',
              'activities') hatten keinen Gegenstand mehr. Ersetzt
              durch assertNotIn("donutHtml").
            - test_studio_list.py: der Fuenf-Farben-Test des
              Prioritaets-Donuts. Umbenannt in
              test_priority_is_a_count_not_a_ring, pinnt jetzt die
              Abwesenheit. Nicht aufgeweicht - der Pruefpunkt
              existiert nicht mehr.
            Gesamt danach 269 passed, 54 skipped, 30 JS-Tests.

OFFEN       Sprosse 5 (Fremder Blick) NICHT gefahren. Subagenten
            sind in dieser Sitzung untersagt, und den Test mit
            eigenem Vorwissen zu fahren waere Aufweichen. Die
            Sprossen 1-4 sind gemessen gruen; ob A1-A4, B1-B3, C4,
            D1, D3, D4 nach dem Besitzerwechsel noch greifen, ist
            damit UNGEPRUEFT und der naechste Schritt.

2026-07-29  IA-UMBAU. 12 Ziele auf 4, keine Unterseiten mehr.
            Vorher: 4 Reiter + 8 Unterseiten, 22 Karten.
            Nachher: Overview | Activities | Packs | Health.
              Board + Kalender  -> Ansichtsschalter der Overview
                                   (Liste/Zeitachse/Kalender), weil
                                   es drei Layouts EINES Vorwaerts-
                                   fensters sind
              Conflicts         -> Issue-Filter der Activities, das
                                   paarweise Workbench-Panel faehrt
                                   mit der Warteschlange mit
              Capacity          -> Health, Abschnitt Coverage
              Campaign Quality  -> neuer Packs-Reiter
              Planning-Reiter   -> aufgeloest
            Attention required wanderte als "Needs you first" auf
            die Overview und ersetzt dort drei der vier Signal-
            baender: Konflikte, Unvollstaendigkeit und Kurzfristig-
            keit standen zweimal auf einem Bildschirm. Uebrig
            bleiben die zwei Befunde, die in keiner Aktivitaets-
            Warteschlange vorkommen: das leere Feld und die
            Abdeckungsluecke.

BEFUND      campaignScorecards gruppierte nach tracking_pack_id und
            warf damit 273 bzw. 125 Aktivitaeten in je EIN "Pack".
            Das explizite Feld communication_pack_cpid ergibt 32
            Packs zu 2-11. Schluesselreihenfolge umgedreht; jede
            Auswertung darauf (Kanalbreite, Quiet period,
            Orchestrierung) beschrieb vorher das Portfolio statt
            einer Planungseinheit.

ENTSCHEIDUNG Nutzer wollte Coverage & channel mix ganz streichen.
            Widersprochen: es ist der einzige Weg zu D1 und D3, und
            das Idle-Signal der Overview zeigt als einziges Ziel
            dorthin. Kompromiss umgesetzt: der REITER verschwindet,
            der tragende Inhalt wird ein Abschnitt der Health-Seite.
            Pillar coverage und Division coverage ersatzlos
            geloescht - "Coverage by dimension" sagt dasselbe und
            deckt zusaetzlich Team, Audience und Region ab, mit
            Nullzeilen.

WAECHTER    Drei Tests zogen mit, je einzeln begruendet:
            - planning-new -> packs-new (Seite aufgeloest, Regel
              "ein Primary je page-actions" unveraendert)
            - assertNotIn(">New pack<") gestrichen: sie zielte auf
              das zweite Primary IM Drawer (#pack-new), nicht auf
              den Seiten-CTA. Jetzt per id gepinnt statt per Label.
            - barList(divisions) entfernt; die Invariante ist die
              Schleife ueber ALLE Aufrufstellen, die bleibt.
            - queue-bar-clear blendet zusaetzlich das Konflikt-Panel
              aus. Getrennte Reset-Reichweiten unveraendert.
            269 passed, 54 skipped, 30 JS-Tests.

OFFEN       "Look back" des Prototyps (Reach per channel, People
            reached) ist NICHT baubar: CPLAN erfasst Planung, keine
            Wirkung. `audience` ist eine geplante Zielgruppen-
            groesse, keine erreichte Reichweite.
            Pack-Owner und Pack-Status existieren nicht als Felder.
            Status waere ableitbar (alles in der Vergangenheit),
            Owner nicht - Datenmodellfrage.

OFFEN       Packs (4,67 Bildschirme) und Health (4,52) sind lange
            Scrollseiten. Das ist der Preis fuer die weggefallenen
            Untermenues; Health hat Sprunganker, Packs ist eine
            Liste und darf lang sein. Ob das im Alltag traegt, ist
            UNGEPRUEFT.

2026-07-30  Kanalfarbe aus dem Campaign-Studio-Prototyp uebernommen:
            kleines Vollquadrat vor dem Kanalnamen, in Tabelle,
            Drawer, Packs-Liste und Coming-up-Chips.
            Zwei Randbedingungen, die der Prototyp nicht hatte:
              - Seine Palette deckt 6 Kanaele, die Produktion traegt
                rund 40. Farben wiederholen sich also; deshalb steht
                der Name IMMER daneben und wird nie ersetzt. Der
                Punkt ist eine Lesehilfe, kein Bezeichner.
              - Zuordnung ueber die Position in der sortierten
                Kanalliste, nicht ueber einen Hash: ein neuer Kanal
                haengt sich an, statt die Tabelle umzufaerben.
            Palettenreihenfolge NICHT alphabetisch schoen, sondern
            nach Abstand: sortiert lagen Intranet auf bronze-1 und
            Town Hall auf bronze-2 - zwei Brauntoene, die ein 9px-
            Quadrat nicht trennt. Jetzt alternieren Familie
            (bordeaux/bronze/grau) und Helligkeit.
            Kontrast der Punkte gegen die Zeile gemessen: 3,01 bis
            12,87 - alle ueber der 3:1-Schwelle fuer nichttextuelle
            Elemente.

2026-07-30  Drawer: 2px-Primary-Kante unter dem Kopf (der Prototyp
            trennt so klebrigen Kopf von scrollendem Koerper) und
            ein Zustandsabzeichen neben der Tracking-ID. Das Studio
            hat kein Statusfeld, also traegt das Abzeichen die
            Vollstaendigkeit - dieselbe Regel wie Issue-Spalte und
            Overview-Warteschlange, nie ein zweites Urteil. Beim
            Anlegen ausgeblendet, dort zaehlt die Ready-Line.

2026-07-30  Packs-Liste von Zeilen auf TABELLE mit eigener Kanal-
            spalte umgestellt (Muster aus dem Prototyp, vom Nutzer
            im Screenshot markiert). Vorher liefen Kanalnamen hinter
            Anzahl und Zeitfenster in einer Meta-Zeile aus und lasen
            sich als Unordnung; in einer Spalte fluchten sie
            untereinander und die Kanalverteilung des Portfolios
            wird in einem senkrechten Blick lesbar.
            Ein Chip je KANAL, nicht je Tracking-ID: der Prototyp
            kann eine ID je Chip drucken, weil seine Packs einen
            Versand je Kanal haben. Unsere haben im Schnitt 7,9
            Aktivitaeten auf vier bis fuenf Kanaelen - je-ID-Chips
            haetten elf Stueck in eine Zelle gelegt und genau das
            Gedraenge neu gebaut. Zahl faehrt mit, IDs im Drawer.

KORREKTUR   Ich wollte "Audiences" und "Lead teams" streichen, weil
            im Screenshot jede Zeile gleich aussah. Nachgemessen:
            27 von 32 Audience-Werten und 26 von 32 Team-Werten sind
            VERSCHIEDEN. Die Spalten tragen also Information; das
            Problem war die Reihenfolge - dieselbe Vierermenge kam
            je Pack anders sortiert an und war dadurch nicht
            vergleichbar. Jetzt sortiert und bei zwei gekappt
            ("+2"). Erst messen, dann loeschen.

2026-07-30  Kanalkarten im Pack-Drawer tragen jetzt die Issue-Chips
            der Aktivitaetentabelle statt eines Zaehler-Abzeichens.
            Ein Abzeichen sagt, dass etwas fehlt, und laesst den
            Planer suchen; der Chip nennt das Feld und oeffnet den
            Datensatz darauf. Gleiches Markup, deshalb faehrt der
            delegierte [data-fix-id]-Handler ohne eigene Verdrahtung
            mit, und beide Oberflaechen lesen A.rowIssues - der
            Befund kann nicht auseinanderlaufen.
            Geprueft: Chip "Description" -> Aktivitaets-Drawer im
            Bearbeitungsmodus, Cursor in activity_description,
            Pack-Drawer bleibt darunter offen.

BEFUND      Escape schloss den Pack-Drawer UNTER dem darueber
            geoeffneten Aktivitaets-Drawer. Jetzt antwortet nur die
            oberste Schicht; zweimal Escape schaelt Lage fuer Lage.

BEFUND      Selbst eingebaut und beim Nachpruefen gefunden: mit dem
            Umbau der Packs-Liste auf eine TABELLE wurde sie
            tastaturunbedienbar. Die Zeilen sind <tr>, und
            bindOpenRows ueberspringt <tr> bewusst (C4). Der Fokus
            landete nach dem Schliessen im BODY. Namenszelle ist
            jetzt ein echter name-btn wie in der Aktivitaeten-
            tabelle, Zeile bleibt Mausbequemlichkeit, mit derselben
            stopPropagation-Sicherung gegen doppeltes Oeffnen.
            LEHRE: eine Liste in eine Tabelle umzubauen nimmt ihr
            die Fokussierbarkeit, weil <tr> keinen Fokus nimmt.

MESSRAUSCHEN Vier Laeufe derselben Aufgabe ergaben 3, 3, 3, 2.
            Die Skala rauscht um +-1, und ein Lauf lobte den
            Einleitungssatz, den der naechste nicht bemerkte.
            Einzelne Punktwerte sind daher kein Signal —
            erst eine Aenderung um 2 Stufen oder ein
            wiederholt genannter Sachbefund zaehlt.

2026-07-29  Vorzeitraum folgt jetzt dem Bereichsfilter.
            Gewaehlter Bereich gegen den gleich langen davor,
            ohne Bereich weiter 30 Tage. Vergleichsmengen aus
            snapshotRows, weil state.rows bereits nach
            start_date gefiltert ist und den Vorzeitraum gar
            nicht mehr enthaelt — daraus haette jeder
            Vergleich null gemeldet.
            Drei Folgefehler dabei gefunden und behoben:
              - Quarter vergleicht ueberwiegend Zukunft gegen
                vollstaendig geplante Vergangenheit. Fenster,
                die ueber heute hinausreichen, sind jetzt als
                "still filling" markiert.
              - YTD und 12M meldeten "Improving", weil ihr
                Vorzeitraum vor dem Datenbeginn liegt und
                jede Kennzahl dort null ist. Ohne Basis kein
                Vergleich, und das Verdikt sagt es.
              - Verdikt behauptete "previous 30 days"
                unabhaengig vom gewaehlten Bereich.

2026-07-29  Chips auf die zwei groessten Bewegungen begrenzt,
            Verdikt in Kernaussage plus Kleingedrucktes
            getrennt, groesster Ausschlag namentlich genannt.
            Klarheit bleibt 2 von 5.

ERKENNTNIS  Sechs Varianten der Delta-Darstellung gemessen:
            4 (ohne Deltas, andere Frage), dann 2, 3, 3, 3,
            2, 2. Die Zahl bewegt sich nicht. Zwoelf Chips
            waren zu viel ("ich muss sechs Werte selbst
            aufrechnen"), zwei sind zu wenig ("warum stehen
            bei Volume und Coverage gar keine Deltas").
            Die Darstellung der Deltas ist nicht der Hebel.

KERNPROBLEM Die Seite hat keine Rangfolge. Vier gleich grosse
            Kacheln, vier gleich aussehende gelbe Baender
            ohne Reihenfolge, und als groesstes Element der
            Monatstrend, dessen Botschaft lautet "lies meine
            letzten vier Balken nicht als Rueckgang".
            Woertlich: "Die dominanteste Grafik der Seite
            sendet aktiv das falsche Signal." und "Vier
            gleich aussehende Hinweisbaender ohne Rangfolge
            — welches ist der termin-relevante Punkt?"
            Naechster Hebel ist visuelles Gewicht, nicht
            Zahlendarstellung.

LEHRE       node --check prueft Syntax, keine temporale
            Totzone. Ein Zugriff auf cmpPrev vor der
            Deklaration kam durch alle 352 Tests und fiel
            erst im Browser auf. Die Fensterarithmetik sitzt
            deshalb jetzt als reine Funktion in analytics.js
            (comparisonWindow) und hat einen Test.

ABBRUCH     Weiter kommt der Loop nicht ohne Datenmodell-
            aenderung. "Der ganze Rest der Seite zeigt
            Zustaende statt Entwicklung" — richtig, und
            unaufloesbar: Vollstaendigkeit, Pack-Abdeckung
            und die Hinweiszeilen koennten nur dann eine
            Veraenderung zeigen, wenn jemand taeglich einen
            Qualitaets-Schnappschuss wegschreibt. Das ist
            eine Produktentscheidung, keine Layoutfrage.

OFFEN       Kennzahlen tragen keine Richtung. "Kein gut oder
            schlecht, keine Trendrichtung — Ampelurteile muss
            ich selbst mitbringen." Braucht Vergleichswerte
            oder Schwellen, beides gibt es heute nicht.

OFFEN       Quality nennt zwei Felder, weil jemand sie
            ausgewaehlt hat. Unbekannte systematisch leere
            Felder bleiben unentdeckbar. Ausserdem unerklaert:
            108 unvollstaendig gegen 89 ohne Beschreibung —
            an welchem Feld haengen die uebrigen 19?

OFFEN       C5 Kanal x Nachricht x Zielgruppe: die
            Kreuzauswertung existiert nicht, der Agent baut
            sie sich aus der Aktivitaetenliste. Echte Luecke,
            kein Namensproblem.

OFFEN       "Open strategic coverage" sitzt auf der Karte
            "Business division". D1 greift richtig, erwartet
            aber Organisationsstruktur statt Themen:
            "einen zweiten Versuch mache ich vor dem Termin
            nicht". Link gehoert auf einen besseren Traeger.

LEHRE       Bloecke zu verschieben verschiebt auch die
            Sprunglinks darauf. Der Umzug von "Attention
            required" nach Planning nahm A, B und C ihren
            einzigen Weg zu Vollstaendigkeit und Vorlauf.
            Nach jedem Umbau die zuvor gruenen Aufgaben
            erneut pruefen, nicht nur die roten.

WICHTIG     Der Fremder-Blick-Test misst Auffindbarkeit, nie
            Existenz. Im Lauf vom 2026-07-28 wurden vier
            "Funktionsluecken" gemeldet, von denen drei
            existierten — hinter dem ersten Klick oder
            unterhalb der Falz. Immer selbst nachklicken.
```
