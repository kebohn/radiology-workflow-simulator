# Arbeitsblatt (SuS): Radiologie Workflow Simulator (HL7 + DICOM)

Ziel: Du simulierst den Datenfluss **KIS → LIS → RIS → MWL → CT → PACS → Workstation** und erkennst, welche Informationen über **HL7** bzw. **DICOM** transportiert werden.

## Vorbereitung

- Stack starten (falls nicht schon gestartet): `./start.sh` (Mac/Linux) oder `start.bat` (Windows)
- App öffnen: http://localhost:5000
- Zentraler Server: zuerst `/welcome`, Session-Key eingeben (vom Trainer) oder Join-Link `/join/<CODE>` nutzen
- Optional: Workflow-Panel rechts öffnen (zeigt aktuellen und nächsten Schritt)

Hinweis zu Orthanc (PACS):
- Lokal: Orthanc UI unter http://localhost:8042 (Login: `trainer` / `trainer123`)
- Zentraler Server: Orthanc ist nicht öffentlich. Der Trainer zeigt es ggf. per Screenshare oder über SSH Port-Forward.

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
- Warum muessen sie spaeter in DICOM-Tags wieder auftauchen?

### 1b) LIS: Kreatinin pruefen (HL7 ORU)

1) Klicke auf **"LIS Abfragen (Kreatinin)"**.
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

## Aufgabe 2: Modalitaet (CT) holt Worklist (DICOM C-FIND / MWL)

1) Wechsle zur CT-Seite.
2) Klicke auf **Worklist abrufen (DICOM C-FIND)**.

Beobachte:
- Welche Patientendaten kommen aus der Worklist?
- Welche ID verknuepft Auftrag/Accession aus HL7 mit der DICOM Worklist?

---

## Aufgabe 3: CT-Scan (DICOM C-STORE) – echte DICOM-Dateien senden

1) Waehle einen Worklist-Eintrag aus (falls die UI das anbietet).
2) Lade echte DICOM-Dateien hoch (mehrere Dateien oder ZIP).
3) Starte den Upload/Transfer (C-STORE).

Beobachte:
- Wie viele Dateien wurden gesendet?
- Gab es "skipped" oder "failed" Dateien? Was koennte der Grund sein?

---

## Aufgabe 4: PACS Check – DICOM Metadaten in Orthanc pruefen

1) Oeffne Orthanc UI: http://localhost:8042 (Login: `trainer` / `trainer123`).
2) Navigiere: Patient -> Studie -> Serie -> Instanz.
3) Oeffne **DICOM Tags**.

Pruefe diese Tags:
- (0010,0010) `PatientName`
- (0010,0020) `PatientID`
- (0008,0050) `AccessionNumber`
- (0008,0060) `Modality`
- (0020,000D) `StudyInstanceUID`

---

## Aufgabe 5: Workstation – Studien suchen (DICOM C-FIND Study Root)

1) Oeffne die Workstation/Viewer-Seite.
2) Schau dir die Trefferliste an.

Notiere:
- Welche Spalten siehst du (Patient, Datum, Modalitaet)?
- Findest du deinen Patienten wieder?

---

## Aufgabe 6: Retrieve (DICOM C-MOVE) + Empfang (DICOM C-STORE Rueckkanal)

1) Waehle eine Studie aus und starte **Retrieve (C-MOVE)**.
2) Warte kurz und beobachte die Empfangsliste.

Notiere:
- Warum ist C-MOVE ein "Pull", fuehrt aber zu einem "Push" ueber den C-STORE Rueckkanal?

---

## Aufgabe 7: Datenschutz – Studie anonymisieren (Orthanc)

1) In Orthanc: Oeffne eine Studie.
2) Klicke auf **Anonymize** / **Anonymisieren**.
3) Bestaetige mit den Standard-Einstellungen.
4) Vergleiche danach die DICOM Tags erneut.

Notiere:
- Wie heisst der Patient nach der Anonymisierung?
- Sind `PatientName` und `PatientID` weg oder ersetzt?

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

2) Was war fuer dich neu oder ueberraschend?

