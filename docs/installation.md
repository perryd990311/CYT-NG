# Installation Guide

Deploy CYT-NG on a Synology NAS (or any Docker-capable host).

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Docker Engine | 20.10+ |
| Docker Compose | v2+ |
| Git | any |
| NAS Storage | 2 GB+ free for database and logs |

On Synology, Docker is available through **Container Manager** (DSM 7.2+) or the legacy **Docker** package.

## 1. Create the Directory Structure

SSH into your NAS and set up the working directory:

```bash
# Adapt this path to your host — e.g. /volume1/docker/cyt-ng on Synology
mkdir -p /path/to/cyt-ng
cd /path/to/cyt-ng

# Clone the repo — the trailing "repo" forces the folder name
git clone https://github.com/perryd990311/CYT-NG.git repo
```

> The folder **must** be named `repo` — the `docker-compose.yaml` build context and post-receive deploy hook expect this path.

Create persistent data directories that live outside the container:

```bash
mkdir -p data/cyt data/logs data/reports data/kml
mkdir -p kismet_data
```

Ignore lists (`maclist.json`, `ssidlist.json`) ship with the repo and are managed through the web UI at **Settings → Ignore Lists & Baseline** — no need to create them manually.

## 2. Configure Environment

```bash
cd repo
cp .env.example .env
```

Edit `.env` with your values:

```env
# Required
CYT_SECRET_KEY=<generate-a-random-64-char-string>

# Optional — Synology SSO (see docs/synology-sso.md)
SYNOLOGY_DSM_URL=https://your-nas:5001
SYNOLOGY_OAUTH_CLIENT_ID=
SYNOLOGY_OAUTH_CLIENT_SECRET=

# Optional — WiGLE geolocation
WIGLE_API_TOKEN=

# Paths (match docker-compose volume mounts)
KISMET_DATA_PATH=/data/kismet
CYT_DATABASE_PATH=/data/cyt/cyt_data.db

# Optional — TLS (auto-generates self-signed if empty)
TLS_CERT_PATH=
TLS_KEY_PATH=
```

> Generate a secret key: `python3 -c "import secrets; print(secrets.token_hex(32))"`

## 3. Set Up the Kismet Data Share

Sensors sync `.kismet` files to the NAS via SMB.

### Create a sensor service account

1. In DSM, go to **Control Panel → User & Group → Create**
2. Create a dedicated user (e.g., `cyt-sensor`) — this account will be used by all RPi sensors to mount the share
3. Assign a strong password and disable all application permissions except file access
4. Do **not** add the account to the `administrators` group

### Create the shared folder

1. In DSM, go to **Control Panel → Shared Folder → Create**
2. Name it `kismet_data` (or similar)
3. Note the local path (e.g., the `kismet_data` directory alongside the repo)

### Set permissions

On the **shared folder** level (Control Panel → Shared Folder → Edit → Permissions):

| User | Permission |
|------|------------|
| `cyt-sensor` | Read/Write |

On the **subfolder/file** level, ensure the sensor account has:

- **Traverse** rights on the share root (so the sensor can navigate into subdirectories)
- **Read/Write** on files within its sensor subdirectory

In DSM: Shared Folder → Edit → **Advanced Permissions** → enable "Traverse folders / execute files" for the `cyt-sensor` user.

> **Tip**: If using ACLs, grant `traverse`, `read data`, `write data`, and `create files/folders` on the share root, applied to "This folder, sub-folders and files."

### Directory layout

Organize by sensor hostname — each sensor writes to its own subdirectory:

```
kismet_data/
  ├── sensor-living-room/
  │   └── Kismet-20250425-1200.kismet
  └── sensor-garage/
      └── Kismet-20250425-1200.kismet
```

## 4. TLS Certificates

**Option A: Bring your own certs**

Place your cert and key files and set in `.env`:

```env
TLS_CERT_PATH=/path/to/fullchain.pem
TLS_KEY_PATH=/path/to/privkey.pem
```

**Option B: Self-signed (default)**

If `TLS_CERT_PATH` is empty, the nginx container auto-generates a self-signed certificate on first start. Your browser will show a security warning — acceptable for LAN use.

**Option C: Use your Synology DSM certificate**

If your NAS already has a valid certificate (Let's Encrypt or CA-signed) managed by DSM:

1. In DSM, go to **Control Panel → Security → Certificate**
2. Select the certificate and click **Export** — this downloads a `.zip` containing `cert.pem`, `privkey.pem`, and `chain.pem` (or similar)
3. Extract the files to a directory on the NAS, e.g., `certs/` alongside the repo
4. Set the paths in `.env`:

```env
TLS_CERT_PATH=/certs/fullchain.pem
TLS_KEY_PATH=/certs/privkey.pem
```

5. If the export gives you separate `cert.pem` and `chain.pem`, concatenate them:

```bash
cat cert.pem chain.pem > fullchain.pem
```

6. Mount the certs directory into the nginx container (already handled by the default `docker-compose.yaml` volume mapping)

> **Note**: DSM certificates auto-renew, but the exported copies do not. Re-export and restart nginx after renewal, or symlink to DSM's internal cert path (`/usr/syno/etc/certificate/`) if your NAS user has access.

## 5. Build and Launch

CYT-NG uses a **two-stage Docker build** to keep deploys fast:

| Image | Purpose | Rebuild when… |
|-------|---------|---------------|
| `cyt-base:latest` | Python runtime + all pip dependencies | `requirements.txt` changes or Python version bumps |
| `cyt-web` (compose) | Application code only — built `FROM cyt-base:latest` | Any code, template, or config change |

Because the base image bakes in all pip packages, a normal `docker compose build` only copies application files and takes a few seconds.

### Build the base image (first time, or after dependency changes)

```bash
cd /path/to/cyt-ng
docker build -f repo/docker/Dockerfile.base -t cyt-base:latest .
```

> **Note:** The build context is the project root (`/path/to/cyt-ng`), not the repo subdirectory. The Dockerfile references paths like `repo/requirements.txt` relative to this context.

### Build and start the app

```bash
docker compose build cyt-web
docker compose up -d
```

Verify both containers are healthy:

```bash
docker compose ps
```

You should see:

| Container | Status |
|-----------|--------|
| cyt-web | Up (healthy) |
| cyt-nginx | Up |

> If `cyt-web` fails with `FROM cyt-base:latest — image not found`, you need to build the base image first (see above).

## 6. First Login

1. Open `https://your-nas-ip` in a browser
2. You'll be redirected to the **account setup** page (first-time only)
3. Create an admin username and password
4. You're in — the dashboard will show "0 devices" until sensors start syncing data

## Updating

```bash
cd /path/to/cyt-ng
git -C repo pull   # or push from dev machine

# If requirements.txt changed, rebuild the base image first:
docker build -f repo/docker/Dockerfile.base -t cyt-base:latest .

# Then rebuild and restart the app:
docker compose build cyt-web
docker compose up -d
```

> If only application code changed (no new pip packages), skip the base image build — `docker compose build cyt-web` is all you need.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Container won't start | Check `docker compose logs cyt-web` for Python errors |
| "Permission denied" on database | Verify `user:` in docker-compose.yaml matches NAS UID:GID |
| Nginx 502 Bad Gateway | cyt-web isn't healthy yet — wait 40s for healthcheck |
| Sensors not syncing | Verify SMB mount and directory structure in `kismet_data/` |
