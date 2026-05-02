"""Analysis blueprint — run surveillance analysis, view results, trends."""

import json
import threading
from collections import Counter
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    current_app,
)
from flask_login import login_required
from sqlalchemy import func

from web.extensions import get_db, socketio
from cyt.models import AnalysisRun, Device, Fingerprint, Appearance, Sensor

bp = Blueprint("analysis", __name__, url_prefix="/analysis")


@bp.before_request
@login_required
def require_login():
    pass


@bp.route("/")
def index():
    db = get_db()
    runs = db.query(AnalysisRun).order_by(AnalysisRun.started_at.desc()).limit(20).all()
    fingerprint_count = db.query(Fingerprint).count()
    return render_template("analysis.html", runs=runs, fingerprint_count=fingerprint_count)


def _execute_analysis(app, run_id):
    """Run analysis in a background thread with app context."""
    with app.app_context():
        from web.extensions import _Session
        from cyt.fingerprint import run_fingerprinting
        from cyt.tasks import _load_ssid_ignore_list

        session = _Session()
        run = session.query(AnalysisRun).get(run_id)
        try:
            threshold = app.config.get("JACCARD_THRESHOLD", 0.85)
            min_ssids = app.config.get("MIN_SSIDS_FOR_FINGERPRINT", 1)
            max_devices_per_ssid = app.config.get("MAX_DEVICES_PER_SSID", 20)
            ignored_ssids = _load_ssid_ignore_list(app)

            # Run SSID fingerprinting
            clusters, fps = run_fingerprinting(
                session,
                threshold=threshold,
                min_ssids=min_ssids,
                max_devices_per_ssid=max_devices_per_ssid,
                ignored_ssids=ignored_ssids,
            )

            # Expire cached objects so count() hits the DB fresh
            session.expire_all()
            devices_count = session.query(Device).count()
            persistent_count = (
                session.query(Device).filter(Device.fingerprint_id.isnot(None)).count()
            )

            run.devices_analyzed = devices_count
            run.persistent_devices = persistent_count
            run.status = "completed"
            run.finished_at = datetime.utcnow()
            session.commit()

            socketio.emit(
                "analysis_complete",
                {
                    "run_id": run_id,
                    "devices": devices_count,
                    "clusters": clusters,
                    "fingerprints": fps,
                },
            )
        except Exception as exc:
            run.status = "failed"
            run.finished_at = datetime.utcnow()
            session.commit()
            socketio.emit("analysis_complete", {"run_id": run_id, "error": str(exc)})
        finally:
            _Session.remove()


@bp.route("/run", methods=["POST"])
def run():
    """Kick off a new analysis run (fingerprinting + persistence scoring)."""
    db = get_db()
    run = AnalysisRun(
        trigger="manual",
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()

    app = current_app._get_current_object()
    thread = threading.Thread(target=_execute_analysis, args=(app, run.id), daemon=True)
    thread.start()

    flash("Analysis started — results will update when complete.", "success")
    return redirect(url_for("analysis.results", run_id=run.id))


@bp.route("/results/<int:run_id>")
def results(run_id):
    db = get_db()
    run = db.query(AnalysisRun).get(run_id)
    if not run:
        flash("Analysis run not found.", "danger")
        return redirect(url_for("analysis.index"))
    return render_template("analysis_results.html", run=run)


@bp.route("/trends")
def trends():
    """Long-term analytics view — aggregated stats over configurable window."""
    db = get_db()
    days = min(request.args.get("days", 30, type=int), 365)
    since = datetime.utcnow() - timedelta(days=days)

    # Daily device counts (unique MACs seen per day)
    daily_devices = (
        db.query(
            func.date(Appearance.timestamp).label("day"),
            func.count(func.distinct(Appearance.device_id)).label("devices"),
        )
        .filter(Appearance.timestamp >= since)
        .group_by("day")
        .order_by("day")
        .all()
    )

    # Daily appearance counts
    daily_appearances = (
        db.query(
            func.date(Appearance.timestamp).label("day"),
            func.count(Appearance.id).label("appearances"),
        )
        .filter(Appearance.timestamp >= since)
        .group_by("day")
        .order_by("day")
        .all()
    )

    # Analysis run history (for the overlay)
    runs = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.started_at >= since)
        .order_by(AnalysisRun.started_at.desc())
        .all()
    )

    # Top persistent devices (most appearances in window)
    top_devices = (
        db.query(
            Device.mac,
            Device.manufacturer,
            Device.is_randomized,
            func.count(Appearance.id).label("count"),
            func.min(Appearance.timestamp).label("first"),
            func.max(Appearance.timestamp).label("last"),
        )
        .join(Appearance, Device.id == Appearance.device_id)
        .filter(Appearance.timestamp >= since)
        .group_by(Device.id)
        .order_by(func.count(Appearance.id).desc())
        .limit(15)
        .all()
    )

    # Summary stats
    total_unique = (
        db.query(func.count(func.distinct(Appearance.device_id)))
        .filter(Appearance.timestamp >= since)
        .scalar()
    ) or 0

    total_sightings = (
        db.query(func.count(Appearance.id)).filter(Appearance.timestamp >= since).scalar()
    ) or 0

    new_devices = (db.query(func.count(Device.id)).filter(Device.first_seen >= since).scalar()) or 0

    return render_template(
        "analysis_trends.html",
        days=days,
        daily_devices=daily_devices,
        daily_appearances=daily_appearances,
        runs=runs,
        top_devices=top_devices,
        total_unique=total_unique,
        total_sightings=total_sightings,
        new_devices=new_devices,
    )


@bp.route("/trends/data")
def trends_data():
    """JSON endpoint for trends chart data."""
    db = get_db()
    days = min(request.args.get("days", 30, type=int), 365)
    since = datetime.utcnow() - timedelta(days=days)

    daily_devices = (
        db.query(
            func.date(Appearance.timestamp).label("day"),
            func.count(func.distinct(Appearance.device_id)).label("devices"),
        )
        .filter(Appearance.timestamp >= since)
        .group_by("day")
        .order_by("day")
        .all()
    )

    daily_appearances = (
        db.query(
            func.date(Appearance.timestamp).label("day"),
            func.count(Appearance.id).label("appearances"),
        )
        .filter(Appearance.timestamp >= since)
        .group_by("day")
        .order_by("day")
        .all()
    )

    return jsonify(
        labels=[str(r.day) for r in daily_devices],
        devices=[r.devices for r in daily_devices],
        appearances=[r.appearances for r in daily_appearances],
        days=days,
    )


@bp.route("/stats")
def stats():
    """Analysis statistics dashboard — all derived metrics from the data."""
    db = get_db()
    days = min(request.args.get("days", 30, type=int), 365)
    since = datetime.utcnow() - timedelta(days=days)

    # ── Summary stat cards ──
    total_devices = (
        db.query(func.count(func.distinct(Appearance.device_id)))
        .filter(Appearance.timestamp >= since)
        .scalar()
    ) or 0

    persistent_devices = (
        db.query(func.count(Device.id)).filter(Device.fingerprint_id.isnot(None)).scalar()
    ) or 0

    randomized_count = (
        db.query(func.count(Device.id))
        .filter(Device.is_randomized.is_(True))
        .join(Appearance, Device.id == Appearance.device_id)
        .filter(Appearance.timestamp >= since)
        .scalar()
    ) or 0
    randomization_pct = round(randomized_count / total_devices * 100) if total_devices else 0

    fingerprint_clusters = (
        db.query(func.count(func.distinct(Device.fingerprint_id)))
        .filter(Device.fingerprint_id.isnot(None))
        .scalar()
    ) or 0

    # Unique SSIDs — parse ssids_json from appearances
    ssid_rows = (
        db.query(Appearance.ssids_json)
        .filter(Appearance.timestamp >= since, Appearance.ssids_json.isnot(None))
        .all()
    )
    ssid_counter = Counter()
    for (raw,) in ssid_rows:
        try:
            ssids = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(ssids, list):
                for s in ssids:
                    if isinstance(s, str) and s:
                        ssid_counter[s] += 1
        except (json.JSONDecodeError, TypeError):
            pass
    unique_ssids = len(ssid_counter)

    total_appearances = (
        db.query(func.count(Appearance.id)).filter(Appearance.timestamp >= since).scalar()
    ) or 0
    avg_appearances = round(total_appearances / total_devices, 1) if total_devices else 0

    # ── Hourly activity pattern ──
    hourly = (
        db.query(
            func.strftime("%H", Appearance.timestamp).label("hour"),
            func.count(func.distinct(Appearance.device_id)).label("devices"),
        )
        .filter(Appearance.timestamp >= since)
        .group_by("hour")
        .order_by("hour")
        .all()
    )
    hourly_map = {r.hour: r.devices for r in hourly}
    hourly_labels = [str(h).zfill(2) for h in range(24)]
    hourly_data = [hourly_map.get(str(h).zfill(2), 0) for h in range(24)]

    # ── New devices per day ──
    new_per_day = (
        db.query(
            func.date(Device.first_seen).label("day"),
            func.count(Device.id).label("cnt"),
        )
        .filter(Device.first_seen >= since)
        .group_by("day")
        .order_by("day")
        .all()
    )
    new_day_labels = [str(r.day) for r in new_per_day]
    new_day_data = [r.cnt for r in new_per_day]

    # ── Top probed SSIDs ──
    # Count devices per SSID (from the counter, need device-level counts)
    ssid_device_counter = Counter()
    for (raw,) in ssid_rows:
        try:
            ssids = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(ssids, list):
                seen = set()
                for s in ssids:
                    if isinstance(s, str) and s and s not in seen:
                        ssid_device_counter[s] += 1
                        seen.add(s)
        except (json.JSONDecodeError, TypeError):
            pass

    # Get first/last seen per SSID from appearances
    # (simplified: use the ssid_counter keys and query timestamps)
    top_ssids = ssid_device_counter.most_common(15)

    # ── Signal strength distribution ──
    signal_buckets = [
        ("Very Close (-20 to -40)", -40, -20),
        ("Near (-40 to -60)", -60, -40),
        ("Medium (-60 to -75)", -75, -60),
        ("Far (-75 to -90)", -90, -75),
        ("Distant (< -90)", -200, -90),
    ]
    signal_data = []
    for label, lo, hi in signal_buckets:
        cnt = (
            db.query(func.count(func.distinct(Appearance.device_id)))
            .filter(
                Appearance.timestamp >= since,
                Appearance.signal_dbm.isnot(None),
                Appearance.signal_dbm >= lo,
                Appearance.signal_dbm <= hi,
            )
            .scalar()
        ) or 0
        signal_data.append({"label": label, "count": cnt, "min": lo, "max": hi})

    # ── Fingerprint clusters ──
    clusters = db.query(Fingerprint).order_by(Fingerprint.appearance_count.desc()).limit(10).all()
    cluster_info = []
    for fp in clusters:
        mac_count = (
            db.query(func.count(Device.id)).filter(Device.fingerprint_id == fp.id).scalar() or 0
        )
        try:
            pool = json.loads(fp.ssids_json) if fp.ssids_json else []
        except (json.JSONDecodeError, TypeError):
            pool = []
        # Confidence: same formula as clusters page
        ssid_count = len(pool)
        if mac_count >= 4 and ssid_count >= 5:
            confidence, conf_cls = "High", "danger"
        elif mac_count >= 3 and ssid_count >= 3:
            confidence, conf_cls = "Medium", "warning"
        else:
            confidence, conf_cls = "Low", "success"
        cluster_info.append(
            {
                "canonical_mac": fp.canonical_mac,
                "mac_count": mac_count,
                "ssids": pool,
                "first_seen": fp.first_seen,
                "last_seen": fp.last_seen,
                "appearances": fp.appearance_count,
                "confidence": confidence,
                "conf_cls": conf_cls,
            }
        )

    # ── Dwell time distribution ──
    # Per-device per-day dwell = max(timestamp) - min(timestamp)
    dwell_rows = (
        db.query(
            func.julianday(func.max(Appearance.timestamp))
            - func.julianday(func.min(Appearance.timestamp))
        )
        .filter(Appearance.timestamp >= since)
        .group_by(Appearance.device_id, func.date(Appearance.timestamp))
        .all()
    )
    dwell_buckets = {
        "<1 min": 0,
        "1-5 min": 0,
        "5-15 min": 0,
        "15-60 min": 0,
        "1-4 hr": 0,
        ">4 hr": 0,
    }
    for (delta_days,) in dwell_rows:
        if delta_days is None:
            continue
        mins = delta_days * 24 * 60
        if mins < 1:
            dwell_buckets["<1 min"] += 1
        elif mins < 5:
            dwell_buckets["1-5 min"] += 1
        elif mins < 15:
            dwell_buckets["5-15 min"] += 1
        elif mins < 60:
            dwell_buckets["15-60 min"] += 1
        elif mins < 240:
            dwell_buckets["1-4 hr"] += 1
        else:
            dwell_buckets[">4 hr"] += 1

    # ── Sensor coverage ──
    sensors = db.query(Sensor).all()
    sensor_stats = []
    for s in sensors:
        cnt = (
            db.query(func.count(Appearance.id))
            .filter(Appearance.sensor_id == s.id, Appearance.timestamp >= since)
            .scalar()
        ) or 0
        sensor_stats.append({"name": s.name, "status": s.status, "sightings": cnt})

    # Multi-sensor overlap (devices seen by 2+ sensors)
    if len(sensors) >= 2:
        overlap = (
            db.query(func.count())
            .select_from(
                db.query(Appearance.device_id)
                .filter(Appearance.timestamp >= since, Appearance.sensor_id.isnot(None))
                .group_by(Appearance.device_id)
                .having(func.count(func.distinct(Appearance.sensor_id)) >= 2)
                .subquery()
            )
            .scalar()
        ) or 0
    else:
        overlap = 0

    return render_template(
        "analysis_stats.html",
        days=days,
        total_devices=total_devices,
        persistent_devices=persistent_devices,
        randomization_pct=randomization_pct,
        fingerprint_clusters=fingerprint_clusters,
        unique_ssids=unique_ssids,
        avg_appearances=avg_appearances,
        hourly_labels=hourly_labels,
        hourly_data=hourly_data,
        new_day_labels=new_day_labels,
        new_day_data=new_day_data,
        top_ssids=top_ssids,
        signal_data=signal_data,
        cluster_info=cluster_info,
        dwell_buckets=dwell_buckets,
        sensor_stats=sensor_stats,
        overlap=overlap,
    )


@bp.route("/clusters")
def clusters():
    """List all fingerprint clusters with MAC count, SSID count, confidence."""
    db = get_db()

    # Single grouped query: only fingerprints with at least one linked device
    mac_counts = (
        db.query(Device.fingerprint_id, func.count(Device.id).label("mac_count"))
        .filter(Device.fingerprint_id.isnot(None))
        .group_by(Device.fingerprint_id)
        .all()
    )
    mac_count_map = {fp_id: cnt for fp_id, cnt in mac_counts}

    # Only load fingerprints that still have linked devices (no orphans)
    active_fp_ids = list(mac_count_map.keys())
    if not active_fp_ids:
        return render_template("clusters.html", clusters=[], total_macs=0)

    all_fps = (
        db.query(Fingerprint)
        .filter(Fingerprint.id.in_(active_fp_ids))
        .order_by(Fingerprint.last_seen.desc())
        .all()
    )

    # Get canonical device manufacturer for each fingerprint
    canonical_macs = [fp.canonical_mac for fp in all_fps]
    canonical_devices = {}
    if canonical_macs:
        for dev in db.query(Device).filter(Device.mac.in_(canonical_macs)).all():
            canonical_devices[dev.mac] = dev.manufacturer or "Unknown"

    cluster_list = []
    for fp in all_fps:
        mac_count = mac_count_map.get(fp.id, 0)
        manufacturer = canonical_devices.get(fp.canonical_mac, "Unknown")
        try:
            pool = json.loads(fp.ssids_json) if fp.ssids_json else []
        except (json.JSONDecodeError, TypeError):
            pool = []
        ssid_count = len(pool)

        # Confidence: High ≥ 4 MACs & ≥ 5 SSIDs, Medium ≥ 3 MACs & ≥ 3 SSIDs, else Low
        if mac_count >= 4 and ssid_count >= 5:
            confidence, conf_cls, conf_sort = "High", "danger", 3
        elif mac_count >= 3 and ssid_count >= 3:
            confidence, conf_cls, conf_sort = "Medium", "warning", 2
        else:
            confidence, conf_cls, conf_sort = "Low", "success", 1

        cluster_list.append({
            "id": fp.id,
            "mac_count": mac_count,
            "ssid_count": ssid_count,
            "sample_ssids": pool[:3],
            "extra_ssids": max(0, ssid_count - 3),
            "confidence": confidence,
            "conf_cls": conf_cls,
            "conf_sort": conf_sort,
            "first_seen": fp.first_seen,
            "last_seen": fp.last_seen,
            "appearances": fp.appearance_count or 0,
            "manufacturer": manufacturer,
        })

    total_macs = sum(c["mac_count"] for c in cluster_list)
    return render_template("clusters.html", clusters=cluster_list, total_macs=total_macs)


@bp.route("/clusters/<int:cluster_id>")
def cluster_detail(cluster_id):
    """Detail view for a single fingerprint cluster."""
    from flask import abort

    db = get_db()
    fp = db.query(Fingerprint).get(cluster_id)
    if not fp:
        abort(404)

    # Devices in this cluster
    devices = (
        db.query(Device)
        .filter(Device.fingerprint_id == fp.id)
        .order_by(Device.last_seen.desc())
        .all()
    )
    device_ids = [d.id for d in devices]

    # Appearance counts per device
    app_counts = {}
    ssid_sets = {}
    if device_ids:
        count_rows = (
            db.query(Appearance.device_id, func.count(Appearance.id).label("cnt"))
            .filter(Appearance.device_id.in_(device_ids))
            .group_by(Appearance.device_id)
            .all()
        )
        app_counts = {r.device_id: r.cnt for r in count_rows}

        # SSIDs per device
        ssid_rows = (
            db.query(Appearance.device_id, Appearance.ssids_json)
            .filter(Appearance.device_id.in_(device_ids), Appearance.ssids_json.isnot(None))
            .all()
        )
        from collections import defaultdict
        ssid_per_device = defaultdict(set)
        for did, raw in ssid_rows:
            try:
                for s in json.loads(raw):
                    if s:
                        ssid_per_device[did].add(s)
            except (json.JSONDecodeError, TypeError):
                pass
        ssid_sets = {did: len(ss) for did, ss in ssid_per_device.items()}

    device_info = []
    for d in devices:
        device_info.append({
            "mac": d.mac,
            "is_randomized": d.is_randomized,
            "manufacturer": d.manufacturer or "Unknown",
            "appearances": app_counts.get(d.id, 0),
            "first_seen": d.first_seen,
            "last_seen": d.last_seen,
            "ssid_count": ssid_sets.get(d.id, 0),
        })

    total_appearances = sum(di["appearances"] for di in device_info)

    # Parse shared SSID pool
    try:
        ssid_pool = json.loads(fp.ssids_json) if fp.ssids_json else []
    except (json.JSONDecodeError, TypeError):
        ssid_pool = []

    # Days active
    days_active = 0
    if fp.first_seen and fp.last_seen:
        days_active = max(1, round((fp.last_seen - fp.first_seen).total_seconds() / 86400))

    # Confidence score
    mac_count = len(devices)
    ssid_count = len(ssid_pool)
    if mac_count >= 4 and ssid_count >= 5:
        confidence, conf_cls = "High", "danger"
    elif mac_count >= 3 and ssid_count >= 3:
        confidence, conf_cls = "Medium", "warning"
    else:
        confidence, conf_cls = "Low", "success"

    # Sensor breakdown
    sensor_stats = []
    if device_ids:
        sensor_rows = (
            db.query(Sensor.name, Sensor.status, func.count(Appearance.id).label("cnt"))
            .join(Appearance, Sensor.id == Appearance.sensor_id)
            .filter(Appearance.device_id.in_(device_ids))
            .group_by(Sensor.id)
            .order_by(func.count(Appearance.id).desc())
            .all()
        )
        sensor_stats = [{"name": r.name, "status": r.status, "count": r.cnt} for r in sensor_rows]

    # Daily activity (last 7 days)
    since_7d = datetime.utcnow() - timedelta(days=7)
    daily_rows = (
        db.query(
            func.date(Appearance.timestamp).label("day"),
            func.count(Appearance.id).label("cnt"),
        )
        .filter(Appearance.device_id.in_(device_ids), Appearance.timestamp >= since_7d)
        .group_by("day")
        .order_by("day")
        .all()
    )
    daily_labels = [str(r.day) for r in daily_rows]
    daily_data = [r.cnt for r in daily_rows]

    return render_template(
        "cluster_detail.html",
        fp=fp,
        devices=device_info,
        ssid_pool=ssid_pool,
        total_appearances=total_appearances,
        days_active=days_active,
        confidence=confidence,
        conf_cls=conf_cls,
        sensor_stats=sensor_stats,
        daily_labels=daily_labels,
        daily_data=daily_data,
    )


@bp.route("/long-term")
def long_term():
    """Show devices present for 2+ days that are NOT already in the baseline."""
    from web.routes.settings import get_baseline_macs

    db = get_db()
    min_days = max(request.args.get("days", 2, type=int), 1)
    baseline_macs = get_baseline_macs()

    all_devices = (
        db.query(Device)
        .filter(
            Device.first_seen.isnot(None),
            Device.last_seen.isnot(None),
        )
        .all()
    )

    min_delta = timedelta(days=min_days)
    long_term_devices = []
    device_ids = []
    for d in all_devices:
        if d.last_seen - d.first_seen >= min_delta and d.mac.upper() not in baseline_macs:
            device_ids.append(d.id)
            long_term_devices.append({"device": d, "appearances": 0, "days_seen": 0})

    # Batch-fetch appearance counts
    if device_ids:
        count_rows = (
            db.query(Appearance.device_id, func.count(Appearance.id).label("cnt"))
            .filter(Appearance.device_id.in_(device_ids))
            .group_by(Appearance.device_id)
            .all()
        )
        counts = {r.device_id: r.cnt for r in count_rows}
        for entry in long_term_devices:
            d = entry["device"]
            entry["appearances"] = counts.get(d.id, 0)
            entry["days_seen"] = round((d.last_seen - d.first_seen).total_seconds() / 86400, 1)

    long_term_devices.sort(key=lambda x: x["days_seen"], reverse=True)

    return render_template(
        "analysis_long_term.html",
        devices=long_term_devices,
        min_days=min_days,
        baseline_count=len(baseline_macs),
    )
