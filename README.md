# Radiologie Workflow Simulator (DICOM & HL7)

Dieses Projekt bietet eine komplette, einfach zu bedienende Simulationsumgebung, um Studierenden den digitalen Arbeitsablauf in der Radiologie (Workflow) näherzubringen.

## Features

- **KIS / LIS / RIS Simulation**: Patientenaufnahme (ADT), Laborprüfung (ORU), Auftrag (ORM) und Worklist-Generierung.
- **HL7 Analyse**: Visualisierung von Beispiel-Events (HL7 ADT / ORU / ORM) im Workflow.
- **Modalitäts-Simulation**:
  - **DICOM C-ECHO** (Verbindungstest ("Ping"))
  - **DICOM C-FIND** (Worklist-Abfrage)
    - **DICOM C-STORE** (Bild-Transfer zum PACS) inkl. Upload echter DICOM-Dateien (ZIP oder mehrere Dateien)
- **Workstation Simulation (Neu!)**:
  - **DICOM C-FIND (Study Root)**: Suche nach Studien im PACS.
  - **DICOM C-MOVE**: Anforderung von Bildern ("Retrieve").
  - **DICOM C-STORE (SCP)**: Empfang der angeforderten Bilder.
- **PACS (Orthanc)**: Echter, voll funktionsfähiger DICOM Server zur Bildspeicherung.
- **Generic DICOM**: Möglichkeit, echte, extern erzeugte DICOM-Dateien zu importieren.

## Architektur & Datenfluss

Folgendes Diagramm visualisiert die Kommunikationswege zwischen den simulierten Komponenten:

Arbeitsblatt für Lernende: [docs/arbeitsblatt-sus.md](docs/arbeitsblatt-sus.md)

Hinweis: Wenn Sie beim Preview die Meldung "No diagram type detected" sehen, wurde sehr wahrscheinlich die Mermaid-Preview auf die gesamte Markdown-Datei angewendet. Öffnen Sie stattdessen die Markdown-Vorschau (für `README.md`) oder nutzen Sie die reine Mermaid-Datei unter `docs/workflow.mermaid`.

![Workflow-Diagramm](docs/workflow.svg)

Quelle (bearbeitbar): [docs/workflow.mermaid](docs/workflow.mermaid)

### Diagramm erklärt (Schritt für Schritt)

Das Diagramm zeigt, wie **administrative Daten** (Patient wird aufgenommen), **klinische Auftragsdaten** (CT wird beauftragt) und **Bilddaten** (DICOM) in der Radiologie zusammenlaufen.

**Legende (vereinfacht):**
- **HL7** = Textnachrichten zwischen Krankenhaus-IT-Systemen (KIS/LIS/RIS). Sie transportieren *Patientendaten*, *Aufträge* und *Laborbefunde*.
- **DICOM** = Protokolle/Dateiformat für radiologische Worklists und Bildübertragung (Modalität, Worklist, PACS, Workstation).
- **Worklist (MWL)** = eigener DICOM-Dienst (Termin-/Auftragsliste für Modalitäten), fachlich vom RIS getrieben.
- **PACS-Archiv** = DICOM-Archiv für Bilder/Studien (Query/Retrieve).
- **Wichtig:** In der Praxis können MWL und PACS im selben System laufen (hier: Orthanc), wir trennen es im Diagramm nur zur Erklärung.

#### 1) HL7 ADT: KIS → RIS (Patientendaten)
- **Was passiert fachlich?** Ein Patient wird im **KIS** administrativ aufgenommen/registriert.
- **Was passiert technisch?** Das KIS würde typischerweise eine **HL7 ADT**-Nachricht senden (z.B. A01 „Aufnahme“).
- **Warum ist das wichtig?** Das **RIS** hat dadurch korrekte Stammdaten (Name, PID usw.). Diese Daten sollen später automatisch in Auftrag, Worklist und DICOM-Metadaten landen.

#### 2) HL7 ORU: RIS ↔ LIS (Kreatinin prüfen)
- **Was passiert fachlich?** Vor einer CT mit Kontrastmittel muss die **Nierenfunktion** geprüft werden.
- **Was passiert technisch?** Das RIS fragt den Kreatininwert im **LIS** ab bzw. erhält einen Befund als **HL7 ORU** (Observation Result).
- **Wie wird das im Simulator veranschaulicht?** Im Dashboard erfasst man zuerst einen Patienten im **KIS** (ADT). Danach kann man über **„RIS → LIS: Kreatinin anfordern“** die Anfrage/Antwort (inkl. ORU-Befund) als Roh-HL7 sehen.
- **Was sollen SuS verstehen?** Medizinische Entscheidungen (Kontrastmittel ja/nein) hängen oft von Daten aus *anderen* Systemen (Labor) ab.

#### 3) HL7 ORM: RIS → Worklist-Server (MWL) (Auftrag freigeben)
- **Was passiert fachlich?** Das RIS erzeugt den Untersuchungsauftrag (z.B. „CT Abdomen mit KM“).
- **Was passiert technisch?** Üblich ist eine **HL7 ORM** (Order Message). In dieser Demo wird daraus ein **Worklist-Eintrag** erzeugt (als `.wl`), den die Modalität später abruft.
- **Merksatz:** **ADT = Patient**, **ORU = Labor**, **ORM = Auftrag**.

#### 4) DICOM C-FIND: Modalität → Worklist-Server (MWL) (Worklist abrufen)
- **Was passiert fachlich?** Der CT-Scanner „weiss“, welche Patient:innen heute dran sind.
- **Was passiert technisch?** Die **Modalität** sendet **DICOM C-FIND** gegen die *Modality Worklist*.
- **Ergebnis:** Die Modalität erhält Patient/Auftrag-Daten, ohne dass man sie am Gerät neu eintippen muss (Fehlervermeidung).

#### 5) DICOM C-STORE: Modalität → PACS-Archiv (Bilder senden)
- **Was passiert fachlich?** Der Scan wird durchgeführt, Bilddaten entstehen.
- **Was passiert technisch?** Die Modalität „pusht“ Bilder via **DICOM C-STORE** an das **PACS-Archiv** (hier: Orthanc).
- **Wichtig:** Die DICOM-Tags (PatientName/ID, AccessionNumber, StudyUID) sollten konsistent zu den vorherigen Schritten sein.

#### 6) DICOM C-FIND: Workstation ↔ PACS-Archiv (Studien suchen)
- **Was passiert fachlich?** Radiolog:innen suchen eine Studie im Archiv.
- **Was passiert technisch?** Die **Workstation** fragt das PACS per **DICOM C-FIND** (Study Root) nach Studien.
- **Ergebnis:** Eine Trefferliste mit Studieninformationen (z.B. Patient, Accession, StudyInstanceUID).

#### 7) DICOM C-MOVE: Workstation lädt Bilder aus dem PACS-Archiv
- **Was passiert fachlich?** Bilder werden zur Befundung geladen.
- **Was passiert technisch?** Die Workstation sendet **C-MOVE** (Retrieve-Anforderung). Danach sendet das PACS die Bilder in einem separaten Schritt per **C-STORE** an die Workstation zurück.
- **Lernpunkt:** „**Pull**“ (Workstation fordert an) führt trotzdem dazu, dass das PACS aktiv „**pushen**“ muss (C-STORE zurück zur Workstation).

Wenn Sie möchten, kann ich daraus auch eine kurze **1-Seiten-Zusammenfassung** (Arbeitsblatt) für den Unterricht machen.

## Voraussetzungen

- **Docker Desktop**: Muss installiert sein. (Download: [docker.com](https://www.docker.com/products/docker-desktop)).
- Sonst nichts! Keine komplexe Installation nötig.

## Schnellstart

### Windows
1. Doppelklick auf `start.bat`.
2. Warten Sie auf die Nachricht "Services started!".
3. Öffnen Sie Ihren Browser unter [http://localhost:5000](http://localhost:5000).

### Mac / Linux
1. Terminal öffnen.
2. `chmod +x start.sh` ausführen (nur einmalig nötig).
3. `./start.sh` ausführen.
4. Browser öffnen unter [http://localhost:5000](http://localhost:5000).

---

## Deployment (zentraler Server)

Anleitung: [docs/deploy-central-server.md](docs/deploy-central-server.md)

## Arbeitsblatt (Aufgabenbeschreibung)

Die komplette Aufgabenbeschreibung für Lernende ist zentral im Arbeitsblatt:

- [docs/arbeitsblatt-sus.md](docs/arbeitsblatt-sus.md)

## Technische Details für Dozenten

- **Orthanc**: Läuft auf Ports 4242 (DICOM) und 8042 (HTTP).
- **Simulator**: Python Flask App auf Port 5000.
    - Nutzt `pynetdicom` als DICOM SCU (Service Class User).
    - Simuliert Worklist Files (`.wl`) als Antwort auf C-FIND.
    - Simuliert HL7-Logik durch Generierung der Worklist-Einträge.


