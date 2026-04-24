#!/usr/bin/env bash
# CYT-NG Kismet Sensor — RPi Installation Script
#
# Usage:
#   sudo bash install.sh [--reinstall] [--unattended]
#
# Environment variables (all optional except NAS_SHARE):
#   NAS_SHARE      SMB share UNC path   e.g. //172.20.0.250/kismet_data  (REQUIRED)
#   NAS_USER       SMB username         prompts interactively if not set
#   NAS_PASS       SMB password         prompts interactively if not set
#   WIFI_IFACE     Kismet capture iface e.g. wlan1  (default: wlan1)
#   SYNC_INTERVAL  Sync cadence (min)   default: 5
#   KISMET_USER    System user          default: kismet
#
# Flags:
#   --reinstall    Overwrite existing install (creds, units, sync script)
#   --unattended   Fail immediately if NAS_USER or NAS_PASS are not set
#                  (safe for scripted/SSH-driven deployment)
#
# Remote deployment: see sensor/deploy.sh
set -euo pipefail

# ── Config ─────────────────────────────────────────────────────────────────
KISMET_USER="${KISMET_USER:-kismet}"
WIFI_IFACE="${WIFI_IFACE:-wlan1}"
SYNC_INTERVAL="${SYNC_INTERVAL:-5}"
NAS_SHARE="${NAS_SHARE:-}"
NAS_MOUNT="/mnt/nas_kismet"
KISMET_LOG_DIR="/home/${KISMET_USER}/kismet_logs"
CREDS_FILE="/etc/cyt-nas.creds"
REINSTALL=0
UNATTENDED=0

for arg in "$@"; do
    case "$arg" in
        --reinstall)   REINSTALL=1 ;;
        --unattended)  UNATTENDED=1 ;;
    esac
done

# ── Helpers ─────────────────────────────────────────────────────────────────
step() { echo ""; echo "[$1/7] $2"; }
ok()   { echo "  ✓ $1"; }
skip() { echo "  – $1 (skipped)"; }
warn() { echo "  ! WARNING: $1"; }
die()  { echo ""; echo "ERROR: $1" >&2; exit 1; }

echo "=================================================="
echo "  CYT-NG Sensor Installer"
echo "  Host: $(hostname)  |  Date: $(date '+%Y-%m-%d %H:%M')"
echo "=================================================="
echo ""

# ── Prerequisites ────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || die "Run as root: sudo bash install.sh"

[ -n "$NAS_SHARE" ] || die "NAS_SHARE is not set.
  Manual:      NAS_SHARE=//172.20.0.250/kismet_data sudo bash install.sh
  Unattended:  NAS_SHARE=... NAS_USER=... NAS_PASS=... sudo bash install.sh --unattended"

if [ "$UNATTENDED" -eq 1 ]; then
    [ -n "${NAS_USER:-}" ] || die "--unattended requires NAS_USER to be set"
    [ -n "${NAS_PASS:-}" ] || die "--unattended requires NAS_PASS to be set"
fi

# ── Already-installed guard ───────────────────────────────────────────────
if systemctl is-active --quiet cyt-kismet-sync.timer 2>/dev/null && [ "$REINSTALL" -eq 0 ]; then
    echo "WARNING: cyt-kismet-sync.timer is already active."
    echo "  Run with --reinstall to overwrite: sudo bash install.sh --reinstall"
    exit 1
fi
[ "$REINSTALL" -eq 1 ] && echo "[*] --reinstall: existing components will be overwritten."

# ── [1/7] Install packages ────────────────────────────────────────────────
step 1 "Installing packages"
DEBIAN_FRONTEND=noninteractive apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y kismet cifs-utils rsync
ok "kismet, cifs-utils, rsync installed"

# ── [2/7] Create kismet group + user ─────────────────────────────────────
step 2 "Creating kismet system user"
if ! getent group kismet &>/dev/null; then
    groupadd -r kismet
    ok "kismet group created"
else
    skip "kismet group already exists"
fi

if ! id "$KISMET_USER" &>/dev/null; then
    useradd -r -m -g kismet "$KISMET_USER"
    ok "kismet user created"
else
    skip "kismet user already exists"
fi

mkdir -p "$KISMET_LOG_DIR"
chown "$KISMET_USER:kismet" "$KISMET_LOG_DIR"
chmod 750 "$KISMET_LOG_DIR"
ok "log dir: $KISMET_LOG_DIR"

# ── [3/7] NAS SMB credentials ─────────────────────────────────────────────
step 3 "Configuring NAS SMB credentials"
if [ -f "$CREDS_FILE" ] && [ "$REINSTALL" -eq 0 ]; then
    skip "credentials file already exists at $CREDS_FILE"
else
    # Prompt only in interactive mode
    if [ -z "${NAS_USER:-}" ]; then
        read -rp "  NAS SMB username: " NAS_USER
    fi
    if [ -z "${NAS_PASS:-}" ]; then
        read -rsp "  NAS SMB password: " NAS_PASS
        echo ""
    fi
    printf 'username=%s\npassword=%s\n' "$NAS_USER" "$NAS_PASS" > "$CREDS_FILE"
    chmod 600 "$CREDS_FILE"
    chown root:root "$CREDS_FILE"
    ok "credentials written to $CREDS_FILE (mode 600, root:root)"
fi

# ── [4/7] fstab + mount ───────────────────────────────────────────────────
step 4 "Configuring NAS mount"
mkdir -p "$NAS_MOUNT"

# 4a. fstab entry — check it exists and references the right share + creds file
FSTAB_LINE=$(grep -F "$NAS_SHARE" /etc/fstab 2>/dev/null || true)
if [ -n "$FSTAB_LINE" ]; then
    # Validate it points to our mount point and credentials file
    if echo "$FSTAB_LINE" | grep -qF "$NAS_MOUNT" && echo "$FSTAB_LINE" | grep -qF "credentials=$CREDS_FILE"; then
        skip "fstab entry already present and correct"
    else
        warn "fstab has an entry for $NAS_SHARE but it looks wrong:"
        warn "  $FSTAB_LINE"
        warn "  Expected mount point: $NAS_MOUNT, credentials=$CREDS_FILE"
        warn "  Edit /etc/fstab manually to fix, then re-run with --reinstall"
    fi
else
    # Use printf to write the line — avoids shell expansion/quoting hazards
    printf '%s %s cifs credentials=%s,iocharset=utf8,vers=3.0,nofail,_netdev 0 0\n' \
        "$NAS_SHARE" "$NAS_MOUNT" "$CREDS_FILE" >> /etc/fstab
    ok "fstab entry added"
fi

# 4b. Verify credentials file is referenced in fstab (sanity — catches manual edits)
if ! grep -qF "credentials=$CREDS_FILE" /etc/fstab 2>/dev/null; then
    warn "credentials=$CREDS_FILE not found in /etc/fstab — mount may fail after reboot"
fi

# 4c. NAS host reachability before attempting mount
NAS_HOST=$(echo "$NAS_SHARE" | sed 's|^//||;s|/.*||')
if ping -c1 -W2 "$NAS_HOST" &>/dev/null; then
    ok "NAS host $NAS_HOST is reachable"
else
    warn "NAS host $NAS_HOST did not respond to ping — proceeding, but mount may fail"
fi

# 4d. Mount (or verify already mounted and live)
MOUNT_LIVE=0
if mountpoint -q "$NAS_MOUNT"; then
    # mountpoint -q only checks the kernel table — verify the mount is actually responsive
    if timeout 5 ls "$NAS_MOUNT" &>/dev/null; then
        ok "$NAS_MOUNT already mounted and responsive"
        MOUNT_LIVE=1
    else
        warn "$NAS_MOUNT is in the mount table but not responsive (stale mount) — remounting"
        umount -l "$NAS_MOUNT" 2>/dev/null || true
    fi
fi

if [ "$MOUNT_LIVE" -eq 0 ]; then
    MOUNT_ERR=$(mount "$NAS_MOUNT" 2>&1) && MOUNT_RC=0 || MOUNT_RC=$?
    if [ "$MOUNT_RC" -eq 0 ]; then
        ok "$NAS_MOUNT mounted"
    else
        warn "mount failed (exit $MOUNT_RC): $MOUNT_ERR"
        warn "Will retry on next boot via _netdev — check NAS share path and credentials"
    fi
fi

# 4e. Post-mount readability check
if mountpoint -q "$NAS_MOUNT"; then
    if [ -r "$NAS_MOUNT" ]; then
        ok "$NAS_MOUNT is readable"
    else
        warn "$NAS_MOUNT is mounted but not readable — check NAS share permissions"
    fi
    # Verify we can write (sync script needs to create subdirs and .last_sync)
    TEST_FILE="$NAS_MOUNT/.cyt_write_test_$$"
    if touch "$TEST_FILE" 2>/dev/null; then
        rm -f "$TEST_FILE"
        ok "$NAS_MOUNT is writable"
    else
        warn "$NAS_MOUNT is mounted but not writable — sync will fail; check NAS share permissions"
    fi
fi

# ── [5/7] Install sync script + systemd units ─────────────────────────────
step 5 "Installing sync script and systemd units"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$SCRIPT_DIR/kismet_sync.sh" ]; then
    die "kismet_sync.sh not found at $SCRIPT_DIR/kismet_sync.sh"
fi

install -o root -g root -m 755 "$SCRIPT_DIR/kismet_sync.sh" /usr/local/bin/cyt-kismet-sync
ok "sync script installed (root:root 755)"

cat > /etc/systemd/system/cyt-kismet-sync.service <<UNIT
[Unit]
Description=CYT-NG Kismet data sync to NAS
After=network-online.target remote-fs.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/cyt-kismet-sync
User=root
Environment=KISMET_LOG_DIR=${KISMET_LOG_DIR}
Environment=NAS_MOUNT=${NAS_MOUNT}

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/cyt-kismet-sync.timer <<UNIT
[Unit]
Description=CYT-NG Kismet sync timer (every ${SYNC_INTERVAL} min)

[Timer]
OnBootSec=2min
OnUnitActiveSec=${SYNC_INTERVAL}min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

chmod 644 /etc/systemd/system/cyt-kismet-sync.{service,timer}
systemctl daemon-reload
systemctl enable --now cyt-kismet-sync.timer
ok "cyt-kismet-sync.timer enabled and started"

# ── [6/7] Configure Kismet log directory + rotation ──────────────────────
step 6 "Configuring Kismet"
KISMET_CONF="/etc/kismet/kismet.conf"
KISMET_SITE="/etc/kismet/kismet_site.conf"

# Deploy CYT site config (log rotation, log types, flush rate)
if [ -f "$SCRIPT_DIR/kismet_site.conf" ]; then
    install -o root -g root -m 644 "$SCRIPT_DIR/kismet_site.conf" "$KISMET_SITE"
    ok "kismet_site.conf deployed (6h rotation, kismet-only logging)"
else
    warn "kismet_site.conf not found at $SCRIPT_DIR — log rotation not configured"
fi

if [ -f "$KISMET_CONF" ]; then
    if grep -q "^log_prefix=" "$KISMET_CONF" 2>/dev/null; then
        # Update existing log_prefix line
        sed -i "s|^log_prefix=.*|log_prefix=${KISMET_LOG_DIR}/kismet|" "$KISMET_CONF"
        ok "log_prefix updated in $KISMET_CONF"
    else
        echo "log_prefix=${KISMET_LOG_DIR}/kismet" >> "$KISMET_CONF"
        ok "log_prefix added to $KISMET_CONF"
    fi

    # Add Wi-Fi source if an interface is specified and not already present
    if [ -n "$WIFI_IFACE" ] && ! grep -q "^source=${WIFI_IFACE}" "$KISMET_CONF" 2>/dev/null; then
        echo "source=${WIFI_IFACE}:name=cyt-sensor" >> "$KISMET_CONF"
        ok "Wi-Fi source added: ${WIFI_IFACE}"
    else
        skip "Wi-Fi source already configured or WIFI_IFACE not set"
    fi
else
    warn "Kismet config not found at $KISMET_CONF — run kismet once to generate it"
fi

# Enable and start Kismet service
if systemctl is-active --quiet kismet 2>/dev/null; then
    skip "Kismet service already running"
elif [ -n "$WIFI_IFACE" ]; then
    # Interface configured — safe to start now
    systemctl enable --now kismet 2>/dev/null \
        && ok "Kismet service enabled and started" \
        || warn "Kismet failed to start — check: journalctl -u kismet -n 20"
else
    # No interface set — enable for boot only, start manually after configuring source=
    systemctl enable kismet 2>/dev/null \
        && ok "Kismet service enabled (start manually once Wi-Fi source is configured)" \
        || warn "Could not enable kismet service"
fi

# ── [7/7] Summary ─────────────────────────────────────────────────────────
step 7 "Installation complete"
echo ""
echo "  Sensor:       $(hostname)"
echo "  NAS share:    $NAS_SHARE → $NAS_MOUNT"
echo "  Kismet logs:  $KISMET_LOG_DIR"
echo "  Sync timer:   every ${SYNC_INTERVAL} minutes"
echo "  Wi-Fi iface:  ${WIFI_IFACE:-not configured}"
echo ""
echo "  Next steps:"
if [ -z "$WIFI_IFACE" ]; then
echo "    Edit /etc/kismet/kismet.conf — add:  source=wlanX:name=cyt-sensor"
echo "    sudo systemctl start kismet       # start capturing"
fi
echo "    systemctl status cyt-kismet-sync.timer"
echo "    journalctl -u cyt-kismet-sync -f  # watch sync logs"
echo ""


[Timer]
OnBootSec=2min
OnUnitActiveSec=${SYNC_INTERVAL}min
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now cyt-kismet-sync.timer

# ---- Kismet config hints ----
echo "[6/6] Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Configure Kismet Wi-Fi source in /etc/kismet/kismet.conf:"
echo "     source=wlan1:name=cyt-sensor"
echo "  2. Set log directory: log_prefix=${KISMET_LOG_DIR}"
echo "  3. Start Kismet: sudo systemctl enable --now kismet"
echo "  4. Verify sync: systemctl status cyt-kismet-sync.timer"
echo ""
echo "Sync will run every ${SYNC_INTERVAL} minutes to ${NAS_SHARE}"
