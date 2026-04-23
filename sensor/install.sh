#!/usr/bin/env bash
# CYT-NG Kismet Sensor — RPi Installation Script
# Run as root: sudo bash install.sh
set -euo pipefail

KISMET_USER="${KISMET_USER:-kismet}"
SYNC_INTERVAL="${SYNC_INTERVAL:-5}"   # minutes
NAS_SHARE="${NAS_SHARE:-//nas/kismet_data}"
NAS_MOUNT="/mnt/nas_kismet"
KISMET_LOG_DIR="/home/${KISMET_USER}/kismet_logs"
CREDS_FILE="/etc/cyt-sensor/smb_credentials"

echo "=== CYT-NG Sensor Installer ==="
echo "Target: Raspberry Pi with Kismet"
echo ""

# ---- Prerequisites ----
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Run as root (sudo bash install.sh)"
    exit 1
fi

# ---- Install packages ----
echo "[1/6] Installing packages..."
apt-get update
apt-get install -y kismet cifs-utils

# ---- Create Kismet user if needed ----
if ! id "$KISMET_USER" &>/dev/null; then
    echo "[2/6] Creating kismet user..."
    useradd -m -g kismet "$KISMET_USER"
else
    echo "[2/6] User $KISMET_USER exists, ensuring group membership..."
    usermod -aG kismet "$KISMET_USER"
fi

mkdir -p "$KISMET_LOG_DIR"
chown "$KISMET_USER:$KISMET_USER" "$KISMET_LOG_DIR"

# ---- SMB credentials ----
echo "[3/6] Configuring NAS SMB credentials..."
mkdir -p /etc/cyt-sensor
if [ ! -f "$CREDS_FILE" ]; then
    read -rp "NAS SMB username: " SMB_USER
    read -rsp "NAS SMB password: " SMB_PASS
    echo ""
    cat > "$CREDS_FILE" <<EOF
username=${SMB_USER}
password=${SMB_PASS}
EOF
    chmod 600 "$CREDS_FILE"
    echo "Credentials saved to $CREDS_FILE"
else
    echo "Credentials file already exists at $CREDS_FILE"
fi

# ---- Mount point ----
echo "[4/6] Setting up NAS mount..."
mkdir -p "$NAS_MOUNT"

# Add fstab entry if not present
FSTAB_LINE="${NAS_SHARE} ${NAS_MOUNT} cifs credentials=${CREDS_FILE},uid=${KISMET_USER},gid=${KISMET_USER},iocharset=utf8,vers=3.0,_netdev,nofail 0 0"
if ! grep -qF "$NAS_SHARE" /etc/fstab; then
    echo "$FSTAB_LINE" >> /etc/fstab
    echo "Added fstab entry"
else
    echo "fstab entry already exists"
fi

mount -a || echo "WARNING: mount failed — check NAS connectivity and credentials"

# ---- Install sync script ----
echo "[5/6] Installing sync script and systemd units..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SCRIPT_DIR/kismet_sync.sh" /usr/local/bin/cyt-kismet-sync
chmod +x /usr/local/bin/cyt-kismet-sync

# Write systemd service
cat > /etc/systemd/system/cyt-kismet-sync.service <<EOF
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
EOF

# Write systemd timer
cat > /etc/systemd/system/cyt-kismet-sync.timer <<EOF
[Unit]
Description=CYT-NG Kismet sync timer (every ${SYNC_INTERVAL} min)

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
