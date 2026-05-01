# Feature: Dashboard Bug Fixes — Filtering, Active Count, Sparkline

**Status:** In Progress  
**GitHub Issue:** (pending)  
**Branch:** main  

---

## Business Goal
Five user-reported bugs on the dashboard make the ignore list ineffective and key stats misleading.

## Bugs Reported
1. **Top Persistent Devices** — ignored devices still appear after being added to the ignore list
2. **Recent Devices** — ignored devices appear in the live device feed
3. **Appearances sparkline** — "Device Activity — Last 24 Hours" chart shows no data points
4. **Active (5 min) = 0** — stat is always zero regardless of sensor activity
5. **Add Selected to Baseline returns 0** — "Added 0 device(s)" flash even when devices are selected

---

## Root Cause Analysis

### Bugs 1, 2, 5 — MAC Case Sensitivity
- `get_baseline_macs()` returns **uppercase** MACs (e.g. `"AA:BB:CC:DD:EE:FF"`)
- Kismet stores MACs in the DB as **lowercase** (e.g. `"aa:bb:cc:dd:ee:ff"`)
- SQLite `NOT IN (...)` is **case-sensitive** by default
- Result: `"aa:bb:cc:dd:ee:ff" NOT IN ("AA:BB:CC:DD:EE:FF")` → TRUE → device not excluded
- Bug 5 chain: device is shown because filter fails → user adds it again → already stored as uppercase → `added = 0`

**Fix:** Use `func.upper(Device.mac).notin_(baseline_macs)` in all filter locations.

### Bug 3 — Sparkline Empty
- `api_sparkline()` queries `Appearance.timestamp >= now - 24h`
- If no Kismet sync has occurred recently, data is older than 24h → empty arrays → empty chart
- Chart.js renders a blank canvas with no "no data" message

**Fix:** Add graceful empty-state message in JS when `data.data.length === 0`.

### Bug 4 — Active (5 min) Always Zero
- `Device.last_seen` is set from the Kismet file's device timestamp (not ingestion time)
- If the Pi hasn't synced a fresh Kismet file recently, no device will have `last_seen` within 5 min
- Window of 5 minutes is too narrow relative to potential sync delays

**Fix:** Expand window to `TIMING.time_windows.recent` from config (default 5 min), and fall back to a minimum of `check_interval * 2` seconds to account for ingestion lag. Label updated to show actual window used.

### Additional Hardening — Empty JSON in `_read_ignore_list`
- `maclist.json` in the repo is an empty file (not valid JSON)
- `_read_ignore_list()` lacks try/except around `json.load()` → would crash with `JSONDecodeError` on first use if mounted empty
- **Fix:** Add `try/except (json.JSONDecodeError, OSError)` to `_read_ignore_list`

---

## Files Changed
- `web/routes/dashboard.py` — case-insensitive MAC filter, wider active window
- `web/routes/settings.py` — `_read_ignore_list` error handling
- `web/templates/dashboard.html` — sparkline empty-state, dynamic active label

---

## Tasks

- [x] Identify root causes (MAC case sensitivity, sync delay, sparkline empty arrays)
- [x] Fix `dashboard.py` MAC filter to use `func.upper()`
- [x] Fix `dashboard.py` active window using config timing
- [x] Fix `settings.py` `_read_ignore_list` JSON error handling
- [x] Fix `dashboard.html` sparkline empty-state JS
- [ ] Deploy to NAS

---

## Architecture Decisions
- **No DB migration needed** — existing MACs will be re-matched via SQL `upper()` function
- **No schema change** — MACs stay as-is in DB; comparison normalised at query time
- **Config-driven active window** — respects `timing.time_windows.recent` from `config.json`
