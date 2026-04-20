"""Sensors blueprint — manage Kismet sensor Raspberry Pis."""
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required

from web.extensions import get_db
from cyt.models import Sensor
from cyt.input_validation import InputValidator

bp = Blueprint("sensors", __name__, url_prefix="/sensors")


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
    clean_hostname = InputValidator.validate_path(hostname)
    if not clean_hostname:
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
