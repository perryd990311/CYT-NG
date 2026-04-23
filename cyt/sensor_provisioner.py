"""Remote sensor provisioning via SSH (Paramiko).

Connects to a Raspberry Pi, installs Kismet + sync components,
and streams step-by-step progress via SocketIO events.

Step design:
  - CRITICAL steps (connectivity, sudo_check, install_kismet): abort on failure
  - OPTIONAL steps (create_log_dir, etc.): log error but continue
  - Each step emits: running → ok | error | skipped
"""
import logging
import os
import socket
import time

import paramiko

logger = logging.getLogger(__name__)

# (step_id, label, is_critical, shell_command_or_None)
# None command = handled by a dedicated function
PROVISION_STEPS = [
    ("port_check",          "Check network reachability",       True,  None),
    ("connectivity",        "SSH authentication",               True,  None),
    ("sudo_check",          "Verify sudo access",               True,  "sudo -n true 2>/dev/null || sudo true"),
    ("update_packages",     "Update package lists",             True,  "sudo apt-get update -qq 2>&1 | tail -3"),
    ("install_kismet",      "Install Kismet & cifs-utils",      True,
        "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y kismet cifs-utils rsync 2>&1 | tail -5"),
    ("create_kismet_group", "Create kismet system group",       False,
        'getent group kismet &>/dev/null && echo "Group already exists" || sudo groupadd -r kismet'),
    ("create_kismet_user",  "Create kismet system user",        False,
        'id kismet &>/dev/null && echo "User already exists" || sudo useradd -r -m -g kismet kismet'),
    ("create_log_dir",      "Create Kismet log directory",      False,
        "sudo mkdir -p /home/kismet/kismet_logs && sudo chown kismet:kismet /home/kismet/kismet_logs && echo ok"),
    ("install_sync_script", "Install sync script & systemd",    False, None),
    ("mount_nas",           "Mount NAS share",                  False, None),
    ("enable_sync_timer",   "Enable sync timer",                False,
        "sudo systemctl daemon-reload && sudo systemctl enable cyt-kismet-sync.timer && sudo systemctl start cyt-kismet-sync.timer && echo ok"),
    ("enable_kismet",       "Enable and start Kismet service",   False,
        "sudo systemctl enable --now kismet 2>/dev/null && echo started || echo 'kismet service not found'"),
    ("detect_kismet_version", "Detect Kismet version",          False,
        "kismet --version 2>&1 | head -1 || echo unknown"),
    ("detect_local_hostname",  "Detect Pi local hostname",        False,
        "hostname"),
]

STEP_IDS = [s[0] for s in PROVISION_STEPS]


def provision_sensor(sensor, socketio, ssh_key_path=None, ssh_password=None,
                     nas_user=None, nas_password=None):
    """Run provisioning on a remote sensor.

    Returns dict with 'success' bool, 'steps' list, and 'kismet_version'.
    ssh_password and nas_password are used once and never stored.
    """
    sensor_id = sensor.id
    results = {}  # step_id -> status

    def emit(step_id, status, message=""):
        completed = sum(1 for s in results.values() if s in ("ok", "skipped"))
        payload = {
            "sensor_id": sensor_id,
            "step": step_id,
            "status": status,       # pending|running|ok|error|skipped
            "message": message[:300],
            "completed": completed,
            "total": len(PROVISION_STEPS),
        }
        if socketio:
            socketio.emit("provision_progress", payload)
        logger.info("Provision[%s] %s → %s  %s", sensor.name, step_id, status, message)

    # Emit all steps as pending so UI can render the full list immediately
    for step_id, label, *_ in PROVISION_STEPS:
        emit(step_id, "pending", label)

    # ── Step 1: TCP port reachability ──────────────────────────────────────
    emit("port_check", "running", f"Checking {sensor.hostname}:{sensor.ssh_port or 22}...")
    try:
        sock = socket.create_connection(
            (sensor.hostname, sensor.ssh_port or 22), timeout=8
        )
        sock.close()
        results["port_check"] = "ok"
        emit("port_check", "ok", f"Port {sensor.ssh_port or 22} reachable")
    except (socket.timeout, OSError) as exc:
        results["port_check"] = "error"
        emit("port_check", "error", f"Cannot reach host: {exc}")
        _skip_remaining(results, emit)
        return _build_result(results)

    # ── Step 2: SSH authentication ─────────────────────────────────────────
    emit("connectivity", "running", "Authenticating via SSH...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        connect_kwargs = {
            "hostname": sensor.hostname,
            "port": sensor.ssh_port or 22,
            "username": sensor.ssh_user or "pi",
            "timeout": 15,
            "allow_agent": True,
            "look_for_keys": True,
            "banner_timeout": 15,
        }
        if ssh_key_path:
            connect_kwargs["key_filename"] = ssh_key_path
        if ssh_password:
            connect_kwargs["password"] = ssh_password
        client.connect(**connect_kwargs)
        results["connectivity"] = "ok"
        emit("connectivity", "ok", f"Authenticated as {sensor.ssh_user or 'pi'}@{sensor.hostname}")
    except paramiko.AuthenticationException:
        results["connectivity"] = "error"
        emit("connectivity", "error", "Authentication failed — check SSH key or user")
        _skip_remaining(results, emit)
        return _build_result(results)
    except Exception as exc:
        results["connectivity"] = "error"
        emit("connectivity", "error", str(exc))
        _skip_remaining(results, emit)
        return _build_result(results)

    # ── Remaining steps via SSH ────────────────────────────────────────────
    kismet_version = None
    local_hostname = None
    try:
        for step_id, label, is_critical, cmd in PROVISION_STEPS:
            if step_id in ("port_check", "connectivity"):
                continue

            emit(step_id, "running")
            time.sleep(0.1)  # let UI render spinner

            # Dispatch special handlers
            if step_id == "install_sync_script":
                ok, msg = _install_sync_files(client, sensor)
            elif step_id == "mount_nas":
                ok, msg = _mount_nas(client, sensor, nas_user=nas_user, nas_password=nas_password)
            else:
                ok, msg = _run_cmd(client, cmd, timeout=300 if "apt" in cmd else 30)

            if step_id == "detect_kismet_version" and ok and msg:
                kismet_version = msg.strip()[:60]
            if step_id == "detect_local_hostname" and ok and msg:
                local_hostname = msg.strip()[:255]

            results[step_id] = "ok" if ok else "error"
            emit(step_id, "ok" if ok else "error", msg)

            if not ok and is_critical:
                emit(step_id, "error", f"Critical step failed — stopping. {msg}")
                _skip_remaining(results, emit)
                break

    finally:
        client.close()

    return _build_result(results, kismet_version, local_hostname)


# ── Helpers ────────────────────────────────────────────────────────────────

def _run_cmd(client, cmd, timeout=30):
    """Run a single command; return (success, output_or_error)."""
    try:
        _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if exit_code == 0:
            return True, out or "Done"
        return False, err or out or f"Exit code {exit_code}"
    except Exception as exc:
        return False, str(exc)


def _skip_remaining(results, emit):
    """Mark all unvisited steps as skipped."""
    for step_id, label, *_ in PROVISION_STEPS:
        if step_id not in results:
            results[step_id] = "skipped"
            emit(step_id, "skipped", "Skipped due to earlier failure")


def _build_result(results, kismet_version=None, local_hostname=None):
    critical_ids = {s[0] for s in PROVISION_STEPS if s[2]}
    success = all(results.get(s, "skipped") in ("ok",) for s in critical_ids)
    return {"success": success, "steps": results, "kismet_version": kismet_version, "local_hostname": local_hostname}


def _install_sync_files(client, sensor):
    """SCP kismet_sync.sh and write systemd service + timer via SFTP."""
    sync_script_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "sensor", "kismet_sync.sh"
    )
    if not os.path.exists(sync_script_path):
        return False, f"sync script not found at {sync_script_path}"

    nas_mount = "/mnt/nas_kismet"

    # Write systemd service via SFTP (avoids echo -e shell escaping issues)
    service_unit = f"""[Unit]
Description=CYT-NG Kismet data sync to NAS
After=network-online.target remote-fs.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/cyt-kismet-sync
User=root
Environment=KISMET_LOG_DIR=/home/kismet/kismet_logs
Environment=NAS_MOUNT={nas_mount}

[Install]
WantedBy=multi-user.target
"""
    timer_unit = """[Unit]
Description=CYT-NG Kismet sync timer

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
"""
    try:
        sftp = client.open_sftp()
        try:
            sftp.put(sync_script_path, "/tmp/cyt-kismet-sync")
            with sftp.open("/tmp/cyt-kismet-sync.service", "w") as f:
                f.write(service_unit)
            with sftp.open("/tmp/cyt-kismet-sync.timer", "w") as f:
                f.write(timer_unit)
        finally:
            sftp.close()
    except Exception as exc:
        return False, f"SFTP upload failed: {exc}"

    # Move files into place
    cmds = [
        "sudo mv /tmp/cyt-kismet-sync /usr/local/bin/cyt-kismet-sync",
        "sudo chown root:root /usr/local/bin/cyt-kismet-sync",
        "sudo chmod 755 /usr/local/bin/cyt-kismet-sync",
        "sudo mv /tmp/cyt-kismet-sync.service /etc/systemd/system/cyt-kismet-sync.service",
        "sudo mv /tmp/cyt-kismet-sync.timer /etc/systemd/system/cyt-kismet-sync.timer",
        "sudo chmod 644 /etc/systemd/system/cyt-kismet-sync.service /etc/systemd/system/cyt-kismet-sync.timer",
    ]
    for cmd in cmds:
        _, stdout, stderr = client.exec_command(cmd, timeout=15)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            err = stderr.read().decode("utf-8", errors="replace").strip()
            return False, f"Failed: {cmd!r} — {err}"

    return True, "Sync script + systemd units installed (root:root)"


def _mount_nas(client, sensor, nas_user=None, nas_password=None):
    """Create NAS mount point, write credentials, configure fstab, and mount."""
    nas_share = getattr(sensor, "smb_share_path", None)
    if not nas_share:
        return True, "No SMB share configured — skipped"  # not a failure

    nas_mount = "/mnt/nas_kismet"
    creds_file = "/etc/cyt-nas.creds"

    # Check if already mounted
    ok, msg = _run_cmd(client, f"mountpoint -q {nas_mount} && echo mounted || echo not_mounted", timeout=10)
    if ok and "mounted" in msg:
        return True, f"{nas_mount} already mounted"

    # Write SMB credentials file if user/password provided
    if nas_user and nas_password:
        try:
            sftp = client.open_sftp()
            try:
                with sftp.open("/tmp/cyt-nas.creds", "w") as f:
                    f.write(f"username={nas_user}\npassword={nas_password}\n")
            finally:
                sftp.close()
            cmds = [
                "sudo mv /tmp/cyt-nas.creds /etc/cyt-nas.creds",
                "sudo chmod 600 /etc/cyt-nas.creds",
                "sudo chown root:root /etc/cyt-nas.creds",
            ]
            for cmd in cmds:
                ok_c, msg_c = _run_cmd(client, cmd, timeout=10)
                if not ok_c:
                    return False, f"Failed to install NAS credentials: {msg_c}"
        except Exception as exc:
            return False, f"SFTP creds upload failed: {exc}"
    else:
        # Check if creds file already exists from a previous run
        ok_check, msg_check = _run_cmd(client, f"test -f {creds_file} && echo exists || echo missing", timeout=5)
        if "missing" in msg_check:
            return False, f"No NAS credentials — provide NAS username/password or create {creds_file} on the sensor"

    # Ensure mount point exists
    ok, msg = _run_cmd(client, f"sudo mkdir -p {nas_mount}", timeout=10)
    if not ok:
        return False, f"Could not create mount point: {msg}"

    # Add to fstab if not already there — write via SFTP to avoid shell quoting hazards
    check_cmd = f"grep -qF '{nas_share}' /etc/fstab && echo exists || echo missing"
    ok, msg = _run_cmd(client, check_cmd, timeout=10)
    if ok and "missing" in msg:
        fstab_line = f"{nas_share} {nas_mount} cifs credentials={creds_file},iocharset=utf8,vers=3.0,nofail,_netdev 0 0\n"
        try:
            sftp = client.open_sftp()
            try:
                with sftp.open("/tmp/cyt-fstab-entry", "w") as f:
                    f.write(fstab_line)
            finally:
                sftp.close()
            ok, msg = _run_cmd(client, "sudo sh -c 'cat /tmp/cyt-fstab-entry >> /etc/fstab && rm /tmp/cyt-fstab-entry' && echo added", timeout=10)
            if not ok:
                return False, f"Could not update fstab: {msg}"
        except Exception as exc:
            return False, f"SFTP fstab write failed: {exc}"

    # Attempt mount
    ok, msg = _run_cmd(client, f"sudo mount {nas_mount} 2>&1 || true", timeout=20)
    mounted_ok, _ = _run_cmd(client, f"mountpoint -q {nas_mount} && echo yes || echo no", timeout=10)
    if "yes" in _:
        return True, f"NAS mounted at {nas_mount}"
    return False, f"Mount attempted but {nas_mount} not mounted — check credentials file {creds_file}"
