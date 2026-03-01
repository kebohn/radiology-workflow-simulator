# Arbeitsblatt (SuS): Radiologie Workflow Simulator (HL7 + DICOM)

Ziel: Du simulierst den Datenfluss **KIS → LIS → RIS → MWL → CT → PACS → Workstation** und erkennst, welche Informationen über **HL7** bzw. **DICOM** transportiert werden.

## Vorbereitung

- Stack starten (falls nicht schon gestartet): `./start.sh` (Mac/Linux) oder `start.bat` (Windows)
- App öffnen: http://localhost:5000
- Zentraler Server: zuerst `/welcome`, Session-Key eingeben (vom Trainer) oder Join-Link `/join/<CODE>` nutzen
- Optional: Workflow-Panel rechts öffnen (zeigt aktuellen und nächsten Schritt)

Hinweis zu Orthanc (PACS):
- Lokal: Orthanc UI unter http://localhost:8042
- Zentraler Server (Standard): Orthanc ist nicht öffentlich. Der Trainer zeigt es ggf. per Screenshare oder über SSH Port-Forward.
- Zentraler Server (optional, wenn vom Trainer freigeschaltet): Orthanc UI unter der vom Trainer genannten URL (Browser fragt nach einem Login, den der Trainer vorgibt)

Hinweis zur SuS-PACS-Ansicht (gefiltert):
- Öffne im Simulator die Seite **/pacs** (Button: "PACS (SuS) öffnen (gefiltert)").
- Dort siehst du nur Studien, deren `PatientID` mit deinem SuS-Code beginnt, inklusive Metadaten und einfachem Viewer.

---

## Aufgabe 0: System-Check (DICOM C-ECHO)

1) Klicke auf **"Verbindung testen (C-ECHO)"**.
2) Beobachte die Rückmeldung.

Notiere:
- Was ist C-ECHO in einem Satz?
- Welche Komponente wird hier getestet?

---

## Aufgabe 1: Verwaltung (HL7) in 3 Schritten: KIS, LIS, RIS

Merksatz: **ADT = Patient**, **ORU = Labor**, **ORM = Auftrag**.

### 1a) KIS: Patient aufnehmen (HL7 ADT)

1) Trage einen Patienten ein:
- Patientenname: z.B. `BOND^JAMES`
- Patienten-ID (PID): z.B. `007`

Notiere:
- Welche Eingaben sind Stammdaten?
- Warum müssen sie später in DICOM-Tags wieder auftauchen?

### 1b) LIS: Kreatinin prüfen (HL7 ORU)

1) Klicke auf **"RIS → LIS: Kreatinin anfordern"**.
2) Lies Kreatinin-Wert und Status.
3) Scrolle zur angezeigten HL7-Nachricht.

Notiere:
- In welchem Segment steht die PID?
- Wo steht der Kreatininwert?
- Was bedeutet ein hoher Wert fachlich (kurz)?

### 1c) RIS: Auftrag freigeben (HL7 ORM) + Worklist erstellen

1) Trage eine Untersuchungsbeschreibung ein (z.B. `CT Abdomen mit KM`).
2) Klicke auf **"RIS: Auftrag freigeben (HL7 ORM) + Worklist erstellen"**.

Beobachte:
- Welche Auftragsnummer (Accession) wird erzeugt?

Optional (HL7 Analyse):
- Finde in der angezeigten ORM-Nachricht die Segmente `PID` und `OBR`.

Beispiel (verkürzt):

```
MSH|^~\&|KIS|HOSPITAL|RIS|RADIO|...||ORM^O01|...|P|2.3
PID|||007||BOND^JAMES
ORC|NW|ACC001
OBR|1|ACC001||CT^CT Abdomen
```

---

## Aufgabe 2: Modalität (CT) holt Worklist (DICOM C-FIND / MWL)

1) Wechsle zur CT-Seite.
2) Klicke auf **Worklist abrufen (DICOM C-FIND)**.

Beobachte:
- Welche Patientendaten kommen aus der Worklist?
- Welche ID verknüpft Auftrag/Accession aus HL7 mit der DICOM Worklist?

---

## Aufgabe 3: CT-Scan (DICOM C-STORE) – echte DICOM-Dateien senden

1) Wähle einen Worklist-Eintrag aus (falls die UI das anbietet).
2) Lade echte DICOM-Dateien hoch (mehrere Dateien oder ZIP).
3) Starte den Upload/Transfer (C-STORE).

Beobachte:
- Wie viele Dateien wurden gesendet?
- Gab es "skipped" oder "failed" Dateien? Was könnte der Grund sein?

---

## Aufgabe 4: PACS Check – DICOM Metadaten + Viewer (gefiltert)

1) Öffne im Simulator die Seite **/pacs**.
2) Klicke bei deiner Studie auf **Metadata**.
3) Klicke auf **Viewer**, um die Bilder anzusehen.

Prüfe diese Tags:
- (0010,0010) `PatientName`
- (0010,0020) `PatientID`
- (0008,0050) `AccessionNumber`
- (0008,0060) `Modality`
- (0020,000D) `StudyInstanceUID`

### 4b) (Optional) Abgeleitete Serie: "Segmentation (simulated)"

1) Öffne in **/pacs** eine Serie deiner Studie.
2) Klicke auf **"Segmentation (simulated) erzeugen"**.
3) Prüfe danach in der Serienansicht, ob eine neue (abgeleitete) Serie entstanden ist.

Notiere:
- Woran erkennst du eine neue Serie (z.B. neue `SeriesInstanceUID`, andere `SeriesDescription`)?

---

## Aufgabe 5: Workstation – Studien suchen (DICOM C-FIND Study Root)

1) Öffne die Workstation/Viewer-Seite.
2) Schau dir die Trefferliste an.

Notiere:
- Welche Spalten siehst du (Patient, Datum, Modalität)?
- Findest du deinen Patienten wieder?

---

## Aufgabe 6: Retrieve (DICOM C-MOVE) + Empfang (DICOM C-STORE Rückkanal)

1) Wähle eine Studie aus und starte **Retrieve (C-MOVE)**.
2) Warte kurz und beobachte die Empfangsliste.

Notiere:
- Warum ist C-MOVE ein "Pull", führt aber zu einem "Push" über den C-STORE Rückkanal?

---

## Aufgabe 7: Befundung auf der Workstation (HL7 ORU^R01)

Voraussetzung: Du hast in Aufgabe 6 Bilder empfangen (C-STORE Cache ist nicht leer).

1) Öffne die Workstation-Seite.
2) Wähle im Bereich "Empfangene Studien" eine Studie aus.
3) Schreibe einen kurzen Befundtext.
4) Klicke auf **"Befund senden (HL7 ORU^R01)"**.
5) Wechsle zum Dashboard und prüfe im Block **"RIS: Befunde (aus Workstation, HL7 ORU)"**:
	- Ist ein Eintrag hinzugekommen?
	- Kannst du die HL7 Nachricht über **"HL7 anzeigen"** aufklappen?

Notiere:
- Welche Patientendaten tauchen in der ORU wieder auf?
- Wo (grob) findest du die `StudyInstanceUID` im Text?

---

## Aufgabe 8: Status der Untersuchung (begonnen / abgeschlossen / befundet)

Ziel: Du beobachtest im Dashboard, wie sich der **Status der Untersuchung** entlang des Workflows ändert.

1) Gehe ins Dashboard (Hauptmenü).
2) Suche in der RIS-Tabelle die Spalte **"Status Untersuchung"**.
3) Beobachte den Status nach diesen Aktionen:
	- Nach **Auftrag freigeben (HL7 ORM)**
	- Nach **Scan / Bilder senden (DICOM C-STORE)**
	- Nach **Befund senden (HL7 ORU^R01)**

Notiere:
- Welche Aktion setzt welchen Status?
- Warum können "begonnen" und "abgeschlossen" im Simulator zeitlich sehr nah beieinander liegen?
- Welche IDs helfen dir bei der eindeutigen Zuordnung (z.B. PID, Accession, StudyInstanceUID)?

---

## Aufgabe 9: Fehlerfall-Training (Teamaufgabe)

Ziel: Ihr übt typische Situationen aus dem Alltag. Nutzt im Dashboard die Kachel **"Fehlerfälle (Training)"** oder den **Workflow-Drawer** als Checkliste.

### Fehlerfall A: Worklist ist leer

1) Geht zur CT-Seite und ruft die Worklist ab.
2) Wenn die Liste leer ist (oder ihr es provozieren wollt): Prüft, ob ihr wirklich einen Auftrag freigegeben habt (HL7 ORM).

Notiere:
- Welche zwei Voraussetzungen müssen erfüllt sein, damit ein Worklist-Eintrag sinnvoll erscheint?
- Welche Nummer ist für die Zuordnung Auftrag <-> Worklist besonders wichtig (Stichwort: Accession)?

### Fehlerfall B: C-MOVE ohne Empfang (Cache bleibt leer)

1) Startet in der Workstation ein Retrieve (C-MOVE).
2) Wenn im Cache nichts auftaucht: Wartet kurz und aktualisiert die Workstation-Seite.

Notiere (konzeptionell):
- Nenne zwei plausible Ursachen, warum nach einem C-MOVE keine Bilder im Empfangs-Cache erscheinen.
- Welche einfache Prüfung würdest du als erstes machen (z.B. C-ECHO)?

---

## Reflexion (kurz)

1) Ordne die Protokolle zu:
- Patient aufnehmen: ___
- Laborbefund: ___
- Auftrag: ___
- Worklist abrufen: ___
- Bilddaten senden: ___
- Studien suchen: ___
- Retrieve: ___

2) Was war für dich neu oder überraschend?

