"""Sensors blueprint — manage Kismet sensor Raspberry Pis."""
import re

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
                _run_provision, current_app._get_current_object(), sensor.id
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
    from flask_socketio import SocketIO

    db = get_db()
    sensor = db.query(Sensor).get(sensor_id)
    if not sensor:
        flash("Sensor not found.", "warning")
        return redirect(url_for("sensors.index"))

    # Mark as provisioning
    sensor.status = "provisioning"
    db.commit()

    # Get SocketIO instance and start background task
    socketio = current_app.extensions.get("socketio")
    if socketio:
        socketio.start_background_task(
            _run_provision, current_app._get_current_object(), sensor_id
        )

    flash(f"Provisioning '{sensor.name}' started — watch progress below.", "info")
    return redirect(url_for("sensors.detail", sensor_id=sensor_id))


def _run_provision(app, sensor_id):
    """Background task: provision sensor via SSH."""
    from cyt.sensor_provisioner import provision_sensor

    with app.app_context():
        db = get_db()
        sensor = db.query(Sensor).get(sensor_id)
        if not sensor:
            return

        socketio = app.extensions.get("socketio")
        result = provision_sensor(sensor, socketio)

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
