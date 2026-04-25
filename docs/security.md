# Security Model

CYT-NG is designed to run on a private LAN, but security is built in at every layer. This document covers the hardening measures in place.

## Authentication

### Local Login

- Passwords hashed with **bcrypt** (cost factor 12)
- Rate limited: 10 login attempts per minute per IP (Flask-Limiter)
- Session cookies are `HttpOnly`, `Secure`, and `SameSite=Lax`

### Synology SSO

- OAuth2 authorization code flow (no implicit grant)
- Client secrets stored in `.env`, never exposed to the browser
- Token exchange is server-to-server
- See [Synology SSO](synology-sso.md) for setup

### First-Run Setup

- If no users exist, the app redirects to a one-time setup page
- The setup page is only accessible when the user table is empty
- After the first account is created, setup is permanently disabled

## Database Security

### Parameterized Queries

All database access uses SQLAlchemy ORM or parameterized statements. String-formatted SQL is prohibited project-wide.

```python
# Always this:
db.query(Device).filter(Device.mac_address == mac)

# Never this:
db.execute(f"SELECT * FROM devices WHERE mac = '{mac}'")  # FORBIDDEN
```

### Input Validation

The `cyt/input_validation.py` module validates all user-supplied data at the boundary:

| Input | Validation |
|-------|-----------|
| MAC addresses | Regex pattern match, format normalization |
| SSIDs | Length limits, character filtering |
| File paths | Path traversal prevention, allowlisting |
| Hostnames | DNS-safe character validation |
| Ports | Integer range (1–65535) |

### No Dynamic Code Execution

`exec()` and `eval()` are completely absent from the active codebase. This was a deliberate hardening decision.

## Credential Management

### Encrypted Storage

API credentials (e.g., WiGLE tokens) are encrypted at rest using:

- **Fernet** symmetric encryption
- Key derived via **PBKDF2** with 480,000 iterations
- Stored in `secure_credentials/` directory
- The `.env` secret key is never written to disk beyond the env file

### Sensor Provisioning Credentials

When provisioning a sensor, the UI collects SSH and NAS passwords. These are:

- Used once for the provisioning session
- Transmitted directly to the Pi over SSH
- **Never stored** in the database or filesystem
- Not logged anywhere

NAS credentials written to the sensor (`/etc/cyt-nas.creds`) are chmod 600 and owned by root.

## Docker Hardening

The `docker-compose.yaml` enforces:

| Control | Setting |
|---------|---------|
| **Non-root user** | `user: "1031:100"` |
| **Read-only filesystem** | `read_only: true` |
| **No privilege escalation** | `security_opt: no-new-privileges:true` |
| **Tmpfs for writables** | `/tmp` and `/run` as tmpfs |
| **Health checks** | HTTP health endpoint every 30s |
| **Restart policy** | `unless-stopped` |

## Nginx / TLS

The `cyt-nginx` reverse proxy enforces:

### Headers

| Header | Value |
|--------|-------|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Content-Security-Policy` | Restrictive policy allowing only required CDN sources |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |

### TLS

- HTTP automatically redirects to HTTPS
- TLS 1.2+ only (1.3 preferred)
- Strong cipher suite configuration
- Self-signed certificate auto-generated if none provided

## Network Security

- CYT-NG is designed for **LAN-only access**
- No cloud dependencies or external API calls (except optional WiGLE)
- Sensor-to-NAS communication uses SMB over the local network
- Web UI should not be exposed to the public internet without a VPN

## Files Never Committed

The following are in `.gitignore` and must never enter version control:

- `.env` — secrets
- `secure_credentials/` — encrypted API tokens
- `*.pem`, `*.key` — TLS certificates
- `*.kismet` — raw sensor data
- `cyt_data.db` — the CYT database

## Reporting Security Issues

If you discover a security vulnerability, please open a private issue or contact the maintainers directly. Do not disclose vulnerabilities publicly before a fix is available.
