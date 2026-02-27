# Arbeitsblatt (SuS): Radiologie Workflow Simulator (HL7 + DICOM)

Ziel: Du simulierst den Datenfluss **KIS → LIS → RIS → MWL → CT → PACS → Workstation** und erkennst, welche Informationen über **HL7** bzw. **DICOM** transportiert werden.

## Vorbereitung

- Starte den Stack (falls nicht schon gestartet): `./start.sh` (Mac/Linux) oder `start.bat` (Windows)
- Öffne die App: http://localhost:5000
- Falls ihr auf einem **zentralen Server** arbeitet: Ihr landet zuerst auf der **Willkommen-Seite** und müsst euren **Session-Key** eingeben (vom Trainer) oder einen Join-Link `/join/<CODE>` nutzen. Danach seht ihr in der Workstation standardmässig nur eure Studien.
- Optional: Öffne das **Workflow**-Panel (rechts), um den aktuellen/nächsten Schritt zu sehen.

---

## Aufgabe 0: System-Check (DICOM C-ECHO)

1. Klicke auf **"Verbindung testen (C-ECHO)"**.
2. Beobachte die Rückmeldung.

Notiere:
- Was ist C-ECHO in einem Satz?
- Welche Komponente wird hier "angepingt"?

---

## Aufgabe 1: Verwaltung (HL7) in 3 Schritten: KIS, LIS, RIS

### 1a) KIS: Patient aufnehmen (HL7 ADT)

1. Trage einen Patienten ein:
   - Patientenname: z.B. `BOND^JAMES`
   - Patienten-ID (PID): z.B. `007`

Beobachte:
- Welche Felder sind Stammdaten?
- Warum müssen diese später in DICOM-Tags wieder auftauchen?

### 1b) LIS: Kreatinin prüfen (HL7 ORU)

1. Klicke auf **"LIS Abfragen (Kreatinin)"**.
2. Lies den Kreatinin-Wert und den Status.
3. Scrolle nach unten zur angezeigten HL7-Nachricht.

Notiere:
- Welches Segment enthält die PID?
- In welchem Segment/Zeile steht der Kreatininwert?
- Was würde ein hoher Kreatininwert fachlich bedeuten (kurz)?

### 1c) RIS: Auftrag freigeben (HL7 ORM) + Worklist erstellen

1. Trage eine Untersuchungsbeschreibung ein (z.B. `CT Abdomen mit KM`).
2. Klicke auf **"RIS: Auftrag freigeben (HL7 ORM) + Worklist erstellen"**.

Beobachte:
- Welche Auftragsnummer (Accession) wird erzeugt?
- Warum ist "Auftrag freigeben" ein sinnvoller Schritt *nach* dem Laborwert?

---

## Aufgabe 2: Modalität (CT) holt Worklist (DICOM C-FIND / MWL)

1. Wechsle zur Modalität-Seite (CT).
2. Klicke auf **Worklist abrufen (DICOM C-FIND)**.

Beobachte:
- Welche Patientendaten kommen aus der Worklist?
- Welche Information verbindet HL7-Order (ORM) und DICOM-Worklist?

---

## Aufgabe 3: CT-Scan (DICOM C-STORE) – echte DICOM-Dateien senden

1. Wähle einen Worklist-Eintrag aus (falls die UI das anbietet).
2. Lade echte DICOM-Dateien hoch:
   - entweder mehrere Dateien
   - oder eine ZIP-Datei mit vielen DICOMs
3. Starte den Upload/Transfer (C-STORE).

Beobachte:
- Wie viele Dateien wurden gesendet?
- Gab es "skipped" oder "failed" Dateien? Warum könnte das passieren?

---

## Aufgabe 4: Workstation: Studien suchen (DICOM C-FIND Study Root)

1. Öffne die Workstation/Viewer-Seite.
2. Schau dir die Liste der Studien an.

Notiere:
- Welche Spalten siehst du (Patient, Datum, Modalität)?
- Findest du deinen Patienten wieder?

---

## Aufgabe 5: Retrieve (DICOM C-MOVE) + Empfang (DICOM C-STORE Rückkanal)

1. Wähle eine Studie aus und starte **Retrieve (C-MOVE)**.
2. Warte kurz und beobachte die Empfangsliste (Bilder, die an die Workstation gesendet wurden).

Notiere:
- Warum ist C-MOVE ein "Pull" (Anforderung), führt aber zu einem "Push" (C-STORE Rückkanal)?

---

## Reflexion (kurz)

1. Ordne die Protokolle zu:
   - Patient aufnehmen: ___
   - Laborbefund: ___
   - Auftrag: ___
   - Worklist abrufen: ___
   - Bilddaten senden: ___
   - Studien suchen: ___
   - Retrieve: ___

2. Was war für dich neu oder überraschend?

