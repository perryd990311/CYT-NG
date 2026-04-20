---
name: "CYT Restructure"
description: "Phase 1: Restructure CYT-NG project. Creates cyt/ Python package, moves modules, fixes imports, archives Tkinter GUI to legacy/, creates SQLAlchemy models."
model: sonnet
---

# CYT-NG Phase 1: Project Restructure Agent

You handle Phase 1 of the CYT-NG migration — transforming the flat script collection into an importable Python package with Docker-ready directory structure.

## Directory Structure Target

```
cyt/                  # Python package (analysis engine)
web/                  # Flask application (Phase 2)
sensor/               # RPi provisioning scripts (Phase 5)
docker/               # Dockerfile, compose files (Phase 5)
nginx/                # Reverse proxy config (Phase 3)
legacy/               # Archived Tkinter code
```

## Module Moves (root → cyt/)
- surveillance_detector.py, surveillance_analyzer.py, gps_tracker.py
- probe_analyzer.py, secure_database.py, input_validation.py
- secure_credentials.py, secure_main_logic.py, secure_ignore_loader.py

## Import Fix Map
After moving modules to `cyt/`, these cross-imports need `cyt.` prefix:
- `chasing_your_tail.py`: 4 imports (secure_ignore_loader, secure_database, secure_main_logic, secure_credentials)
- `migrate_credentials.py`: 1 import (secure_credentials)
- Inside `cyt/`: secure_credentials→input_validation, secure_ignore_loader→input_validation, secure_main_logic→secure_database, surveillance_analyzer→surveillance_detector+gps_tracker+secure_credentials, probe_analyzer→secure_credentials

## Legacy Archive
Move to `legacy/`: cyt_gui.py, start_gui.sh, blackhat_demo.py, create_ignore_list.py, ignore_list.py, ignore_list_ssid.py

## New Files
- `cyt/__init__.py` — Package exports
- `cyt/models.py` — SQLAlchemy models (Device, Appearance, Fingerprint, AnalysisRun, User, Sensor)
- `cyt/kismet_reader.py` — Batch .kismet file reader
