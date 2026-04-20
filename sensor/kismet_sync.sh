#!/usr/bin/env bash
# CYT-NG — Sync .kismet files from RPi to Synology NAS via SMB mount
# Called by cyt-kismet-sync.timer (systemd) or manually
set -euo pipefail

KISMET_LOG_DIR="${KISMET_LOG_DIR:-/home/kismet/kismet_logs}"
NAS_MOUNT="${NAS_MOUNT:-/mnt/nas_kismet}"
HOSTNAME="$(hostname)"
LOG_TAG="cyt-sync"

log() { logger -t "$LOG_TAG" "$1"; echo "$(date '+%Y-%m-%d %H:%M:%S') $1"; }

# Verify NAS mount
if ! mountpoint -q "$NAS_MOUNT"; then
    log "ERROR: $NAS_MOUNT not mounted — attempting mount..."
    mount "$NAS_MOUNT" || { log "FATAL: mount failed"; exit 1; }
fi

# Create sensor subdirectory on NAS (one per RPi hostname)
DEST_DIR="${NAS_MOUNT}/${HOSTNAME}"
mkdir -p "$DEST_DIR"

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

# Write health-check timestamp
echo "$(date -Iseconds)" > "${DEST_DIR}/.last_sync"
