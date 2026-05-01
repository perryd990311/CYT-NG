# CYT-NG Copilot Instructions

## Project
CYT-NG is a Wi-Fi probe request surveillance detection system. Kismet sensors on Raspberry Pis capture wireless frames and sync `.kismet` SQLite files to a Synology NAS. A Flask web UI provides real-time monitoring, analysis, and reporting.

## Stack
- **Python 3.11**, Flask, Flask-SocketIO, HTMX, Chart.js, SQLAlchemy, SQLite
- **Docker**: cyt-web (Gunicorn + gevent) + cyt-nginx (TLS reverse proxy)
- **Auth**: Synology DSM OAuth2 SSO + local bcrypt fallback via Flask-Login
- **Target**: Synology DS218+ (x86_64, 10GB RAM, DSM 7.3.2)

## Directory Layout
```
cyt/        # Python package — analysis engine, models, security modules
web/        # Flask app — routes, templates, auth, static assets
docker/     # Dockerfile, docker-compose files
nginx/      # TLS reverse proxy config
sensor/     # RPi Kismet sensor provisioning scripts
legacy/     # Archived Tkinter GUI (do not import from here)
```

## Coding Conventions
- All database queries use **parameterized statements** — never string-format SQL
- No `exec()` or `eval()` — eliminated as part of security hardening
- Imports from the analysis engine use the `cyt.` package prefix: `from cyt.input_validation import InputValidator`
- Flask routes go in `web/routes/` as blueprints registered in the app factory
- HTMX partials live in `web/templates/partials/` and check for `HX-Request` header
- Config lives in `config.json` (paths, timing, search) and `.env` (secrets)

## Security Rules
- Never commit `.env`, `secure_credentials/`, or `*.pem`/`*.key` files
- Validate all MAC addresses and SSIDs via `cyt/input_validation.py`
- Rate-limit authentication endpoints
- Docker containers run as non-root
- Nginx enforces HSTS, X-Content-Type-Options, X-Frame-Options, CSP

## Agent Work Tracking (BMAD)
All agent work is tracked in `.github/agent-work/` using a BMAD-inspired workflow:

1. **Business** — GitHub Issue defines the goal
2. **Mission** — Feature `.md` file in `agent-work/` defines the deliverable
3. **Architecture** — Design decisions recorded in the feature file
4. **Development** — Task checklist tracked to completion

### Workflow
- `agent-work/backlog/` — Planned features (linked to GitHub Issues)
- `agent-work/active/` — In-progress work (check here at session start)
- `agent-work/completed/` — Finished work (knowledge base)
- `agent-work/templates/` — Feature and task templates

### Agent Rules
- **Session start**: Read `agent-work/active/` to restore context
- **New work**: Create feature file from template, link to GitHub Issue
- **During work**: Update checkboxes and decisions in real-time
- **Work done**: Move file to `completed/`, close GitHub Issue

## Agent Routing
- **Runtime issues** (app errors, broken pages, container failures): use `/debugger` agent
- **Code implementation** (new features, deploying changes, infrastructure updates): use `/code-implementer` agent
