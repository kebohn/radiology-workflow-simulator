# Deployment: Zentraler Server (ein Stack für alle SuS)

Ziel: Ein zentraler Server hostet die App. SuS greifen per Browser zu.

Wichtige Hinweise:
- Orthanc ist **kein Multi-Tenant PACS**. Harte Isolation pro SuS geht nur mit getrennten Backends.
- Dieses Repo implementiert daher eine **soft isolation**: SuS setzen einen **SuS-Code**; PID/Accession werden intern geprefixt und die Workstation filtert standardmässig darauf.
- Für echte Trennung: pro SuS eigener Stack (z.B. Codespaces) oder pro SuS eigenes Orthanc.

## Empfohlenes Minimal-Setup

- 1 VPS (Ubuntu) + Docker + Docker Compose
- Reverse Proxy: **Caddy** (TLS/HTTPS automatisch)
- Public: nur der Simulator (HTTP/HTTPS)
- Orthanc: nur lokal am Server (127.0.0.1), Trainer-Zugriff per SSH Port-Forward

## Schritt 1: Server vorbereiten

1. Docker installieren (Engine) und Compose Plugin aktivieren.
2. Firewall:
   - erlauben: 80 (und 443 falls HTTPS)
   - blockieren: 8042/4242 (Orthanc)

## Schritt 1b: Domain + HTTPS (empfohlen)

1. DNS:
   - `A` Record (oder `AAAA`) für z.B. `sim.example.org` auf die Server-IP setzen
2. In [deploy/Caddyfile](deploy/Caddyfile) `:80` durch deine Domain ersetzen:
   - `sim.example.org { ... }`
3. In [docker-compose.server.yml](docker-compose.server.yml) Port `443:443` aktivieren (auskommentieren).

Caddy holt dann automatisch Zertifikate via Let's Encrypt.

## Schritt 2: Repo auf den Server

Variante A (simpel): per Git clone
- Repo auf den Server klonen
- `cd orthanc-example`

Variante B (besser): Prebuilt Images (z.B. GHCR)

Du kannst den Simulator als vorgebautes Image betreiben, damit der Server nichts kompilieren/bauen muss.

## Schritt 3: Secrets/Env setzen

Auf dem Server im Repo-Ordner eine `.env` anlegen:

```
FLASK_SECRET_KEY=please-change-me-long-random
# Aktiviert das Admin-Panel unter /admin (zum Generieren von SuS-Codes)
ADMIN_PASSWORD=please-change-me
# Optional: wenn Sie nicht 20 Codes wollen, hier anpassen
# AUTO_GENERATE_SESSIONS=20
# ORTHANC_PUBLIC_URL leer lassen (Orthanc nicht öffentlich)
ORTHANC_PUBLIC_URL=
```

## Schritt 4: Starten

```
docker compose -f docker-compose.server.yml up -d --build
```

Danach ist die App unter `http://SERVER-IP/` erreichbar.

Hinweis: Die Startseite leitet auf `/welcome` um, bis ein SuS-Session-Key gesetzt wurde.

Mit Domain + HTTPS: `https://sim.example.org/`

## Trainer: Orthanc UI trotzdem nutzen

Orthanc läuft nur auf `127.0.0.1:8042`.
Von deinem Laptop:

```
ssh -L 8042:127.0.0.1:8042 user@SERVER
```

Dann lokal im Browser: `http://localhost:8042` (Login: `trainer` / `trainer123`).

## Parameter-Ueberblick (Server)

Auf dem Server im Repo-Ordner eine `.env` anlegen (siehe auch `.env.server.example`):
- `FLASK_SECRET_KEY` (Pflicht)
- `ADMIN_PASSWORD` (Pflicht, aktiviert `/admin`)
- `AUTO_GENERATE_SESSIONS` (optional, Default 20)
- `ORTHANC_PUBLIC_URL` (optional, auf Server meist leer)

Optional (wenn du den Simulator als Image betreibst):
- `SIMULATOR_IMAGE` (z.B. `ghcr.io/<owner>/<repo>-simulator:latest`)

## Optional: Prebuilt Simulator Image (kein Build auf dem Server)

Wenn der Server nicht bauen soll oder das Build lange dauert, kannst du den Simulator als Image bauen und in eine Registry pushen (z.B. GHCR). Der Server zieht dann nur noch das Image.

1. In deiner Server-`.env` zusätzlich setzen:

```
SIMULATOR_IMAGE=ghcr.io/<owner>/<repo>-simulator:latest
```

2. Image bauen und pushen (lokal oder in einer CI), Beispiel lokal:

```
docker login ghcr.io
docker buildx build --platform linux/amd64 \
   -t ghcr.io/<owner>/<repo>-simulator:latest \
   --push ./simulator
```

Wenn das Image public ist, braucht der Server kein `docker login` zum Pullen.

3. Deploy ohne Build:

```
docker compose -f docker-compose.server.yml pull simulator
docker compose -f docker-compose.server.yml up -d --no-build
```

Hinweis: Der Workflow [.github/workflows/build-simulator-image.yml](.github/workflows/build-simulator-image.yml) ist aktuell ein Build-Test (build-only) und pusht nichts nach GHCR.

## CI: Build-Only Workflow (Smoke Test)

Der Workflow [.github/workflows/build-simulator-image.yml](.github/workflows/build-simulator-image.yml) baut bei Push/PR (nur wenn sich `simulator/**` ändert) das Docker Image als schnellen Smoke Test. Er benötigt keine Secrets.

## Betrieb für SuS (wichtig)

- Einmalig als Trainer: `http://SERVER-IP/admin` öffnen, mit `ADMIN_PASSWORD` einloggen und **20 Codes generieren** (oder `AUTO_GENERATE_SESSIONS` nutzen).
- SuS bekommen jeweils einen Code oder direkt den Join-Link `/join/<CODE>`.
- Ohne gesetzten Code landen SuS immer zuerst auf `/welcome`.
- Sobald Codes existieren, akzeptiert der Simulator nur noch diese Codes.

