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
- erlauben: 80/tcp (und 443/tcp falls HTTPS)
- nicht freigeben: 8042/tcp, 4242/tcp (Orthanc)

## Schritt 2: Repo klonen

```
git clone <REPO_URL> orthanc-example
cd orthanc-example
```

## Schritt 3: Secrets/Env setzen

```
cp .env.server.example .env
```

Dann `.env` editieren (mindestens `FLASK_SECRET_KEY` und `ADMIN_PASSWORD` setzen).

Tipp für `FLASK_SECRET_KEY`:

```
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Schritt 4: Starten

```
docker compose -f docker-compose.server.yml up -d --build
```

Danach ist die App erreichbar:
- ohne Domain: `http://SERVER-IP/`
- mit Domain + HTTPS: `https://sim.example.org/`

Hinweis: Die Startseite leitet auf `/welcome` um, bis ein SuS-Session-Key gesetzt wurde.

## Schritt 5: HTTPS aktivieren (optional, empfohlen)

1) DNS:
- `A` (oder `AAAA`) Record für z.B. `sim.example.org` auf die Server-IP setzen

2) Caddy konfigurieren:
- In [deploy/Caddyfile](deploy/Caddyfile) `:80` durch deine Domain ersetzen:
  - `sim.example.org { ... }`

3) Port 443 aktivieren:
- In [docker-compose.server.yml](docker-compose.server.yml) die Zeile `443:443` auskommentieren.

4) Änderungen anwenden:

```
docker compose -f docker-compose.server.yml up -d
```

Caddy holt dann automatisch Zertifikate via Let's Encrypt.

## Betrieb für SuS

- Einmalig als Trainer: `http://SERVER-IP/admin` öffnen, mit `ADMIN_PASSWORD` einloggen und Codes prüfen/generieren.
- SuS bekommen jeweils einen Code oder direkt den Join-Link `/join/<CODE>`.
- Ohne gesetzten Code landen SuS immer zuerst auf `/welcome`.

## Trainer: Orthanc UI trotzdem nutzen

Orthanc läuft nur auf `127.0.0.1:8042`. Von deinem Laptop:

```
ssh -L 8042:127.0.0.1:8042 user@SERVER
```

Dann lokal im Browser: `http://localhost:8042` (Login: `trainer` / `trainer123`).

## Update (neue Version deployen)

Im Repo-Ordner:

```
git pull
docker compose -f docker-compose.server.yml up -d --build
```

