"""Sensors blueprint — manage Kismet sensor Raspberry Pis."""
import re
import socket

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required

from web.extensions import get_db
from cyt.models import Sensor

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

    is_htmx = request.headers.get("HX-Request")
    if is_htmx:
        return render_template("partials/sensor_list.html", sensors=sensors)
    return render_template("sensors.html", sensors=sensors)


@bp.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "GET":
        return render_template("sensor_form.html", sensor=None)

    name = request.form.get("name", "").strip()
    hostname = request.form.get("hostname", "").strip()
    ssh_port = request.form.get("ssh_port", "22").strip()
    ssh_user = request.form.get("ssh_user", "pi").strip()
    wifi_interface = request.form.get("wifi_interface", "wlan1").strip()
    ssh_key_path = request.form.get("ssh_key_path", "").strip() or None
    smb_share_path = request.form.get("smb_share_path", "").strip() or None
    ssh_password = request.form.get("ssh_password", "") or None  # not persisted

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
                ssh_password=ssh_password
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

    ssh_password = request.form.get("ssh_password", "") or None  # not persisted

    # Mark as provisioning
    sensor.status = "provisioning"
    db.commit()

    socketio = current_app.extensions.get("socketio")
    if socketio:
        socketio.start_background_task(
            _run_provision, current_app._get_current_object(), sensor_id,
            ssh_password=ssh_password
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

    return _conn_html(results)


def _conn_html(results):
    """Render a compact result table fragment."""
    rows = ""
    for label, ok, msg in results:
        icon = '<i class="bi bi-check-circle-fill text-success"></i>' if ok else '<i class="bi bi-x-circle-fill text-danger"></i>'
        rows += f'<tr><td class="pe-2">{icon}</td><td>{label}</td><td class="text-muted small">{msg}</td></tr>'
    return f'<table class="table table-sm table-borderless mb-0 mt-1"><tbody>{rows}</tbody></table>'


def _run_provision(app, sensor_id, ssh_password=None):
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
        )

        # Update sensor record
        sensor.status = "online" if result["success"] else "error"
        if result.get("kismet_version"):
            sensor.kismet_version = result["kismet_version"]
        db.commit()

        # Final status event
        if socketio:
            socketio.emit("provision_complete", {
                "sensor_id": sensor_id,
                "success": result["success"],
                "status": sensor.status,
            })
