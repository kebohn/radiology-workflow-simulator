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

Variante B (besser): Images via GitHub Container Registry (GHCR)
- Siehe "GitHub Actions" unten

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

## GitHub Actions (Deploy über GitHub)

Einfacher Workflow:
- Action baut ein Image und pushed nach GHCR
- Server zieht das Image und startet Compose neu

Minimal-Ansatz (Pseudo-Schritte):
1. GitHub Repo Settings:
   - Secrets: `SERVER_SSH_KEY`, `SERVER_HOST`, `SERVER_USER`
   - Optional: `GHCR_IMAGE` (oder hart codieren)
2. Action:
   - `docker build` / `docker push` nach `ghcr.io/<org>/<repo>:latest`
   - per SSH:
     - `docker login ghcr.io`
     - `docker compose -f docker-compose.server.yml pull`
     - `docker compose -f docker-compose.server.yml up -d`

Dieses Repo enthält bereits einen einfachen Workflow: [.github/workflows/deploy-central-server.yml](.github/workflows/deploy-central-server.yml)

## Optional: Prebuilt Simulator Image (kein Build auf dem Server)

Wenn der Server keine Build-Tools haben soll oder das Build lange dauert, kannst du den Simulator als Image bauen und in eine Registry pushen (z.B. GHCR). Der Server zieht dann nur noch das Image.

1. In deiner Server-`.env` zusätzlich setzen:

```
SIMULATOR_IMAGE=ghcr.io/<owner>/<repo>-simulator:latest
```

2. (Falls Repo/Package privat) einmalig auf dem Server bei GHCR einloggen:

```
echo "<TOKEN>" | docker login ghcr.io -u "<USERNAME>" --password-stdin
```

3. Deploy ohne Build:

```
docker compose -f docker-compose.server.yml pull simulator
docker compose -f docker-compose.server.yml up -d --no-build
```

Hinweis: Im Repo gibt es einen Build-Workflow, der das Simulator-Image nach GHCR pushed: [.github/workflows/build-simulator-image.yml](.github/workflows/build-simulator-image.yml)

### Nötige GitHub Secrets

- `SERVER_HOST`: z.B. `203.0.113.10` oder `sim.example.org`
- `SERVER_USER`: z.B. `ubuntu`
- `SERVER_SSH_KEY`: Private Key (ed25519) für den Deploy-User
- `SERVER_APP_DIR`: Pfad auf dem Server, z.B. `/opt/orthanc-example`

Der Workflow macht dann per SSH:
- `git pull`
- `docker compose -f docker-compose.server.yml up -d --build`

## Betrieb für SuS (wichtig)

- Einmalig als Trainer: `http://SERVER-IP/admin` öffnen, mit `ADMIN_PASSWORD` einloggen und **20 Codes generieren** (oder `AUTO_GENERATE_SESSIONS` nutzen).
- SuS bekommen jeweils einen Code oder direkt den Join-Link `/join/<CODE>`.
- Ohne gesetzten Code landen SuS immer zuerst auf `/welcome`.
- Sobald Codes existieren, akzeptiert der Simulator nur noch diese Codes.

