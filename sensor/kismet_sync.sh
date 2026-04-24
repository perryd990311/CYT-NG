#!/usr/bin/env bash
# CYT-NG — Sync .kismet files from RPi to Synology NAS via SMB mount
# Called by cyt-kismet-sync.timer (systemd) or manually
set -euo pipefail

KISMET_LOG_DIR="${KISMET_LOG_DIR:-/kismet/}"
NAS_MOUNT="${NAS_MOUNT:-/mnt/nas_kismet}"
HOSTNAME="$(hostname)"
LOG_TAG="cyt-sync"

log() { logger -t "$LOG_TAG" "$1"; echo "$(date '+%Y-%m-%d %H:%M:%S') $1"; }

# ── Kismet health check ────────────────────────────────────────────────────
# Sensor may be online but Kismet stopped (crash, OOM, bad config reload).
# Attempt restart and log — probe data gap is surfaced via .last_sync delta.
if ! systemctl is-active --quiet kismet 2>/dev/null; then
    log "WARNING: Kismet is not running — attempting restart"
    if systemctl start kismet 2>/dev/null; then
        sleep 3
        if systemctl is-active --quiet kismet 2>/dev/null; then
            log "INFO: Kismet restarted successfully"
        else
            log "ERROR: Kismet failed to restart — check: journalctl -u kismet -n 20"
        fi
    else
        log "ERROR: systemctl start kismet failed"
    fi
fi

# Verify NAS mount
if ! mountpoint -q "$NAS_MOUNT"; then
    log "ERROR: $NAS_MOUNT not mounted — attempting mount..."
    mount "$NAS_MOUNT" || { log "FATAL: mount failed"; exit 1; }
fi

# Create sensor subdirectory on NAS (one per RPi hostname)
# 755 so the CYT web container (different UID) can read .kismet files and .last_sync
DEST_DIR="${NAS_MOUNT}/${HOSTNAME}"
mkdir -p "$DEST_DIR"
chmod 755 "$DEST_DIR"

# Sync only .kismet files — rsync handles partial/incremental
SYNC_COUNT=0
for f in "${KISMET_LOG_DIR}"/*.kismet; do
    [ -f "$f" ] || continue

    BASENAME="$(basename "$f")"
    DEST="${DEST_DIR}/${BASENAME}"

    # Only copy if source is newer or different size
    if [ ! -f "$DEST" ] || [ "$f" -nt "$DEST" ]; then
        cp -p "$f" "$DEST"
        SYNC_COUNT=$((SYNC_COUNT + 1))
        log "Synced: $BASENAME → $DEST_DIR/"
    fi
done

if [ "$SYNC_COUNT" -eq 0 ]; then
    log "No new files to sync"
else
    log "Synced $SYNC_COUNT file(s) to NAS"
fi

# ── Purge old .kismet files from the Pi ─────────────────────────────────
# Keep the most recent files to avoid deleting the active log.
# Older files have already been synced to the NAS and ingested.
KEEP_COUNT="${KEEP_LOCAL_FILES:-2}"
FILE_COUNT=$(find "${KISMET_LOG_DIR}" -maxdepth 1 -name "*.kismet" -type f | wc -l)
if [ "$FILE_COUNT" -gt "$KEEP_COUNT" ]; then
    PURGE_COUNT=$((FILE_COUNT - KEEP_COUNT))
    # Sort by modification time, oldest first — delete all but the newest $KEEP_COUNT
    find "${KISMET_LOG_DIR}" -maxdepth 1 -name "*.kismet" -type f -printf '%T@ %p\n' \
        | sort -n \
        | head -n "$PURGE_COUNT" \
        | cut -d' ' -f2- \
        | while IFS= read -r old_file; do
            rm -f "$old_file"
            log "Purged old local log: $(basename "$old_file")"
        done
    log "Purged $PURGE_COUNT old .kismet file(s) from Pi (kept newest $KEEP_COUNT)"
fi

# Write health-check timestamp
echo "$(date -Iseconds)" > "${DEST_DIR}/.last_sync"
