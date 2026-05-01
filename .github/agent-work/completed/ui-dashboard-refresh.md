# Feature: Dashboard UI Refresh (Mockup → Production)

**Status:** Active  
**Source:** `web/mockup/dashboard.html`

## Changes

### Template-only (ready now)
- [x] Top Persistent: Add "X appearances" sub-text below MAC
- [x] Top Persistent: Replace count badge with High/Medium/Low severity badge
- [x] Activity chart: Change sparkline line chart → bar chart (hourly buckets)
- [x] Recent Devices header: Add "View all →" link

### Needs backend
- [ ] Sensor Status card: Show per-sensor name + sighting count (requires `sensors` list with counts passed from `dashboard.py index()`)
- [ ] Recent Devices: Compact dashboard-specific view (MAC, Manufacturer, Signal, Appearances, Last Seen) vs full device_list.html partial

## Files
- `web/templates/dashboard.html`
- `web/routes/dashboard.py` (for sensor sighting counts)
