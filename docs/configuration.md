# Configuration Reference

CYT-NG uses two configuration sources:

- **`config.json`** — Application settings (paths, timing, thresholds)
- **`.env`** — Secrets and environment variables (never committed to git)

## config.json

Editable from the web UI at **Settings → Configuration**, or by editing the file directly.

In Docker, a writable override is stored at `/data/cyt/config.json`. The baked-in default at the repo root is read-only.

### Full Reference

```json
{
  "paths": {
    "kismet_logs": "/data/kismet",
    "cyt_database": "/data/cyt/cyt_data.db",
    "ignore_lists": "ignore_lists",
    "reports_dir": "/data/reports",
    "kml_dir": "/data/kml"
  },
  "timing": {
    "check_interval": 60,
    "analysis_interval_hours": 6,
    "cleanup_interval_hours": 24,
    "retention_days": 90,
    "time_windows": [5, 10, 15, 20]
  },
  "search": {
    "lat_min": 0.0,
    "lat_max": 0.0,
    "lon_min": 0.0,
    "lon_max": 0.0
  },
  "fingerprinting": {
    "jaccard_threshold": 0.85,
    "min_ssids_for_fingerprint": 2
  }
}
```

### Section Details

#### paths

| Key | Description | Default |
|-----|-------------|---------|
| `kismet_logs` | Directory containing `.kismet` files from sensors | `/data/kismet` |
| `cyt_database` | Path to the CYT SQLite database | `/data/cyt/cyt_data.db` |
| `ignore_lists` | Directory containing MAC and SSID ignore list JSON files | `ignore_lists` |
| `reports_dir` | Output directory for analysis reports | `/data/reports` |
| `kml_dir` | Output directory for KML/Google Earth files | `/data/kml` |

#### timing

| Key | Description | Default |
|-----|-------------|---------|
| `check_interval` | Seconds between Kismet file ingestion runs | `60` |
| `analysis_interval_hours` | Hours between automated analysis runs | `6` |
| `cleanup_interval_hours` | Hours between database cleanup jobs | `24` |
| `retention_days` | Days to keep appearance data before cleanup | `90` |
| `time_windows` | Minutes — sliding windows for persistence scoring | `[5, 10, 15, 20]` |

#### search

GPS bounding box for WiGLE SSID geolocation lookups. Set to `0.0` to disable.

| Key | Description |
|-----|-------------|
| `lat_min` / `lat_max` | Latitude range |
| `lon_min` / `lon_max` | Longitude range |

#### fingerprinting

| Key | Description | Default |
|-----|-------------|---------|
| `jaccard_threshold` | Minimum Jaccard similarity (0.0–1.0) to cluster two SSID probe pools as the same device | `0.85` |
| `min_ssids_for_fingerprint` | Minimum unique SSIDs a device must probe before fingerprint analysis applies | `2` |

## .env

Secrets and Docker-specific settings. Never committed to git.

### Full Reference

```env
# Required
CYT_SECRET_KEY=<random-64-char-hex>

# Flask mode
FLASK_ENV=production

# Synology DSM OAuth2 SSO (optional)
SYNOLOGY_DSM_URL=https://your-nas:5001
SYNOLOGY_OAUTH_CLIENT_ID=
SYNOLOGY_OAUTH_CLIENT_SECRET=

# WiGLE API (optional)
WIGLE_API_TOKEN=

# Data paths (should match docker-compose volume mounts)
KISMET_DATA_PATH=/data/kismet
CYT_DATABASE_PATH=/data/cyt/cyt_data.db

# TLS certificates (optional)
TLS_CERT_PATH=
TLS_KEY_PATH=
```

### Variable Details

| Variable | Required | Description |
|----------|----------|-------------|
| `CYT_SECRET_KEY` | Yes | Flask session encryption key. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `FLASK_ENV` | No | `production` (default) or `development` |
| `SYNOLOGY_DSM_URL` | No | Base URL of your Synology NAS. See [Synology SSO](synology-sso.md) |
| `SYNOLOGY_OAUTH_CLIENT_ID` | No | OAuth2 Client ID from DSM |
| `SYNOLOGY_OAUTH_CLIENT_SECRET` | No | OAuth2 Client Secret from DSM |
| `WIGLE_API_TOKEN` | No | WiGLE API token for SSID geolocation |
| `KISMET_DATA_PATH` | No | Override Kismet data path (default: from config.json) |
| `CYT_DATABASE_PATH` | No | Override database path (default: from config.json) |
| `TLS_CERT_PATH` | No | Path to TLS certificate (PEM). Auto-generates self-signed if empty |
| `TLS_KEY_PATH` | No | Path to TLS private key (PEM) |

## Ignore Lists

Two JSON files control which devices and networks are excluded from analysis. Both ship with the repo (in `ignore_lists/`) and are managed through the web UI at **Settings → Ignore Lists & Baseline** — no manual editing required.

### ignore_lists/maclist.json

```json
[
  "AA:BB:CC:DD:EE:FF",
  "11:22:33:44:55:66"
]
```

MACs in this list are treated as "baseline" — your own devices, family devices, etc. They still appear in the UI but are visually marked and excluded from surveillance scoring. You can also add devices to the baseline directly from the dashboard using the "Add to Baseline" checkbox.

### ignore_lists/ssidlist.json

```json
[
  "MyHomeNetwork",
  "CoffeeShopWiFi"
]
```

SSIDs in this list are ignored during fingerprint analysis.
