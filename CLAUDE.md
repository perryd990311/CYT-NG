# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CYT-NG (Chasing Your Tail — Next Generation) is a Wi-Fi probe request surveillance detection system. Kismet sensors on Raspberry Pis capture wireless frames and sync `.kismet` SQLite files to a Synology DS218+ NAS. A Flask web UI (in progress) provides real-time monitoring, analysis, and reporting via Docker.

## Architecture

```
RPi (Kismet sensor) --SMB sync--> Synology NAS (Docker)
                                   ├── cyt-nginx (TLS/HTTPS)
                                   └── cyt-web (Flask+SocketIO)
                                       ├── cyt/ analysis engine
                                       └── SQLite (own DB)
```

## Directory Layout

```
cyt/                  # Python package — analysis engine, models, security modules
  __init__.py         # Package exports
  models.py           # SQLAlchemy models (Device, Appearance, Fingerprint, User, Sensor, etc.)
  kismet_reader.py    # Batch .kismet file reader with incremental ingestion
  surveillance_detector.py  # Core persistence detection engine
  surveillance_analyzer.py  # Orchestrator with GPS correlation + KML
  gps_tracker.py      # GPS tracking + KML export
  probe_analyzer.py   # WiGLE SSID geolocation integration
  secure_database.py  # Parameterized Kismet DB queries
  secure_credentials.py     # Fernet-encrypted credential management
  secure_main_logic.py      # Secure monitoring logic
  secure_ignore_loader.py   # Safe ignore list loading (replaced exec())
  input_validation.py       # MAC/SSID/path sanitization
web/                  # Flask application (Phase 2 — not yet built)
  routes/             # Blueprint modules
  templates/partials/ # HTMX partial fragments
  static/css/, js/    # Frontend assets
  auth/               # Authentication modules
docker/               # Dockerfile, docker-compose files
nginx/                # TLS reverse proxy config
sensor/               # RPi Kismet sensor provisioning scripts
legacy/               # Archived: Tkinter GUI, old scripts, presentation docs
.github/agents/       # 9 Copilot agent definitions
.github/copilot-instructions.md  # Workspace-wide coding conventions
.tmp/plan.md          # 5-phase migration plan with progress tracking
```

## Key Files at Root

- `chasing_your_tail.py` — Core monitoring engine (imports from `cyt.*`)
- `migrate_credentials.py` — Tool to migrate insecure credentials
- `config.json` — Paths, timing, search bounds, web/docker/sensor/fingerprinting config
- `requirements.txt` — Python dependencies
- `.env.example` — Environment variable template
- `.dockerignore` — Docker build exclusions

## Coding Conventions

- All imports from the analysis engine use `cyt.` prefix: `from cyt.secure_database import SecureKismetDB`
- All database queries use **parameterized statements** — never string-format SQL
- No `exec()` or `eval()` — eliminated as part of security hardening
- Flask routes go in `web/routes/` as blueprints registered in the app factory
- HTMX partials check for `HX-Request` header
- Config in `config.json` (paths, timing) and `.env` (secrets)
- Credentials encrypted via `cyt/secure_credentials.py` (Fernet + PBKDF2)
- Never commit `.env`, `secure_credentials/`, or `*.pem`/`*.key` files
- Validate all MAC addresses and SSIDs via `cyt/input_validation.py`

## Configuration

`config.json` contains:
- `paths`: base_dir, log_dir, kismet_logs, cyt_database, ignore_lists, reports_dir, kml_dir
- `timing`: check_interval (60s), list_update_interval (5 cycles), time_windows (5/10/15/20 min)
- `search`: lat/lon bounds for WiGLE
- `web`: host, port, secret_key_env
- `docker`: image_name, ports, volume paths
- `sensor`: sync_interval, smb_share, health_check_interval
- `fingerprinting`: jaccard_threshold (0.85), min_ssids_for_fingerprint (2)

## Development Commands

```bash
# Install dependencies
pip3 install -r requirements.txt

# Migrate credentials to encrypted storage
python3 migrate_credentials.py

# Run core monitoring
python3 chasing_your_tail.py

# Run surveillance analysis
python3 -m cyt.surveillance_analyzer

# Run probe analysis (local only, past 14 days)
python3 -m cyt.probe_analyzer
```

## Migration Status

See `.tmp/plan.md` for the full 5-phase migration plan.

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Project Restructure | ✅ Complete |
| 2 | Flask + HTMX Web UI | Not started |
| 3 | Auth & HTTPS | Not started |
| 4 | SSID Fingerprinting | Not started |
| 5 | Docker & Deployment | Not started |

## Security

- SQL injection: All queries parameterized via `cyt/secure_database.py`
- Credential exposure: API keys encrypted with Fernet + PBKDF2 via `cyt/secure_credentials.py`
- Input validation: Comprehensive sanitization in `cyt/input_validation.py`
- Ignore lists: Safe JSON loading via `cyt/secure_ignore_loader.py` (no exec())
- Docker: Containers run as non-root; Nginx enforces HSTS, CSP, X-Frame-Options