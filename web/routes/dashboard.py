"""Dashboard blueprint — landing page, status bar, live device feed."""

from datetime import datetime, timedelta

from flask import Blueprint, render_template, jsonify, request, current_app
from sqlalchemy import func

from web.extensions import get_db, socketio
from cyt.models import Device, Appearance, Sensor, AnalysisRun, KismetFileTracker, Fingerprint
from cyt.scoring import compute_likelihood
from web.routes.settings import get_baseline_macs

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
    # Active window: use check_interval from config (seconds) * 3 as the lookback,
    # with a minimum of 5 minutes to account for ingestion lag and sync delays.
    check_secs = current_app.config.get("TIMING", {}).get("check_interval", 60)
    active_window_minutes = max(5, (check_secs * 3) // 60)
    active_since = now - timedelta(minutes=active_window_minutes)
    show_ignored = request.args.get("show_ignored", "0") == "1"
    baseline_macs = get_baseline_macs()
    hide_unknown = current_app.config.get("HIDE_UNKNOWN_MANUFACTURER", False)

    # Base device query with optional filters
    base_q = db.query(Device)
    if hide_unknown:
        base_q = base_q.filter(
            Device.manufacturer != "Unknown",
            Device.manufacturer != "",
            Device.manufacturer.isnot(None),
        )

    total_devices = base_q.count()
    active_devices = base_q.filter(Device.last_seen >= active_since).count()
    total_appearances = db.query(Appearance).count()
    sensors_online = db.query(Sensor).filter(Sensor.status == "online").count()
    sensors_total = db.query(Sensor).count()

    last_run = db.query(AnalysisRun).order_by(AnalysisRun.started_at.desc()).first()

    day_ago = now - timedelta(hours=24)
    new_24h = base_q.filter(Device.first_seen >= day_ago).count()
    probes_24h = db.query(Appearance).filter(Appearance.timestamp >= day_ago).count()
    recurring_subq = (
        db.query(Appearance.device_id)
        .filter(Appearance.timestamp >= day_ago)
        .group_by(Appearance.device_id)
        .having(func.count(Appearance.id) > 1)
        .subquery()
    )
    recurring_24h = db.query(func.count()).select_from(recurring_subq).scalar() or 0

    top_q = (
        db.query(Device, func.count(Appearance.id).label("cnt"))
        .join(Appearance, Device.id == Appearance.device_id)
        .group_by(Device.id)
        .order_by(func.count(Appearance.id).desc())
    )
    if hide_unknown:
        top_q = top_q.filter(
            Device.manufacturer != "Unknown",
            Device.manufacturer != "",
            Device.manufacturer.isnot(None),
        )
    if not show_ignored and baseline_macs:
        top_q = top_q.filter(func.upper(Device.mac).notin_(baseline_macs))
    top_persistent = top_q.limit(10).all()

    # Enrich top persistent with probed SSIDs and suspicious likelihood
    top_enriched = []
    for device, cnt in top_persistent:
        app_rows = db.query(Appearance.ssids_json).filter(Appearance.device_id == device.id).all()
        probed = set()
        for (ssids_json,) in app_rows:
            if ssids_json:
                try:
                    import json as _json

                    for s in _json.loads(ssids_json):
                        if s and s.strip():
                            probed.add(s.strip())
                except Exception:
                    pass
        _score, likelihood, likelihood_cls = compute_likelihood(
            appearances=cnt,
            probed_ssids=probed,
            is_randomized=bool(device.is_randomized),
            manufacturer=device.manufacturer or "",
        )
        top_enriched.append(
            {
                "device": device,
                "cnt": cnt,
                "probed_ssids": sorted(probed),
                "likelihood": likelihood,
                "likelihood_cls": likelihood_cls,
            }
        )

    # Collapse cluster MACs into single rows
    seen_fps = {}  # fingerprint_id → index in top_grouped
    top_grouped = []
    for item in top_enriched:
        fp_id = item["device"].fingerprint_id
        if fp_id and fp_id in seen_fps:
            # Merge into existing cluster row
            existing = top_grouped[seen_fps[fp_id]]
            existing["cnt"] += item["cnt"]
            existing["cluster_extra"] += 1
            existing["probed_ssids"] = sorted(
                set(existing["probed_ssids"]) | set(item["probed_ssids"])
            )
        elif fp_id:
            # First MAC in this cluster
            seen_fps[fp_id] = len(top_grouped)
            item["cluster_extra"] = 0
            item["cluster_id"] = fp_id
            top_grouped.append(item)
        else:
            # Non-clustered device
            item["cluster_extra"] = 0
            item["cluster_id"] = None
            top_grouped.append(item)

    ignored_count = len(baseline_macs)
    fingerprint_clusters = (
        db.query(func.count(func.distinct(Device.fingerprint_id)))
        .filter(Device.fingerprint_id.isnot(None))
        .scalar()
    ) or 0

    return render_template(
        "dashboard.html",
        total_devices=total_devices,
        active_devices=active_devices,
        active_window_minutes=active_window_minutes,
        total_appearances=total_appearances,
        sensors_online=sensors_online,
        sensors_total=sensors_total,
        last_run=last_run,
        new_24h=new_24h,
        probes_24h=probes_24h,
        recurring_24h=recurring_24h,
        top_persistent=top_grouped,
        show_ignored=show_ignored,
        ignored_count=ignored_count,
        fingerprint_clusters=fingerprint_clusters,
    )


@bp.route("/partials/status-bar")
def status_bar():
    db = get_db()
    now = datetime.utcnow()

    latest_appearance = db.query(Appearance).order_by(Appearance.timestamp.desc()).first()
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
        labels=[r.bucket + ":00Z" for r in rows],
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
    from web.routes.devices import _device_ssid_sets, _device_enrichment, _build_cluster_info

    db = get_db()
    page = request.args.get("page", 1, type=int)
    show_ignored = request.args.get("show_ignored", "0") == "1"
    per_page = 25
    offset = (page - 1) * per_page

    query = db.query(Device)
    hide_unknown = current_app.config.get("HIDE_UNKNOWN_MANUFACTURER", False)
    if hide_unknown:
        query = query.filter(
            Device.manufacturer != "Unknown",
            Device.manufacturer != "",
            Device.manufacturer.isnot(None),
        )
    if not show_ignored:
        baseline_macs = get_baseline_macs()
        if baseline_macs:
            query = query.filter(func.upper(Device.mac).notin_(baseline_macs))

    total = query.count()
    devices = query.order_by(Device.last_seen.desc()).offset(offset).limit(per_page).all()

    if _is_htmx():
        device_ids = [d.id for d in devices]
        device_ssids = _device_ssid_sets(db, device_ids)
        enrichment = _device_enrichment(db, devices)
        cluster_info = _build_cluster_info(db, devices)
        return render_template(
            "partials/device_list.html",
            devices=devices,
            page=page,
            total=total,
            per_page=per_page,
            device_ssids=device_ssids,
            enrichment=enrichment,
            cluster_info=cluster_info,
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
    socketio.emit(
        "status_update",
        {
            "devices": db.query(Device).count(),
            "sensors": db.query(Sensor).filter(Sensor.status == "online").count(),
        },
    )
