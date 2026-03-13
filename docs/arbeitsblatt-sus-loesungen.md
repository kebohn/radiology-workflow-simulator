---
title: "Lösungen: Radiologie Workflow Simulator (HL7 + DICOM)"
numbersections: true
---

Hinweis: Das sind Musterlösungen. Je nach Daten (PID, Kreatinin, DICOM-Dateien) können Werte variieren.

# Aufgabe 1: System-Check (DICOM C-ECHO)

- **Was ist C-ECHO?** Ein DICOM "Ping" (Verification). Damit prüft man, ob eine DICOM-Verbindung technisch funktioniert.
- **Welche Komponente wird getestet?** Die DICOM-Konnektivität vom Simulator zur Gegenstelle (PACS/Orthanc DICOM Listener) inkl. AE Title/Host/Port.

# Aufgabe 2: Verwaltung (HL7) in 3 Schritten

## KIS: Patient aufnehmen (HL7 ADT)

- **Welche Eingaben sind Stammdaten?** Patientenname und Patienten-ID (PID). Diese Identitätsdaten sind die Basis für spätere Zuordnung.
- **Warum müssen sie später in DICOM-Tags wieder auftauchen?** Damit Bilddaten (DICOM) und Verwaltungsdaten (HL7) zum selben Patienten matchen, z.B. in den DICOM-Tags `PatientName` und `PatientID`.

## LIS: Kreatinin prüfen (HL7 ORU)

- **In welchem Segment steht die PID?** Im Segment `PID`.
  - In der gezeigten ORU steht sie typischerweise in `PID` als Patienten-ID Feld.
- **Wo steht der Kreatininwert?** Im Segment `OBX`.
  - Wert ist im `OBX` im Value-Feld (in der Demo: `OBX|...||<WERT>|mg/dL|...`).
- **Was bedeutet ein hoher Wert fachlich (kurz)?** Hinweis auf eingeschränkte Nierenfunktion; Kontrastmittelgabe kann riskant sein.

## RIS: Auftrag freigeben (HL7 ORM) + Worklist erstellen

- **Welche Auftragsnummer (Accession) wird erzeugt?** Das ist die eingegebene/erzeugte Accession, z.B. `ACC001` (oder ähnlich).
- **Wo finde ich PID und OBR?**
  - Patient: Segment `PID` (Patienten-ID und Name)
  - Untersuchung/Auftrag: meist in `ORC` (Order Control) und `OBR` (Order Detail), z.B. Accession im `ORC`/`OBR`.

# Aufgabe 3: Modalität (CT) holt Worklist (DICOM C-FIND / MWL)

- **Welche Patientendaten kommen aus der Worklist?** Typisch: PatientName, PatientID, AccessionNumber, Untersuchungsbeschreibung, geplante Modalität.
- **Welche ID verknüpft HL7 Auftrag/Accession mit der DICOM Worklist?** In der Regel die **AccessionNumber** (DICOM Tag (0008,0050)) bzw. die Auftragsnummer.

# Aufgabe 4: CT-Scan (DICOM C-STORE) – echte DICOM-Dateien senden

- **Wie viele Dateien wurden gesendet?** Anzahl der erfolgreich übertragenen DICOM-Instanzen (hängt vom Upload ab).
- **Warum können Dateien "skipped" oder "failed" sein?** Typische Gründe:
  - Datei ist kein DICOM oder hat kaputte Meta-Header
  - nicht unterstützte Transfer Syntax (komprimiert)
  - fehlende Pflicht-Tags oder unlesbare Pixel-Daten

# Aufgabe 5: PACS Check – DICOM Metadaten + Viewer (gefiltert)

- **(0010,0010) PatientName**: entspricht dem im KIS erfassten Namen.
- **(0010,0020) PatientID**: entspricht der PID (oft mit SuS-Präfix).
- **(0008,0050) AccessionNumber**: entspricht dem Auftrag (HL7 ORM).
- **(0008,0060) Modality**: z.B. `CT`.
- **(0020,000D) StudyInstanceUID**: eindeutige Studien-ID (deterministisch aus AccessionNumber abgeleitet).
- **(0020,000E) SeriesInstanceUID**: eindeutige Serien-ID; pro Scan/Serie verschieden.
- **(0008,0018) SOPInstanceUID**: eindeutige Instanz-ID; jedes einzelne Bild hat eine eigene.
- **(0008,0016) SOPClassUID**: gibt den DICOM-Objekttyp an, z.B. `1.2.840.10008.5.1.4.1.1.2` = CT Image Storage.
- **(0008,1030) StudyDescription**: Untersuchungsbeschreibung, stammt aus dem RIS-Auftrag (HL7 ORM).
- **(0008,0090) ReferringPhysicianName**: überweisender Arzt, z.B. `Dr. House` (aus dem Worklist-Eintrag).
- **(0028,0010) Rows / (0028,0011) Columns**: Bildmatrix, z.B. 512 × 512 Pixel.
- **(0028,0100) BitsAllocated**: Bit-Tiefe pro Pixel, z.B. 16 Bit bei CT.
- **(0002,0010) TransferSyntaxUID**: Kodierung der DICOM-Daten, z.B. Implicit VR Little Endian (`1.2.840.10008.1.2`).

## Abgeleitete Serie: "Segmentation (simulated)"

- **Woran erkenne ich eine neue Serie?**
  - neue `SeriesInstanceUID`
  - `SeriesDescription` ist "Segmentation (simulated)"
  - oft auch `ImageType` mit `DERIVED`/`SECONDARY` (je nach Anzeige)

# Aufgabe 6: Workstation – Studien suchen (DICOM C-FIND Study Root)

- **Welche Spalten siehst du?** Typisch: PatientName, PatientID, StudyDate, ModalitiesInStudy.
- **Findest du deinen Patienten wieder?** Ja, wenn `PatientID`/Name konsistent durch HL7 und DICOM durchgereicht wurde.

# Aufgabe 7: Retrieve (DICOM C-MOVE) + Empfang (DICOM C-STORE Rückkanal)

- **Warum ist C-MOVE ein "Pull", führt aber zu einem "Push"?**
  - Die Workstation fordert per C-MOVE an (Pull).
  - Das PACS sendet die Bildinstanzen danach aktiv per C-STORE an die Ziel-AE (Push zur Workstation).

# Aufgabe 8: Befundung auf der Workstation (HL7 ORU^R01)

- **Welche Patientendaten tauchen in der ORU wieder auf?** Im Segment `PID` stehen `PatientID` und `PatientName`.
- **Wo finde ich die StudyInstanceUID?** In der Demo-ORU steht sie als eigener Eintrag im `OBX`-Segment mit Kennung `STUDYUID`.
  - Beispiel: `OBX|2|ST|STUDYUID||<StudyInstanceUID>`

# Aufgabe 9: Status der Untersuchung (begonnen / abgeschlossen / befundet)

- **Welche Aktion setzt welchen Status?**
  - **Auftrag freigeben (HL7 ORM)** setzt: **"Auftrag freigegeben"**.
  - **Scan / Bilder senden (DICOM C-STORE)** setzt zuerst **"Untersuchung begonnen"** und nach erfolgreichem Senden **"Untersuchung abgeschlossen"**.
  - **Befund senden (HL7 ORU^R01)** setzt: **"Befundet"**.
- **Warum können "begonnen" und "abgeschlossen" im Simulator zeitlich sehr nah beieinander liegen?**
  - Weil der Scan als einzelne Aktion simuliert wird (ein Klick), und das Senden der Instanzen direkt danach erfolgt.
- **Welche IDs helfen bei der eindeutigen Zuordnung?**
  - **PID** (PatientID) für den Patienten.
  - **Accession** (AccessionNumber) für den Auftrag/Worklist.
  - **StudyInstanceUID** für die Studie (Bilder/Befund).

# Aufgabe 10: Fehlerfall-Training

## Fehlerfall A: Worklist ist leer

- **Welche zwei Voraussetzungen müssen erfüllt sein, damit ein Worklist-Eintrag sinnvoll erscheint?**
  - Patient ist im KIS angelegt (HL7 ADT vorhanden, PID bekannt).
  - Auftrag ist im RIS freigegeben (HL7 ORM) und hat eine Accession.
- **Welche Nummer ist für die Zuordnung Auftrag <-> Worklist besonders wichtig (Stichwort: Accession)?**
  - Die **AccessionNumber** (DICOM (0008,0050)) bzw. die Auftragsnummer aus HL7.

## Fehlerfall B: C-MOVE ohne Empfang (Cache bleibt leer)

- **Zwei plausible Ursachen:**
  - Transfer ist noch nicht fertig (C-MOVE ist asynchron) oder Seite wurde nicht aktualisiert.
  - Technisch passt das Ziel nicht: Empfänger-AE Title/Host/Port stimmen nicht, oder das PACS kennt die Ziel-AE nicht, daher scheitert der C-STORE Rückkanal.
  - (Alternativ ebenfalls plausibel) Falsche Studie ausgewählt (StudyInstanceUID passt nicht).
- **Welche einfache Prüfung zuerst (z.B. C-ECHO)?**
  - C-ECHO (PACS erreichbar?) und danach die Konfiguration der Ziel-AE prüfen (AE Title/Port) bzw. ob der Store-SCP läuft.

# Aufgabe 11: Reflexion

- Patient aufnehmen: **HL7 ADT**
- Laborbefund: **HL7 ORU**
- Auftrag: **HL7 ORM**
- Worklist abrufen: **DICOM C-FIND (MWL)**
- Bilddaten senden: **DICOM C-STORE**
- Studien suchen: **DICOM C-FIND (Study Root)**
- Retrieve: **DICOM C-MOVE** (mit C-STORE Rückkanal)
