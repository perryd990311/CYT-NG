"""Dashboard blueprint — landing page, status bar, live device feed."""
from datetime import datetime, timedelta

from flask import Blueprint, render_template, jsonify, request
from sqlalchemy import func

from web.extensions import get_db, socketio
from cyt.models import Device, Appearance, Sensor, AnalysisRun, KismetFileTracker

bp = Blueprint("dashboard", __name__)


@bp.before_request
def require_login():
    """Require login for all dashboard routes except the health endpoint."""
    if request.endpoint == "dashboard.api_status":
        return
    from flask_login import current_user
    if not current_user.is_authenticated:
        from flask import redirect, url_for
        return redirect(url_for("auth.login", next=request.url))


def _is_htmx():
    return request.headers.get("HX-Request") == "true"


@bp.route("/")
def index():
    db = get_db()
    now = datetime.utcnow()
    five_min_ago = now - timedelta(minutes=5)

    total_devices = db.query(Device).count()
    active_devices = (
        db.query(Device)
        .filter(Device.last_seen >= five_min_ago)
        .count()
    )
    total_appearances = db.query(Appearance).count()
    sensors_online = db.query(Sensor).filter(Sensor.status == "online").count()
    sensors_total = db.query(Sensor).count()

    last_run = (
        db.query(AnalysisRun)
        .order_by(AnalysisRun.started_at.desc())
        .first()
    )

    day_ago = now - timedelta(hours=24)
    new_24h = db.query(Device).filter(Device.first_seen >= day_ago).count()
    probes_24h = db.query(Appearance).filter(Appearance.timestamp >= day_ago).count()
    recurring_subq = (
        db.query(Appearance.device_id)
        .filter(Appearance.timestamp >= day_ago)
        .group_by(Appearance.device_id)
        .having(func.count(Appearance.id) > 1)
        .subquery()
    )
    recurring_24h = db.query(func.count()).select_from(recurring_subq).scalar() or 0
    top_persistent = (
        db.query(Device, func.count(Appearance.id).label("cnt"))
        .join(Appearance, Device.id == Appearance.device_id)
        .group_by(Device.id)
        .order_by(func.count(Appearance.id).desc())
        .limit(10)
        .all()
    )

    return render_template(
        "dashboard.html",
        total_devices=total_devices,
        active_devices=active_devices,
        total_appearances=total_appearances,
        sensors_online=sensors_online,
        sensors_total=sensors_total,
        last_run=last_run,
        new_24h=new_24h,
        probes_24h=probes_24h,
        recurring_24h=recurring_24h,
        top_persistent=top_persistent,
    )


@bp.route("/partials/status-bar")
def status_bar():
    db = get_db()
    now = datetime.utcnow()

    latest_appearance = (
        db.query(Appearance)
        .order_by(Appearance.timestamp.desc())
        .first()
    )
    data_age = None
    if latest_appearance and latest_appearance.timestamp:
        delta = now - latest_appearance.timestamp
        data_age = int(delta.total_seconds() // 60)

    kismet_files = db.query(KismetFileTracker).count()
    sensors_online = db.query(Sensor).filter(Sensor.status == "online").count()
    sensors_total = db.query(Sensor).count()

    return render_template(
        "partials/status_bar.html",
        data_age_minutes=data_age,
        kismet_files=kismet_files,
        sensors_online=sensors_online,
        sensors_total=sensors_total,
    )


@bp.route("/api/sparkline")
def api_sparkline():
    """Hourly unique device counts for the last 24h dashboard sparkline."""
    db = get_db()
    since = datetime.utcnow() - timedelta(hours=24)
    rows = (
        db.query(
            func.strftime("%Y-%m-%d %H:00", Appearance.timestamp).label("bucket"),
            func.count(func.distinct(Appearance.device_id)).label("devices"),
        )
        .filter(Appearance.timestamp >= since)
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )
    return jsonify(
        labels=[r.bucket[-5:] for r in rows],
        data=[r.devices for r in rows],
    )


@bp.route("/api/status")
def api_status():
    """JSON health / status endpoint."""
    db = get_db()
    return jsonify(
        status="ok",
        devices=db.query(Device).count(),
        appearances=db.query(Appearance).count(),
        sensors=db.query(Sensor).filter(Sensor.status == "online").count(),
    )


@bp.route("/api/devices")
def api_devices():
    """Return recent devices as HTMX partial or JSON."""
    db = get_db()
    page = request.args.get("page", 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    devices = (
        db.query(Device)
        .order_by(Device.last_seen.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )
    total = db.query(Device).count()

    if _is_htmx():
        return render_template(
            "partials/device_list.html",
            devices=devices,
            page=page,
            total=total,
            per_page=per_page,
        )

    return jsonify(
        devices=[
            {
                "mac": d.mac,
                "last_seen": d.last_seen.isoformat() if d.last_seen else None,
                "device_type": d.device_type,
                "manufacturer": d.manufacturer,
            }
            for d in devices
        ],
        total=total,
        page=page,
    )


# ── SocketIO events ─────────────────────────────────────────
@socketio.on("connect")
def handle_connect():
    pass


@socketio.on("request_status")
def handle_request_status():
    db = get_db()
    socketio.emit("status_update", {
        "devices": db.query(Device).count(),
        "sensors": db.query(Sensor).filter(Sensor.status == "online").count(),
    })
