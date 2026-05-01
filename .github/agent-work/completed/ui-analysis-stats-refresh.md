# Feature: Analysis Stats UI Refresh (Mockup → Production)

**Status:** Active  
**Source:** `web/mockup/analysis-stats.html`

## Changes

### Template + CSS (ready now)
- [x] Right sidebar stat cards: Compact `.stat-card-sm` style (inline label + value, 0.75rem padding, 1.35rem font)
- [x] Fingerprint clusters: Replace inline styles with `.cluster-item`, `.cluster-id`, `.cluster-count` CSS classes
- [x] Cluster SSID tags: Use `.ssid-tag` class instead of full inline style

### Needs backend
- [ ] Top Probed SSIDs table: Add First Seen / Last Seen columns (requires route to return these per SSID)
- [ ] Dwell Time Distribution chart: Currently only shows data from Appearances but needs min/max per device-visit calculated

## Files
- `web/templates/analysis_stats.html`
- `web/static/css/style.css`
