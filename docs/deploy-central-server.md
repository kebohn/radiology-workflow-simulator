# Deployment: Zentraler Server (Repo klonen + Docker Compose Build)

Ziel: Ein zentraler Server hostet die App. SuS greifen per Browser zu.

Wichtige Hinweise:
- Orthanc ist kein Multi-Tenant PACS. Harte Isolation pro SuS geht nur mit getrennten Backends.
- Dieses Repo implementiert daher eine soft isolation: SuS setzen einen SuS-Code; PatientID/Accession werden intern geprefixt und die UI filtert standardmässig darauf.
- Orthanc wird auf dem Server nur an `127.0.0.1` gebunden (nicht öffentlich).

## Voraussetzungen

- Linux Server (z.B. Ubuntu)
- Docker Engine + Docker Compose Plugin
- Optional: Domain (für HTTPS)

## Schritt 1: Server vorbereiten (Ubuntu)

Docker installieren (Ubuntu, Copy/Paste):

```
sudo apt-get update
sudo apt-get install -y ca-certificates curl

# Docker Repo
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

Optional: Docker ohne `sudo` (neu einloggen danach):

```
sudo usermod -aG docker $USER
```

Installations-Check:

```
docker --version
docker compose version
```

Firewall:
- erlauben: 80/tcp und 443/tcp (Caddy; HTTP wird auf HTTPS umgeleitet)
- nicht freigeben: 8042/tcp, 4242/tcp (Orthanc)

AWS EC2 Hinweis:
- In der EC2 Security Group muessen Inbound Rules fuer 80/tcp **und** 443/tcp erlaubt sein (HTTP wird auf HTTPS umgeleitet).
- Die Instanz braucht eine Public IPv4 (oder Elastic IP) und muss in einem Public Subnet mit Route zum Internet Gateway liegen, sonst ist sie von aussen nicht erreichbar.

Troubleshooting (Browser: `ERR_SSL_PROTOCOL_ERROR`):
- Prüfe zuerst, dass 443/tcp wirklich offen ist (Security Group + ggf. NACL).
- Auf dem Server prüfen, ob Caddy auf 443 lauscht und ohne Fehler läuft:

```
docker compose -f docker-compose.server.yml ps
docker logs --tail=200 caddy
sudo ss -ltnp | egrep ':(80|443)\b'
```

## Schritt 2: Repo klonen

```
git clone <REPO_URL> radiology-workflow-simulator
cd radiology-workflow-simulator
```

## Schritt 3: Secrets/Env setzen

```
cp .env.server.example .env
```

Dann `.env` editieren (mindestens `FLASK_SECRET_KEY` und `ADMIN_PASSHASH` setzen).

Wichtig für HTTPS (Reverse Proxy):
- Setze `SIM_DOMAIN` auf einen Hostnamen, z.B. `sim.example.org`.

### DNS (Cloudflare) fuer `orthanc.bohn-teaching.org`

Wenn du Cloudflare als DNS-Provider nutzt und die App auf AWS (z.B. EC2) laeuft:

1) DNS Record anlegen (Cloudflare Dashboard -> **DNS**)

- **Type**: `A`
- **Name**: `orthanc`
- **IPv4 address**: `<DEINE_PUBLIC_IP>` (EC2 Public IPv4 / Elastic IP)
- **Proxy status**: fuer die erste Inbetriebnahme am einfachsten **DNS only** (graue Wolke)

Optional (wenn du auch IPv6 hast):
- **Type**: `AAAA` mit deiner Public IPv6

2) Sobald `https://orthanc.bohn-teaching.org` funktioniert, kannst du (optional) wieder auf **Proxied** (orange Wolke) schalten.

Hinweise:
- In AWS muessen in der Security Group Inbound Rules fuer **80/tcp** und **443/tcp** offen sein.
- Wenn du Cloudflare Proxy nutzt: Stelle unter **SSL/TLS** den Modus auf **Full (strict)** (nachdem Caddy erfolgreich ein Zertifikat bezogen hat).
- Vermeide Cloudflare-Optionen wie **Always Use HTTPS** / HSTS waehrend der allerersten ACME/Let's-Encrypt Einrichtung, falls du unerwartete Redirect/Challenge-Probleme siehst.

Hinweis Schulnetz / FortiGate:
- Dienste wie `sslip.io` werden oft als **Dynamic DNS** kategorisiert und in Schulnetzen (FortiGate) standardmäßig blockiert.
- Wenn SuS aus dem Schulnetz zugreifen sollen, verwende besser **eine „normale“ Domain** (eigene Domain oder Subdomain der Schule), die per DNS A/AAAA auf die Server-IP zeigt.

Ohne eigene Domain (Fallback):
- Du kannst die App auch über die **öffentliche IP** aufrufen. Das ist dann typischerweise **nur HTTP** (kein öffentliches Let's-Encrypt-TLS): `http://<SERVER-IP>/`
  - Stelle sicher, dass im Firewall/Security-Group **80/tcp erlaubt** ist.
  - Viele Browser/Schulnetze erzwingen HTTPS ("HTTPS-Only"). Wenn dein Browser automatisch auf `https://<SERVER-IP>/` springt, funktioniert das ohne echte Domain meistens nicht.
  - Empfehlung: Für Unterrichtsbetrieb besser eine echte Domain nutzen.

### Wenn HTTPS erzwungen wird (HTTPS-Only)

Wenn euer Schulnetz oder eure Browser-Richtlinie **HTTPS erzwingt**, ist ein reiner IP-Zugriff praktisch nicht mehr nutzbar:
- Für `https://<PUBLIC-IP>/` bekommst du üblicherweise **kein** öffentlich vertrauenswürdiges TLS-Zertifikat (Let's Encrypt stellt in der Regel keine IP-Zertifikate aus).

Dann bleiben realistisch diese Optionen:
- **Echte Domain / Schul-Subdomain nutzen** (empfohlen): DNS A/AAAA → Server-IP, `SIM_DOMAIN=sim.example.org`.
- **IT-Ausnahme**: Zugriff auf `http://<PUBLIC-IP>/` erlauben bzw. HTTPS-Only für diese URL deaktivieren.
- **Geräte verwalten** (nur wenn ihr volle Kontrolle habt): eigene CA / Zertifikat verteilen (deutlich mehr Aufwand).

Tipp für `FLASK_SECRET_KEY`:

```
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Schritt 4: Starten

```
docker compose -f docker-compose.server.yml up -d --build
```

Danach ist die App erreichbar:
- `https://<SIM_DOMAIN>/`

Hinweis: Die Startseite leitet auf `/welcome` um, bis ein SuS-Session-Key gesetzt wurde.

## Schritt 5: HTTPS (Default)

Wenn `SIM_DOMAIN` auf einen gültigen Hostnamen zeigt (DNS A/AAAA auf Server-IP), holt Caddy automatisch TLS-Zertifikate via Let's Encrypt.

Änderungen anwenden:

```
docker compose -f docker-compose.server.yml up -d
```

## Betrieb für SuS

- Einmalig als Trainer: `https://<SIM_DOMAIN>/admin` öffnen, mit Benutzer `admin` + Passwort einloggen und Codes prüfen/generieren.
- SuS bekommen jeweils einen Code oder direkt den Join-Link `/join/<CODE>`.
- Ohne gesetzten Code landen SuS immer zuerst auf `/welcome`.

PACS-Ansicht für SuS (gefiltert):
- Im Simulator gibt es eine Seite `/pacs` (Button: "PACS (SuS) öffnen (gefiltert)").
- Diese Ansicht zeigt Metadaten + einfachen Viewer, gefiltert nach dem SuS-Code (PatientID Prefix).
- Dadurch musst du Orthanc nicht öffentlich exponieren, damit SuS Bilder/Metadaten sehen.

## Trainer: Orthanc UI trotzdem nutzen

Orthanc läuft nur auf `127.0.0.1:8042`. Von deinem Laptop:

```
ssh -L 8042:127.0.0.1:8042 user@SERVER
```

Dann lokal im Browser: `http://localhost:8042`.

(Hinweis: In dieser Version sind Orthanc-Zugangsdaten nicht mehr in der Orthanc-Konfiguration hinterlegt; wenn du Orthanc über Caddy veröffentlichst, erfolgt der Zugriff über Basic Auth vor Orthanc.)

## Update (neue Version deployen)

## (Optional) Orthanc über Caddy reverse-proxy'en (Subdomain + Basic Auth)

Wenn du Orthanc im Browser erreichbar machen willst, **ohne** Port `8042` öffentlich zu öffnen, kannst du Orthanc über Caddy unter einer **eigenen Subdomain** bereitstellen.

Warum Subdomain (statt `/orthanc`)? Orthancs Web-UI nutzt an vielen Stellen absolute Pfade (z.B. `/app/...`). Unter einem URL-Unterpfad geht die Navigation deshalb oft kaputt.

### Voraussetzungen

- Du hast eine Domain und kannst DNS setzen (oder nutzt einen Wildcard-DNS-Dienst wie `sslip.io`, siehe Tipp unten).

### Schritte

1) DNS: Lege z.B. `orthanc.example.org` an (A/AAAA → deine EC2 Public IP).

2) Setze diese Umgebungsvariablen auf dem Server (z.B. in deiner Shell, `.env` oder im Systemd Unit Environment):

- `ORTHANC_DOMAIN=orthanc.example.org`

Wichtig:
- Wenn `ORTHANC_DOMAIN` **nicht** gesetzt ist, faellt das Setup auf den Default `orthanc.localhost` zurueck.
  Das ist nur fuer lokale Tests gedacht; extern im Browser fuehrt das oft zu TLS/SSL-Fehlern.
  In `docker logs caddy` solltest du spaeter unter "domains" deine echten FQDNs sehen (z.B. `pacs.example.org`).

3) Setze einen Basic-Auth-Zugang (damit Orthanc nicht offen im Internet steht):

- `ORTHANC_PROXY_USER=admin`
- `ORTHANC_PROXY_PASSHASH=<bcrypt-hash>`

Hash erzeugen:

`docker compose -f docker-compose.server.yml run --rm caddy caddy hash-password --plaintext 'DEIN_PASSWORT'`

4) Stack neu starten:

`docker compose -f docker-compose.server.yml up -d`

Wenn du den Wert in `.env` geaendert hast und Caddy den Host immer noch nicht kennt:
- erzwinge ein Recreate von Caddy: `docker compose -f docker-compose.server.yml up -d --force-recreate caddy`

Danach ist Orthanc unter `https://orthanc.example.org` erreichbar (Browser fragt nach Basic Auth).

Tipp ohne eigenes DNS: `orthanc.<EC2_PUBLIC_IP>.sslip.io` zeigt automatisch auf deine IP.

### SuS-Zugang (wenn Orthanc für alle SuS sichtbar sein soll)

Wenn du Orthanc für alle SuS erreichbar machst, gib ihnen den gemeinsamen Basic-Auth-Login (User `admin` + Passwort, das du selbst setzt). Diese Zugangsdaten stehen **nicht** im Repo, sondern nur in deiner Server-Umgebung (`ORTHANC_PROXY_*`).

Tipp: Du kannst denselben bcrypt Hash auch für `/admin` verwenden:
- `ADMIN_USER=admin`
- `ADMIN_PASSHASH=<derselbe bcrypt-hash wie ORTHANC_PROXY_PASSHASH>`
Im Repo-Ordner:

```
git pull
docker compose -f docker-compose.server.yml up -d --build
```

