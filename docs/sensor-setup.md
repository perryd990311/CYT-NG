# Sensor Setup Guide

Each CYT-NG sensor is a Raspberry Pi running Kismet with a monitor-mode Wi-Fi adapter. Sensors capture probe requests and sync data to the NAS automatically.

## Hardware

### Recommended Components

| Component | Recommendation | Notes |
|-----------|---------------|-------|
| **Board** | Raspberry Pi 4 Model B (2 GB+) | Pi 3B+ also works |
| **Wi-Fi Adapter** | Alfa AWUS036ACM | Dual-band, excellent monitor mode support |
| **SD Card** | 32 GB+ Class 10 / A1 | Kismet logs can grow quickly |

### Alternative Wi-Fi Adapters

Any adapter with **monitor mode** support works. Verified options:

- **Alfa AWUS036ACM** — MediaTek MT7612U, 2.4/5 GHz (recommended)
- **Alfa AWUS036ACHM** — MediaTek MT7610U, 2.4/5 GHz, smaller form factor
- **Panda PAU09** — Ralink RT5572, 2.4/5 GHz, good budget option

> The built-in Pi Wi-Fi chip does **not** support monitor mode. You must use an external USB adapter.

## Software Setup

### Option A: Automated Provisioning (Recommended)

CYT-NG can provision sensors directly from the web UI. This is the fastest path:

1. Flash a fresh **Raspberry Pi OS Lite (64-bit)** to the SD card
2. Enable SSH (add an empty `ssh` file to the boot partition)
3. Configure Wi-Fi for initial connectivity (or use Ethernet)
4. Boot the Pi and note its IP address
5. In CYT-NG, go to **Sensors → Add Sensor**
6. Fill in the connection details:
   - **Name**: A friendly label (e.g., "Living Room")
   - **Hostname/IP**: The Pi's address
   - **SSH User**: `pi` (or your configured user)
   - **Wi-Fi Interface**: `wlan1` (the external adapter — `wlan0` is usually built-in)
   - **SMB Share Path**: The NAS share for Kismet data
7. Click **Provision / Reinstall**
8. Enter SSH credentials and NAS credentials when prompted (used once, never stored)

The provisioner runs 11 automated steps:

| Step | Action |
|------|--------|
| 1 | TCP port reachability check |
| 2 | SSH authentication |
| 3 | Sudo privilege verification |
| 4 | `apt-get update` |
| 5 | Install Kismet from official repos |
| 6 | Create `kismet` system user |
| 7 | Create log directory (`/kismet/`) |
| 8 | Install sync script |
| 9 | Mount NAS share (writes `/etc/cyt-nas.creds`, chmod 600) |
| 10 | Enable systemd sync timer |
| 11 | Detect and report Kismet version |

Progress streams live to the browser via WebSocket.

### Option B: Manual Setup

If you prefer to set up sensors manually:

#### 1. Install Kismet

```bash
# Add Kismet repo
wget -O - https://www.kismetwireless.net/repos/kismet-release.gpg.key | \
  sudo gpg --dearmor -o /usr/share/keyrings/kismet-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/kismet-archive-keyring.gpg] \
  https://www.kismetwireless.net/repos/apt/release/$(lsb_release -cs) \
  $(lsb_release -cs) main" | \
  sudo tee /etc/apt/sources.list.d/kismet.list

sudo apt update
sudo apt install -y kismet
```

#### 2. Configure Kismet

Edit `/etc/kismet/kismet.conf` or create an override in `/etc/kismet/kismet_site.conf`:

```
# Capture source — your monitor-mode adapter
source=wlan1:name=wifi_sensor

# Log only what CYT-NG needs
log_types=kismet

# Rotate logs to prevent disk fill
log_prefix=/kismet/
```

#### 3. Set Up Data Sync

Install the sync script from the repo:

```bash
sudo cp sensor/kismet_sync.sh /usr/local/bin/cyt-kismet-sync
sudo chmod +x /usr/local/bin/cyt-kismet-sync
```

Create NAS credentials:

```bash
sudo tee /etc/cyt-nas.creds << EOF
username=sensor_user
password=your_smb_password
EOF
sudo chmod 600 /etc/cyt-nas.creds
```

Mount the NAS share and set up a systemd timer for periodic sync.

#### 4. Enable Kismet as a Service

```bash
sudo systemctl enable kismet
sudo systemctl start kismet
```

## Verifying Sensor Operation

After setup, check the sensor from the CYT-NG web UI:

1. **Sensors** tab shows online/offline status
2. **Dashboard** shows sensor count and sighting activity
3. **Settings → Scheduled Tasks** shows the ingestion job picking up new files

You can also verify on the Pi itself:

```bash
# Check Kismet is running
systemctl status kismet

# Check sync timer
systemctl list-timers | grep cyt

# Check for .kismet files
ls -lh /kismet/*.kismet

# Check NAS mount
ls /mnt/nas_kismet/
```

## Multiple Sensors

CYT-NG supports unlimited sensors. Each syncs to its own subdirectory on the NAS:

```
kismet_data/
  ├── sensor-living-room/
  ├── sensor-garage/
  ├── sensor-office/
  └── sensor-car/
```

The analysis engine correlates devices across all sensors automatically. The **Statistics** page shows per-sensor coverage and multi-sensor overlap (devices seen by 2+ sensors).

## Kismet Log Rotation

Kismet files grow over time. The provisioner installs a rotation timer that:

1. Sends `SIGHUP` to Kismet (starts a new log file)
2. Triggers a sync to the NAS
3. Optionally cleans old local files

This keeps disk usage manageable on the Pi's SD card.
