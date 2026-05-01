# Feature: Devices UI Refresh (Mockup → Production)

**Status:** Active  
**Source:** `web/mockup/devices.html`

## Changes

### Template + CSS (ready now)
- [x] Signal column: Color-coded dBm badge (excellent/good/fair/weak/poor) using `signal_raw` from enrichment
- [x] Baseline badge: Show `baseline` tag on MAC cell for ignored devices
- [x] Row-ignored: Dim rows for baseline devices (`opacity: 0.45`)
- [x] Row-suspicious: Red left-border on high-appearance non-baseline devices
- [x] CSS: Add `.signal-badge`, `.signal-excellent/good/fair/weak/poor`, `.baseline-badge`, `.row-ignored`, `.row-suspicious`

### Needs backend
- [ ] Appearances column: Show count in table (currently in popup only) — needs sort support
- [ ] Filter badge UI: Active filter chips with ×-to-clear (signal range, type, etc.)
- [ ] Pagination: Styled page numbers (currently prev/next only)

## Files
- `web/routes/devices.py` (add `signal_raw` to enrichment)
- `web/templates/partials/device_list.html`
- `web/static/css/style.css`
