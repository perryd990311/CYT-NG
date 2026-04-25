"""Sensors blueprint — manage Kismet sensor Raspberry Pis."""
import re
import socket
from datetime import datetime

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required
from sqlalchemy import func

from web.extensions import get_db
from cyt.models import Sensor, Appearance, KismetFileTracker

bp = Blueprint("sensors", __name__, url_prefix="/sensors")

# Hostname/IP pattern: alphanumeric, dots, hyphens, colons (IPv6)
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9._:\-]{1,253}$")


@bp.before_request
@login_required
def require_login():
    pass


@bp.route("/")
def index():
    db = get_db()
    sensors = db.query(Sensor).order_by(Sensor.name).all()

    # Sightings per sensor
    sightings_q = (
        db.query(Appearance.sensor_id, func.count(Appearance.id))
        .group_by(Appearance.sensor_id)
        .all()
    )
    sightings_map = dict(sightings_q)

    # DB size per sensor (sum of tracked Kismet file sizes)
    dbsize_q = (
        db.query(KismetFileTracker.sensor_id, func.sum(KismetFileTracker.file_size))
        .group_by(KismetFileTracker.sensor_id)
        .all()
    )
    dbsize_map = dict(dbsize_q)

    now = datetime.utcnow()
    sensor_stats = []
    for s in sensors:
        sightings = sightings_map.get(s.id, 0)
        db_bytes = dbsize_map.get(s.id, 0) or 0
        db_size_mb = round(db_bytes / (1024 * 1024), 1) if db_bytes else 0

        # Sync health: based on minutes since last_seen
        if s.last_seen:
            delta_min = (now - s.last_seen).total_seconds() / 60
            if delta_min <= 10:
                sync_pct, sync_level = 100, "ok"
            elif delta_min <= 30:
                sync_pct, sync_level = 85, "ok"
            elif delta_min <= 60:
                sync_pct, sync_level = 60, "warn"
            elif delta_min <= 360:
                sync_pct, sync_level = 30, "danger"
            else:
                sync_pct, sync_level = 0, "danger"
        else:
            sync_pct, sync_level = 0, "danger"

        # Uptime: time since created_at
        if s.created_at:
            uptime_delta = now - s.created_at
            days = uptime_delta.days
            hours = uptime_delta.seconds // 3600
            mins = (uptime_delta.seconds % 3600) // 60
            if days > 0:
                uptime_str = f"{days}d {hours}h {mins}m"
            elif hours > 0:
                uptime_str = f"{hours}h {mins}m"
            else:
                uptime_str = f"{mins}m"
        else:
            uptime_str = "—"

        sensor_stats.append({
            "sensor": s,
            "sightings": sightings,
            "db_size_mb": db_size_mb,
            "sync_pct": sync_pct,
            "sync_level": sync_level,
            "uptime": uptime_str,
        })

    is_htmx = request.headers.get("HX-Request")
    if is_htmx:
        return render_template("partials/sensor_list.html", sensor_stats=sensor_stats)
    return render_template("sensors.html", sensor_stats=sensor_stats)


@bp.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "GET":
        from flask import current_app
        default_smb = current_app.config.get("RAW_CONFIG", {}).get("sensor", {}).get("smb_share", "")
        return render_template("sensor_form.html", sensor=None, default_smb=default_smb)

    name = request.form.get("name", "").strip()
    hostname = request.form.get("hostname", "").strip()
    ssh_port = request.form.get("ssh_port", "22").strip()
    ssh_user = request.form.get("ssh_user", "pi").strip()
    wifi_interface = request.form.get("wifi_interface", "wlan1").strip()
    ssh_key_path = request.form.get("ssh_key_path", "").strip() or None
    smb_share_path = request.form.get("smb_share_path", "").strip() or None
    ssh_password = request.form.get("ssh_password", "") or None  # not persisted
    nas_user = request.form.get("nas_user", "") or None          # not persisted
    nas_password = request.form.get("nas_password", "") or None  # not persisted

    if not name or not hostname:
        flash("Name and hostname are required.", "danger")
        return redirect(url_for("sensors.add"))

    # Basic hostname validation (alphanumeric, dots, hyphens)
    if not _HOSTNAME_RE.match(hostname):
        flash("Invalid hostname.", "danger")
        return redirect(url_for("sensors.add"))

    try:
        port = int(ssh_port)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        flash("SSH port must be 1-65535.", "danger")
        return redirect(url_for("sensors.add"))

    db = get_db()
    sensor = Sensor(
        name=name,
        hostname=hostname,
        ssh_port=port,
        ssh_user=ssh_user,
        wifi_interface=wifi_interface,
        ssh_key_path=ssh_key_path,
        smb_share_path=smb_share_path,
        status="unknown",
    )
    db.add(sensor)
    db.commit()

    # Auto-provision if checkbox was checked
    should_provision = request.form.get("provision") == "1"
    if should_provision:
        from flask import current_app

        sensor.status = "provisioning"
        db.commit()
        socketio = current_app.extensions.get("socketio")
        if socketio:
            socketio.start_background_task(
                _run_provision, current_app._get_current_object(), sensor.id,
                ssh_password=ssh_password, nas_user=nas_user, nas_password=nas_password
            )
        flash(f"Sensor '{name}' added — provisioning started.", "info")
        return redirect(url_for("sensors.detail", sensor_id=sensor.id))

    flash(f"Sensor '{name}' added.", "success")
    return redirect(url_for("sensors.index"))


@bp.route("/<int:sensor_id>")
def detail(sensor_id):
    db = get_db()
    sensor = db.query(Sensor).get(sensor_id)
    if not sensor:
        flash("Sensor not found.", "warning")
        return redirect(url_for("sensors.index"))
    return render_template("sensor_detail.html", sensor=sensor)


@bp.route("/<int:sensor_id>/set_nas_dir", methods=["POST"])
def set_nas_dir(sensor_id):
    """Update local_hostname (NAS directory name) for a sensor. HTMX endpoint."""
    db = get_db()
    sensor = db.query(Sensor).get(sensor_id)
    if not sensor:
        return '<span class="text-danger">Sensor not found.</span>', 404
    value = request.form.get("local_hostname", "").strip() or None
    sensor.local_hostname = value
    db.commit()
    display = value or '—'
    return f'''<span id="nas-dir-display">{display}</span>
 <button class="btn btn-link btn-sm p-0 ms-1 text-secondary"
         hx-get="{ url_for('sensors.nas_dir_form', sensor_id=sensor_id) }"
         hx-target="#nas-dir-cell" hx-swap="innerHTML"
         title="Edit"><i class="bi bi-pencil"></i></button>'''


@bp.route("/<int:sensor_id>/nas_dir_form", methods=["GET"])
def nas_dir_form(sensor_id):
    """Return an inline edit form for local_hostname. HTMX endpoint."""
    db = get_db()
    sensor = db.query(Sensor).get(sensor_id)
    if not sensor:
        return '<span class="text-danger">Not found.</span>', 404
    current = sensor.local_hostname or ''
    return f'''<form hx-post="{ url_for('sensors.set_nas_dir', sensor_id=sensor_id) }"
          hx-target="#nas-dir-cell" hx-swap="innerHTML" class="d-flex gap-1">
  <input type="text" name="local_hostname" value="{current}"
         class="form-control form-control-sm" placeholder="e.g. raspberrypi" style="max-width:180px">
  <button type="submit" class="btn btn-sm btn-primary">Save</button>
  <button type="button" class="btn btn-sm btn-outline-secondary"
          hx-get="{ url_for('sensors.detail', sensor_id=sensor_id) }"
          hx-target="body" hx-swap="outerHTML">Cancel</button>
</form>'''


@bp.route("/<int:sensor_id>/delete", methods=["POST"])
def delete(sensor_id):
    db = get_db()
    sensor = db.query(Sensor).get(sensor_id)
    if sensor:
        db.delete(sensor)
        db.commit()
        flash(f"Sensor '{sensor.name}' deleted.", "success")
    return redirect(url_for("sensors.index"))


@bp.route("/<int:sensor_id>/provision", methods=["POST"])
def provision(sensor_id):
    """Kick off sensor provisioning in a background SocketIO task."""
    from flask import current_app

    db = get_db()
    sensor = db.query(Sensor).get(sensor_id)
    if not sensor:
        flash("Sensor not found.", "warning")
        return redirect(url_for("sensors.index"))

    ssh_password = request.form.get("ssh_password", "") or None   # not persisted
    nas_user = request.form.get("nas_user", "") or None           # not persisted
    nas_password = request.form.get("nas_password", "") or None   # not persisted

    # Mark as provisioning
    sensor.status = "provisioning"
    db.commit()

    socketio = current_app.extensions.get("socketio")
    if socketio:
        socketio.start_background_task(
            _run_provision, current_app._get_current_object(), sensor_id,
            ssh_password=ssh_password, nas_user=nas_user, nas_password=nas_password
        )

    flash(f"Provisioning '{sensor.name}' started — watch progress below.", "info")
    return redirect(url_for("sensors.detail", sensor_id=sensor_id))


@bp.route("/<int:sensor_id>/test_connectivity", methods=["POST"])
def test_connectivity(sensor_id):
    """Quick TCP + SSH auth check; returns an HTML fragment for HTMX."""
    import paramiko

    db = get_db()
    sensor = db.query(Sensor).get(sensor_id)
    if not sensor:
        return '<span class="text-danger">Sensor not found.</span>', 404

    host = sensor.hostname
    port = sensor.ssh_port or 22
    ssh_password = request.form.get("ssh_password", "") or None
    results = []

    # 1. TCP reachability
    try:
        sock = socket.create_connection((host, port), timeout=6)
        sock.close()
        results.append(("TCP port reachable", True, f"{host}:{port} open"))
    except (socket.timeout, OSError) as exc:
        results.append(("TCP port reachable", False, str(exc)))
        return _conn_html(results)

    # 2. SSH auth (keys only — no password prompt)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        connect_kwargs = dict(
            hostname=host, port=port,
            username=sensor.ssh_user or "pi",
            timeout=10, allow_agent=True, look_for_keys=True,
            banner_timeout=10,
        )
        if sensor.ssh_key_path:
            connect_kwargs["key_filename"] = sensor.ssh_key_path
        if ssh_password:
            connect_kwargs["password"] = ssh_password
        client.connect(**connect_kwargs)
        results.append(("SSH authentication", True, f"Authenticated as {sensor.ssh_user or 'pi'}"))
    except paramiko.AuthenticationException:
        results.append(("SSH authentication", False, "Authentication failed — check SSH key"))
        client.close()
        return _conn_html(results)
    except Exception as exc:
        results.append(("SSH authentication", False, str(exc)))
        return _conn_html(results)

    # 3. Sudo check
    try:
        _, stdout, _ = client.exec_command("sudo -n true 2>&1 && echo ok || echo fail", timeout=8)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        ok = "ok" in out
        results.append(("Sudo access", ok, "sudo available" if ok else "sudo requires password or not permitted"))
    except Exception as exc:
        results.append(("Sudo access", False, str(exc)))
    finally:
        client.close()

    # 4. NAS share / last_sync check (server-side, no SSH needed)
    from datetime import datetime, timezone
    from flask import current_app
    import os

    kismet_path = current_app.config.get("KISMET_LOGS", "")
    nas_dir = sensor.local_hostname or sensor.hostname
    if kismet_path and nas_dir:
        sensor_dir = os.path.join(kismet_path, nas_dir)
        sync_file = os.path.join(sensor_dir, ".last_sync")
        if not os.path.isdir(sensor_dir):
            results.append(("NAS share directory", False,
                            f"{sensor_dir} not found — check NAS directory name"))
        elif not os.path.isfile(sync_file):
            results.append(("NAS share directory", True, f"{sensor_dir} exists"))
            results.append(("Last sync file", False, ".last_sync missing — sync script may not be running"))
        else:
            results.append(("NAS share directory", True, f"{sensor_dir} exists"))
            try:
                raw = open(sync_file).read().strip()
                ts = datetime.fromisoformat(raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - ts
                mins = int(age.total_seconds() // 60)
                age_str = f"{mins}m ago" if mins < 120 else f"{mins // 60}h ago"
                fresh = age.total_seconds() < 300  # warn if >5 min
                results.append(("Last sync", fresh,
                                f"{age_str} ({ts.strftime('%Y-%m-%d %H:%M:%S %Z')})",
                                "ok" if fresh else "warn"))
            except (ValueError, OSError) as exc:
                results.append(("Last sync", False, f"Could not parse .last_sync: {exc}"))
    else:
        results.append(("NAS share check", False,
                        "Skipped — KISMET_LOGS not configured or NAS directory not set"))

    return _conn_html(results)


def _conn_html(results):
    """Render a compact result table fragment."""
    rows = ""
    for item in results:
        label, ok, msg = item[0], item[1], item[2]
        warn = len(item) > 3 and item[3] == "warn"
        if ok:
            icon = '<i class="bi bi-check-circle-fill text-success"></i>'
        elif warn:
            icon = '<i class="bi bi-exclamation-circle-fill text-warning"></i>'
        else:
            icon = '<i class="bi bi-x-circle-fill text-danger"></i>'
        rows += f'<tr><td class="pe-2">{icon}</td><td>{label}</td><td class="text-muted small">{msg}</td></tr>\n'
    return f'<table class="table table-sm mb-0">{rows}</table>'


def _run_provision(app, sensor_id, ssh_password=None, nas_user=None, nas_password=None):
    from cyt.sensor_provisioner import provision_sensor

    with app.app_context():
        db = get_db()
        sensor = db.query(Sensor).get(sensor_id)
        if not sensor:
            return

        socketio = app.extensions.get("socketio")
        result = provision_sensor(
            sensor, socketio,
            ssh_key_path=sensor.ssh_key_path or None,
            ssh_password=ssh_password,
            nas_user=nas_user,
            nas_password=nas_password,
        )

        # Update sensor record
        sensor.status = "online" if result["success"] else "error"
        if result.get("kismet_version"):
            sensor.kismet_version = result["kismet_version"]
        if result.get("local_hostname"):
            sensor.local_hostname = result["local_hostname"]
        db.commit()

        # Final status event
        if socketio:
            socketio.emit("provision_complete", {
                "sensor_id": sensor_id,
                "success": result["success"],
                "status": sensor.status,
            })
