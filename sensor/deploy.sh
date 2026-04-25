#!/usr/bin/env bash
# CYT-NG — Remote sensor deployment wrapper
#
# Copies install.sh + kismet_sync.sh to a remote RPi and runs install.sh
# over SSH. All configuration is passed as environment variables.
#
# Usage:
#   bash deploy.sh [options] USER@HOST
#
# Required:
#   USER@HOST      SSH target, e.g.  pi@raspberrypi  or  kismet@sensor-01
#   NAS_SHARE      SMB path,  e.g.  //YOUR_NAS_IP/kismet_data
#   NAS_USER       NAS SMB username
#   NAS_PASS       NAS SMB password
#
# Optional env vars (forwarded to install.sh):
#   WIFI_IFACE     Wi-Fi capture interface  (default: wlan1)
#   SYNC_INTERVAL  Sync cadence in minutes  (default: 5)
#   KISMET_USER    System user on sensor    (default: kismet)
#   SSH_KEY        Path to SSH private key  (default: ~/.ssh/id_ed25519)
#   SSH_PORT       SSH port                 (default: 22)
#
# Flags:
#   --reinstall    Pass --reinstall to install.sh
#   --dry-run      Show what would be run; do not connect
#
# Examples:
#   NAS_SHARE=//YOUR_NAS_IP/kismet_data NAS_USER=sensor NAS_PASS=s3cr3t \
#     bash deploy.sh pi@SENSOR_IP
#
#   NAS_SHARE=//YOUR_NAS_IP/kismet_data NAS_USER=sensor NAS_PASS=s3cr3t \
#     WIFI_IFACE=wlan1 bash deploy.sh --reinstall pi@SENSOR_IP
set -euo pipefail

# ── Parse args ──────────────────────────────────────────────────────────────
REINSTALL_FLAG=""
DRY_RUN=0
TARGET=""

for arg in "$@"; do
    case "$arg" in
        --reinstall) REINSTALL_FLAG="--reinstall" ;;
        --dry-run)   DRY_RUN=1 ;;
        *)           TARGET="$arg" ;;
    esac
done

# ── Validate ─────────────────────────────────────────────────────────────────
die() { echo "ERROR: $1" >&2; exit 1; }

[ -n "$TARGET" ]            || die "Usage: bash deploy.sh [--reinstall] [--dry-run] USER@HOST"
[ -n "${NAS_SHARE:-}" ]     || die "NAS_SHARE is not set"
[ -n "${NAS_USER:-}" ]      || die "NAS_USER is not set"
[ -n "${NAS_PASS:-}" ]      || die "NAS_PASS is not set"

SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
SSH_PORT="${SSH_PORT:-22}"
WIFI_IFACE="${WIFI_IFACE:-wlan1}"
SYNC_INTERVAL="${SYNC_INTERVAL:-5}"
KISMET_USER="${KISMET_USER:-kismet}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_SH="$SCRIPT_DIR/install.sh"
SYNC_SH="$SCRIPT_DIR/kismet_sync.sh"

[ -f "$INSTALL_SH" ] || die "install.sh not found at $INSTALL_SH"
[ -f "$SYNC_SH" ]    || die "kismet_sync.sh not found at $SYNC_SH"
[ -f "$SSH_KEY" ]    || die "SSH key not found at $SSH_KEY"

SSH_OPTS="-i $SSH_KEY -p $SSH_PORT -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"

echo "=================================================="
echo "  CYT-NG Remote Sensor Deployment"
echo "  Target:       $TARGET"
echo "  NAS share:    $NAS_SHARE"
echo "  Wi-Fi iface:  $WIFI_IFACE"
echo "  Sync interval: ${SYNC_INTERVAL} min"
[ -n "$REINSTALL_FLAG" ] && echo "  Mode:         REINSTALL"
[ "$DRY_RUN" -eq 1 ]     && echo "  *** DRY RUN — no changes will be made ***"
echo "=================================================="
echo ""

[ "$DRY_RUN" -eq 1 ] && { echo "Dry run complete."; exit 0; }

# ── Copy files to sensor ──────────────────────────────────────────────────
echo "[1/3] Copying files to $TARGET..."
REMOTE_DIR="/tmp/cyt-deploy-$$"
# shellcheck disable=SC2086
ssh $SSH_OPTS "$TARGET" "mkdir -p $REMOTE_DIR"
# shellcheck disable=SC2086
scp $SSH_OPTS "$INSTALL_SH" "$SYNC_SH" "${TARGET}:${REMOTE_DIR}/"
# Strip CRLF in case files were checked out on Windows
# shellcheck disable=SC2086
ssh $SSH_OPTS "$TARGET" "sed -i 's/\r//' ${REMOTE_DIR}/install.sh ${REMOTE_DIR}/kismet_sync.sh"
echo "  ✓ Files copied to $REMOTE_DIR"

# ── Run install.sh on remote ──────────────────────────────────────────────
echo "[2/3] Running install.sh on $TARGET..."
# shellcheck disable=SC2086
ssh $SSH_OPTS "$TARGET" \
    "NAS_SHARE='${NAS_SHARE}' NAS_USER='${NAS_USER}' NAS_PASS='${NAS_PASS}' \
     WIFI_IFACE='${WIFI_IFACE}' SYNC_INTERVAL='${SYNC_INTERVAL}' KISMET_USER='${KISMET_USER}' \
     sudo --preserve-env=NAS_SHARE,NAS_USER,NAS_PASS,WIFI_IFACE,SYNC_INTERVAL,KISMET_USER \
     bash ${REMOTE_DIR}/install.sh --unattended ${REINSTALL_FLAG}"

# ── Cleanup ───────────────────────────────────────────────────────────────
echo "[3/3] Cleaning up temp files..."
# shellcheck disable=SC2086
ssh $SSH_OPTS "$TARGET" "rm -rf $REMOTE_DIR"
echo "  ✓ Done"
echo ""
echo "Deployment complete → $TARGET"
