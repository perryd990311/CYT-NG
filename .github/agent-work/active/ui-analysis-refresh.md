# Feature: Analysis UI Refresh (Mockup → Production)

**Status:** Active  
**Source:** `web/mockup/analysis.html`

## Changes

### Template-only (ready now)
- [x] Runs table: Accent border-left on the latest run row
- [x] Trigger badge: `manual` = blue, `scheduled` = muted
- [x] Persistent count: Badge colored red if >0, green if 0
- [x] Status badge: Soft opacity style (bg-opacity-25) matching mockup
- [x] Table headers: Align Devices (right), Persistent/Status (center)
- [x] Card header: Add "Last 20 runs" note

### Needs backend / separate page work
- [ ] Inline run results: Expand run row to show stat cards + fingerprint clusters inline instead of navigating to `/results/N`
- [ ] "Run Analysis" loading state: Show spinner while run is executing

## Files
- `web/templates/analysis.html`
