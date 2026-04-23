# Chasing Your Tail NG (CYT-NG)

A Wi-Fi probe request surveillance detection system. Kismet sensors on Raspberry Pis capture wireless frames and sync `.kismet` SQLite files to a Synology NAS. A Flask web UI provides real-time monitoring, device tracking, analysis, and reporting.

## Architecture

```
RPi (Kismet sensor) --SMB sync--> Synology NAS (Docker)
                                    cyt-nginx   (TLS reverse proxy)
                                    cyt-web     (Flask + SocketIO)
                                        cyt/    analysis engine
                                        SQLite  CYT database
```

## Stack

- **Python 3.12**, Flask, Flask-SocketIO, HTMX, Chart.js, SQLAlchemy, SQLite
- **Docker**: `cyt-web` (Gunicorn + gevent) + `cyt-nginx` (TLS reverse proxy)
- **Auth**: Synology DSM OAuth2 SSO + local bcrypt fallback via Flask-Login
- **Target**: Synology DS218+ (x86_64, DSM 7.3.2)

## Directory Layout

```
cyt/              Python package  analysis engine, models, security modules
  models.py       SQLAlchemy models (Device, Appearance, Fingerprint, User, Sensor)
  kismet_reader.py          Incremental .kismet file ingestion
  surveillance_detector.py  Persistence scoring engine
  surveillance_analyzer.py  GPS correlation + KML export
  sensor_provisioner.py     SSH-based RPi sensor provisioning
  fingerprint.py            SSID fingerprint similarity (Jaccard)
  tasks.py                  APScheduler background tasks
  secure_database.py        Parameterized Kismet DB queries
  secure_credentials.py     Fernet-encrypted credential storage
  input_validation.py       MAC/SSID/path sanitization
web/              Flask application
  app.py          App factory
  routes/         Blueprints: dashboard, devices, analysis, sensors, settings, auth
  templates/      Jinja2 templates + HTMX partials
  auth/           Synology OAuth2 + local login
  static/         CSS, JS
docker/           Dockerfile + entrypoint.sh
nginx/            TLS reverse proxy config
sensor/           RPi provisioning scripts (install.sh, kismet_sync.sh)
```

## Requirements

- Docker + Docker Compose (deployment target: Synology NAS)
- Raspberry Pi with Kismet and a monitor-mode Wi-Fi adapter (sensors)
- SMB share on NAS for `.kismet` file sync

## Deployment

```bash
# Push to NAS bare git remote (triggers post-receive hook)
git push nas main

# Rebuild and restart on NAS
ssh user@nas "cd /volume1/docker/cyt-ng/repo && \
  docker compose build --no-cache cyt-web && \
  docker compose up -d"
```

The `.env` file on the NAS holds secrets (`SECRET_KEY`, `WIGLE_TOKEN`, OAuth2 credentials). See `.env.example`.

## Sensor Provisioning

From the web UI (Settings  Sensors  Add Sensor), fill in hostname, SSH user/port, Wi-Fi interface, and SMB share path. Click **Provision / Reinstall**  the UI prompts for SSH and NAS credentials (never stored), then runs 11 steps over SSH:

1. TCP port check
2. SSH connectivity
3. Sudo check
4. `apt-get update`
5. Install Kismet
6. Create `kismet` user
7. Create log directory
8. Install sync script (`sensor/kismet_sync.sh`)
9. Mount NAS share (writes `/etc/cyt-nas.creds` via SFTP, chmod 600)
10. Enable sync timer
11. Detect Kismet version

Progress is streamed live via SocketIO.

## Configuration

`config.json`  paths, timing, search bounds, fingerprinting thresholds.  
`.env`  secrets only (never committed).

Key config sections:
- `paths`: kismet_logs, cyt_database, ignore_lists, reports_dir, kml_dir
- `timing`: check_interval, time_windows (5/10/15/20 min)
- `search`: lat/lon bounds for WiGLE
- `fingerprinting`: jaccard_threshold (0.85), min_ssids_for_fingerprint (2)

## Security

- All SQL queries use parameterized statements  no string-format SQL
- No `exec()` or `eval()` anywhere in active code
- Input validated via `cyt/input_validation.py` (MAC, SSID, paths)
- API credentials encrypted via Fernet + PBKDF2 (`cyt/secure_credentials.py`)
- Docker containers run as non-root (`cyt:cyt`)
- Nginx enforces HSTS, X-Content-Type-Options, X-Frame-Options, CSP
- Rate limiting on auth endpoints (Flask-Limiter)
- SSH/NAS credentials used once during provisioning and never persisted

## Author

@perryd990311 / @matt0177

## License

MIT License

## Disclaimer

Intended for legitimate security research, network administration, and personal safety purposes. Users are responsible for complying with all applicable laws in their jurisdiction.
