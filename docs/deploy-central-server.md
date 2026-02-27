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
- In der EC2 Security Group muessen Inbound Rules fuer 80/tcp (und optional 443/tcp) erlaubt sein.
- Die Instanz braucht eine Public IPv4 (oder Elastic IP) und muss in einem Public Subnet mit Route zum Internet Gateway liegen, sonst ist sie von aussen nicht erreichbar.

## Schritt 2: Repo klonen

```
git clone <REPO_URL> radiology-workflow-simulator
cd radiology-workflow-simulator
```

## Schritt 3: Secrets/Env setzen

```
cp .env.server.example .env
```

Dann `.env` editieren (mindestens `FLASK_SECRET_KEY` und `ADMIN_PASSWORD` setzen).

Wichtig für HTTPS (Reverse Proxy):
- Setze `SIM_DOMAIN` auf einen Hostnamen, z.B. `sim.example.org`.
- Ohne eigene Domain kannst du `sim.<SERVER-IP>.sslip.io` verwenden.

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

- Einmalig als Trainer: `http://SERVER-IP/admin` öffnen, mit `ADMIN_PASSWORD` einloggen und Codes prüfen/generieren.
- SuS bekommen jeweils einen Code oder direkt den Join-Link `/join/<CODE>`.
- Ohne gesetzten Code landen SuS immer zuerst auf `/welcome`.

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

3) Setze einen Basic-Auth-Zugang (damit Orthanc nicht offen im Internet steht):

- `ORTHANC_PROXY_USER=sus`
- `ORTHANC_PROXY_PASSHASH=<bcrypt-hash>`

Hash erzeugen:

`docker compose -f docker-compose.server.yml run --rm caddy caddy hash-password --plaintext 'DEIN_PASSWORT'`

4) Stack neu starten:

`docker compose -f docker-compose.server.yml up -d`

Danach ist Orthanc unter `https://orthanc.example.org` erreichbar (Browser fragt nach Basic Auth).

Tipp ohne eigenes DNS: `orthanc.<EC2_PUBLIC_IP>.sslip.io` zeigt automatisch auf deine IP.

### SuS-Zugang (wenn Orthanc für alle SuS sichtbar sein soll)

Wenn du Orthanc für alle SuS erreichbar machst, gib ihnen den gemeinsamen Basic-Auth-Login (z.B. User `sus` + Passwort, das du selbst setzt). Diese Zugangsdaten stehen **nicht** im Repo, sondern nur in deiner Server-Umgebung (`ORTHANC_PROXY_*`).
Im Repo-Ordner:

```
git pull
docker compose -f docker-compose.server.yml up -d --build
```

