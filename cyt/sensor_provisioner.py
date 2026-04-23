"""Remote sensor provisioning via SSH (Paramiko).

Connects to a Raspberry Pi, installs Kismet + sync components,
and streams step-by-step progress via SocketIO events.
"""
import logging
import time

import paramiko

logger = logging.getLogger(__name__)

# Provisioning steps — each is (step_name, shell_command)
PROVISION_STEPS = [
    ("connectivity", "echo ok"),
    ("update_packages", "sudo apt-get update -qq"),
    ("install_kismet", "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq kismet cifs-utils"),
    ("create_kismet_user", (
        'id kismet &>/dev/null && echo "exists" || '
        "sudo useradd -m -G kismet kismet"
    )),
    ("create_log_dir", "sudo mkdir -p /home/kismet/kismet_logs && sudo chown kismet:kismet /home/kismet/kismet_logs"),
    ("install_sync_script", None),  # handled specially — SCP
    ("enable_sync_timer", "sudo systemctl daemon-reload && sudo systemctl enable --now cyt-kismet-sync.timer 2>/dev/null || true"),
    ("detect_kismet_version", "kismet --version 2>/dev/null | head -1 || echo unknown"),
]


def provision_sensor(sensor, socketio, ssh_key_path=None, nas_share=None):
    """Run provisioning on a remote sensor.

    Args:
        sensor: Sensor model instance (must have hostname, ssh_port, ssh_user, wifi_interface).
        socketio: Flask-SocketIO instance for emitting progress.
        ssh_key_path: Optional path to SSH private key. Falls back to agent.
        nas_share: SMB share path for kismet sync (e.g. //nas/kismet_data).

    Returns:
        dict with 'success' bool and 'steps' list of step results.
    """
    sensor_id = sensor.id
    results = []

    def emit_progress(step, status, message=""):
        """Emit a provision_progress event."""
        payload = {
            "sensor_id": sensor_id,
            "step": step,
            "status": status,  # "running", "ok", "error", "skipped"
            "message": message,
            "completed": len([r for r in results if r["status"] in ("ok", "skipped")]),
            "total": len(PROVISION_STEPS),
        }
        socketio.emit("provision_progress", payload)
        logger.info("Provision %s [%s]: %s %s", sensor.name, step, status, message)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Step 0: Connect
    emit_progress("connectivity", "running", "Connecting via SSH...")
    try:
        connect_kwargs = {
            "hostname": sensor.hostname,
            "port": sensor.ssh_port or 22,
            "username": sensor.ssh_user or "pi",
            "timeout": 15,
            "allow_agent": True,
            "look_for_keys": True,
        }
        if ssh_key_path:
            connect_kwargs["key_filename"] = ssh_key_path
        client.connect(**connect_kwargs)
        results.append({"step": "connectivity", "status": "ok"})
        emit_progress("connectivity", "ok", f"Connected to {sensor.hostname}")
    except Exception as exc:
        results.append({"step": "connectivity", "status": "error"})
        emit_progress("connectivity", "error", str(exc))
        return {"success": False, "steps": results}

    kismet_version = None

    try:
        for step_name, cmd in PROVISION_STEPS:
            if step_name == "connectivity":
                continue  # already done

            emit_progress(step_name, "running")

            if step_name == "install_sync_script":
                # SCP the sync script and systemd units
                try:
                    _install_sync_files(client, sensor, nas_share)
                    results.append({"step": step_name, "status": "ok"})
                    emit_progress(step_name, "ok", "Sync script installed")
                except Exception as exc:
                    results.append({"step": step_name, "status": "error"})
                    emit_progress(step_name, "error", str(exc))
                continue

            # Run command via SSH
            try:
                stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
                exit_code = stdout.channel.recv_exit_status()
                output = stdout.read().decode("utf-8", errors="replace").strip()
                err_output = stderr.read().decode("utf-8", errors="replace").strip()

                if step_name == "detect_kismet_version" and output:
                    kismet_version = output[:50]

                if exit_code == 0:
                    results.append({"step": step_name, "status": "ok"})
                    emit_progress(step_name, "ok", output[:200] if output else "Done")
                else:
                    results.append({"step": step_name, "status": "error"})
                    msg = err_output[:200] if err_output else f"Exit code {exit_code}"
                    emit_progress(step_name, "error", msg)
            except Exception as exc:
                results.append({"step": step_name, "status": "error"})
                emit_progress(step_name, "error", str(exc))

            # Small pause so the UI can animate
            time.sleep(0.3)

    finally:
        client.close()

    success = all(r["status"] in ("ok", "skipped") for r in results)
    return {"success": success, "steps": results, "kismet_version": kismet_version}


def _install_sync_files(client, sensor, nas_share):
    """SCP the sync script and create systemd units on the sensor."""
    import os

    sync_script_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "sensor", "kismet_sync.sh"
    )

    sftp = client.open_sftp()
    try:
        sftp.put(sync_script_path, "/tmp/cyt-kismet-sync")
    finally:
        sftp.close()

    commands = [
        "sudo mv /tmp/cyt-kismet-sync /usr/local/bin/cyt-kismet-sync",
        "sudo chmod +x /usr/local/bin/cyt-kismet-sync",
    ]

    # Create systemd service
    nas_mount = "/mnt/nas_kismet"
    service_content = (
        "[Unit]\\n"
        "Description=CYT-NG Kismet data sync to NAS\\n"
        "After=network-online.target remote-fs.target\\n"
        "Wants=network-online.target\\n\\n"
        "[Service]\\n"
        "Type=oneshot\\n"
        "ExecStart=/usr/local/bin/cyt-kismet-sync\\n"
        "User=root\\n"
        f"Environment=KISMET_LOG_DIR=/home/kismet/kismet_logs\\n"
        f"Environment=NAS_MOUNT={nas_mount}\\n\\n"
        "[Install]\\n"
        "WantedBy=multi-user.target"
    )
    commands.append(
        f'echo -e "{service_content}" | sudo tee /etc/systemd/system/cyt-kismet-sync.service > /dev/null'
    )

    # Create systemd timer
    timer_content = (
        "[Unit]\\n"
        "Description=CYT-NG Kismet sync timer\\n\\n"
        "[Timer]\\n"
        "OnBootSec=2min\\n"
        "OnUnitActiveSec=5min\\n"
        "Persistent=true\\n\\n"
        "[Install]\\n"
        "WantedBy=timers.target"
    )
    commands.append(
        f'echo -e "{timer_content}" | sudo tee /etc/systemd/system/cyt-kismet-sync.timer > /dev/null'
    )

    for cmd in commands:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            err = stderr.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Command failed ({exit_code}): {err}")
