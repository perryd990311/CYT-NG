# CYT-NG Feature Plan

## Completed
- [x] Kismet `.kismet` file ingestion (glob recursive fix)
- [x] Dashboard stat cards, sparkline chart, 24h summary, top persistent devices
- [x] Color dot + friendly name visual identifiers on device list
- [x] SSID color tags on device list
- [x] Device quick-view popup (click row → popup with enrichment data)
- [x] Popup shared across Devices + Dashboard pages
- [x] Popup enrichment: appearances, time span, sensors, signal, fingerprint, baseline, notes
- [x] Fixed-top popup positioning
- [x] datetime naive/aware bug fix across all routes

## In Progress
- [ ] Sensor data freshness — rsync frequency / active file re-sync

## Next Up

### Sortable Device Table
- Click column headers to sort by: Device (MAC), Type, Manufacturer, SSIDs count, First Seen, Last Seen
- Visual sort indicator (arrow up/down on active column)
- Client-side sort for current page; server-side sort across all pages
- Remember last sort preference (localStorage)
- Works on both Devices page and Dashboard recent devices list

### Data Pipeline Improvements
- Improve rsync frequency for active Kismet files (currently stale 15h+)
- Consider live-tailing or inotify-based sync trigger
- Show last sync time in status bar alongside data age

## Backlog
- [ ] Persistent ignore lists across container rebuilds (mount `ignore_lists/` as a Docker volume or store in the SQLite DB so edits survive `docker compose build`)
- [ ] Ignore list integration into fingerprinting
- [ ] Device detail page enrichment (match popup data)
- [ ] Export devices to CSV/JSON
- [ ] Alert notifications (SocketIO push for new suspicious devices)
- [ ] Multi-sensor map view (if GPS data available)
- [ ] Bulk device actions (mark as baseline, add notes)
- [ ] Analysis page improvements (scheduling, history)
- [ ] Dark/light theme toggle
