---
name: "CYT Web"
description: "Phase 2: Build Flask + HTMX web interface for CYT-NG. Creates routes, templates, WebSocket events, dashboard, HTMX partials, and Chart.js visualizations."
model: sonnet
---

# CYT-NG Phase 2: Web Application Agent

You build the Flask + HTMX web UI that replaces the Tkinter GUI.

## Stack
- Flask app factory pattern (`create_app()`)
- Flask-SocketIO for real-time WebSocket events
- HTMX for dynamic partials (no SPA framework)
- Chart.js for data visualization
- Dark theme, responsive (no 800x480 constraint)

## Key Files
- `web/app.py` — App factory
- `web/extensions.py` — Flask-SocketIO, Flask-Login, SQLAlchemy init
- `web/config.py` — Config from env vars + config.json
- `web/routes/` — Blueprint modules (dashboard, analysis, devices, reports, settings, sensors)
- `web/templates/` — Jinja2 templates with HTMX attributes
- `web/templates/partials/` — HTMX partial fragments
- `web/static/` — CSS (dark theme), JS (WebSocket + HTMX config)

## Conventions
- All routes return full pages OR HTMX partials based on `HX-Request` header
- WebSocket events: `device_update`, `status_update`, `analysis_progress`
- Blueprints registered in app factory
- Import analysis engine from `cyt.*` package
