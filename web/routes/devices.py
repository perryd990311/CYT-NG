"""Devices blueprint — browse and inspect detected wireless devices."""

import json
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, abort, jsonify
from flask_login import login_required
from sqlalchemy import func

from web.extensions import get_db
from cyt.models import Device, Appearance, Sensor
from cyt.input_validation import InputValidator

bp = Blueprint("devices", __name__, url_prefix="/devices")


@bp.before_request
@login_required
def require_login():
    pass


def _device_ssid_counts(db, device_ids):
    """Return {device_id: ssid_count} for a list of device IDs."""
    if not device_ids:
        return {}
    rows = (
        db.query(Appearance.device_id, Appearance.ssids_json)
        .filter(Appearance.device_id.in_(device_ids), Appearance.ssids_json.isnot(None))
        .all()
    )
    counts = defaultdict(set)
    for device_id, ssids_json in rows:
        try:
            for ssid in json.loads(ssids_json):
                if ssid:
                    counts[device_id].add(ssid)
        except (json.JSONDecodeError, TypeError):
            pass
    return {did: len(ssids) for did, ssids in counts.items()}


def _device_ssid_sets(db, device_ids):
    """Return {device_id: sorted_ssid_list} for a list of device IDs."""
    if not device_ids:
        return {}
    rows = (
        db.query(Appearance.device_id, Appearance.ssids_json)
        .filter(Appearance.device_id.in_(device_ids), Appearance.ssids_json.isnot(None))
        .all()
    )
    sets = defaultdict(set)
    for device_id, ssids_json in rows:
        try:
            for ssid in json.loads(ssids_json):
                if ssid:
                    sets[device_id].add(ssid)
        except (json.JSONDecodeError, TypeError):
            pass
    return {did: sorted(ssids) for did, ssids in sets.items()}


def _device_enrichment(db, devices):
    """Return {device_id: dict} with popup enrichment data."""
    if not devices:
        return {}
    device_ids = [d.id for d in devices]

    # Appearance counts
    count_rows = (
        db.query(Appearance.device_id, func.count(Appearance.id).label("cnt"))
        .filter(Appearance.device_id.in_(device_ids))
        .group_by(Appearance.device_id)
        .all()
    )
    counts = {r.device_id: r.cnt for r in count_rows}

    # Last signal strength per device
    signal_sub = (
        db.query(
            Appearance.device_id,
            Appearance.signal_dbm,
            func.row_number()
            .over(partition_by=Appearance.device_id, order_by=Appearance.timestamp.desc())
            .label("rn"),
        )
        .filter(
            Appearance.device_id.in_(device_ids),
            Appearance.signal_dbm.isnot(None),
        )
        .subquery()
    )
    signal_rows = (
        db.query(signal_sub.c.device_id, signal_sub.c.signal_dbm).filter(signal_sub.c.rn == 1).all()
    )
    signals = {r.device_id: r.signal_dbm for r in signal_rows}

    # Sensors per device
    sensor_rows = (
        db.query(Appearance.device_id, Sensor.name)
        .join(Sensor, Appearance.sensor_id == Sensor.id)
        .filter(Appearance.device_id.in_(device_ids))
        .distinct()
        .all()
    )
    sensors = defaultdict(list)
    for did, sname in sensor_rows:
        sensors[did].append(sname)

    # Baseline MAC list
    import os

    baseline_macs = set()
    mac_list_path = os.environ.get("IGNORE_LISTS", "ignore_lists") + "/maclist.json"
    try:
        with open(mac_list_path) as f:
            data = json.load(f)
            if isinstance(data, dict):
                items = data.get("macs", [])
            elif isinstance(data, list):
                items = data
            else:
                items = []
            baseline_macs = {m.upper() for m in items if isinstance(m, str)}
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        pass

    result = {}
    for d in devices:
        # Time span
        span = ""
        if d.first_seen and d.last_seen:
            delta = d.last_seen - d.first_seen
            total_secs = int(delta.total_seconds())
            if total_secs < 60:
                span = f"{total_secs}s"
            elif total_secs < 3600:
                span = f"{total_secs // 60}m"
            elif total_secs < 86400:
                span = f"{total_secs // 3600}h {(total_secs % 3600) // 60}m"
            else:
                span = f"{total_secs // 86400}d {(total_secs % 86400) // 3600}h"

        # Fingerprint info
        fp_info = ""
        if d.fingerprint_id and d.fingerprint:
            fp_ssids = []
            try:
                fp_ssids = json.loads(d.fingerprint.ssids_json)
            except (json.JSONDecodeError, TypeError):
                pass
            linked = len(d.fingerprint.devices) if d.fingerprint.devices else 0
            fp_info = f"Cluster #{d.fingerprint_id} ({linked} MACs, {len(fp_ssids)} SSIDs)"

        sig = signals.get(d.id)
        sig_str = ""
        if sig is not None:
            if sig >= -30:
                sig_str = f"{sig} dBm (excellent)"
            elif sig >= -50:
                sig_str = f"{sig} dBm (strong)"
            elif sig >= -70:
                sig_str = f"{sig} dBm (fair)"
            else:
                sig_str = f"{sig} dBm (weak)"

        result[d.id] = {
            "appearances": counts.get(d.id, 0),
            "span": span,
            "sensors": ", ".join(sorted(sensors.get(d.id, []))),
            "signal": sig_str,
            "signal_raw": signals.get(d.id),
            "fingerprint": fp_info,
            "baseline": d.mac.upper() in baseline_macs,
            "notes": d.notes or "",
        }
    return result


# Allowed sort columns — whitelist to prevent SQL injection
_SORT_COLUMNS = {
    "mac": Device.mac,
    "type": Device.device_type,
    "manufacturer": Device.manufacturer,
    "first_seen": Device.first_seen,
    "last_seen": Device.last_seen,
}


@bp.route("/")
def index():
    from web.routes.settings import get_baseline_macs

    db = get_db()
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()
    show_ignored = request.args.get("show_ignored", "0") == "1"
    sort_col = request.args.get("sort", "last_seen")
    sort_dir = request.args.get("dir", "desc")
    signal_min = request.args.get("signal_min", type=int)
    signal_max = request.args.get("signal_max", type=int)
    per_page = 50
    offset = (page - 1) * per_page

    query = db.query(Device)
    if search:
        # Sanitize search input
        safe = search.replace("%", "").replace("_", "")
        query = query.filter(Device.mac.ilike(f"%{safe}%") | Device.manufacturer.ilike(f"%{safe}%"))

    # Signal strength filter — find devices with appearances in the dBm range
    if signal_min is not None or signal_max is not None:
        signal_sub = db.query(Appearance.device_id).filter(Appearance.signal_dbm.isnot(None))
        if signal_min is not None:
            signal_sub = signal_sub.filter(Appearance.signal_dbm >= signal_min)
        if signal_max is not None:
            signal_sub = signal_sub.filter(Appearance.signal_dbm <= signal_max)
        signal_device_ids = signal_sub.distinct().subquery()
        query = query.filter(Device.id.in_(db.query(signal_device_ids.c.device_id)))

    baseline_macs = get_baseline_macs()
    if not show_ignored and baseline_macs:
        query = query.filter(Device.mac.notin_(baseline_macs))

    total = query.count()

    # Apply sort — whitelist-validated column, or subquery for ssids
    if sort_col == "ssids":
        # Subquery: count distinct SSIDs per device from appearances
        ssid_sub = (
            db.query(
                Appearance.device_id,
                func.count(func.distinct(Appearance.ssids_json)).label("ssid_cnt"),
            )
            .filter(Appearance.ssids_json.isnot(None))
            .group_by(Appearance.device_id)
            .subquery()
        )
        query = query.outerjoin(ssid_sub, Device.id == ssid_sub.c.device_id)
        order_expr = ssid_sub.c.ssid_cnt
        order = order_expr.asc() if sort_dir == "asc" else order_expr.desc()
        # nulls (no SSIDs) sort last
        from sqlalchemy import case

        devices = (
            query.order_by(
                case((order_expr.is_(None), 1), else_=0),
                order,
            )
            .offset(offset)
            .limit(per_page)
            .all()
        )
    else:
        col = _SORT_COLUMNS.get(sort_col, Device.last_seen)
        order = col.asc() if sort_dir == "asc" else col.desc()
        devices = query.order_by(order).offset(offset).limit(per_page).all()

    ssid_counts = _device_ssid_counts(db, [d.id for d in devices])
    device_ssids = _device_ssid_sets(db, [d.id for d in devices])
    enrichment = _device_enrichment(db, devices)
    new_threshold = datetime.utcnow() - timedelta(hours=24)

    sort_ctx = {"sort": sort_col, "dir": sort_dir}

    if request.headers.get("HX-Request") == "true":
        return render_template(
            "partials/device_list.html",
            devices=devices,
            page=page,
            total=total,
            per_page=per_page,
            ssid_counts=ssid_counts,
            device_ssids=device_ssids,
            enrichment=enrichment,
            new_threshold=new_threshold,
            **sort_ctx,
        )

    return render_template(
        "devices.html",
        devices=devices,
        page=page,
        total=total,
        per_page=per_page,
        search=search,
        ssid_counts=ssid_counts,
        device_ssids=device_ssids,
        enrichment=enrichment,
        new_threshold=new_threshold,
        show_ignored=show_ignored,
        ignored_count=len(baseline_macs),
        signal_min=signal_min,
        signal_max=signal_max,
        **sort_ctx,
    )


@bp.route("/<mac>")
def detail(mac):
    if not InputValidator.validate_mac_address(mac):
        abort(400, "Invalid MAC address format.")

    db = get_db()
    device = db.query(Device).filter_by(mac=mac.upper()).first()
    if not device:
        abort(404)

    appearances = (
        db.query(Appearance)
        .filter_by(device_id=device.id)
        .order_by(Appearance.timestamp.desc())
        .limit(100)
        .all()
    )

    # Parse SSID lists for display
    ssid_set = set()
    for a in appearances:
        if a.ssids_json:
            try:
                ssid_set.update(json.loads(a.ssids_json))
            except (json.JSONDecodeError, TypeError):
                pass

    return render_template(
        "device_detail.html",
        device=device,
        appearances=appearances,
        ssids=sorted(ssid_set),
        total_appearances=db.query(Appearance).filter_by(device_id=device.id).count(),
    )


@bp.route("/<mac>/history")
def history(mac):
    """Return appearance counts bucketed by hour for Chart.js timeline."""
    if not InputValidator.validate_mac_address(mac):
        abort(400, "Invalid MAC address format.")

    db = get_db()
    device = db.query(Device).filter_by(mac=mac.upper()).first()
    if not device:
        abort(404)

    # Default to 7 days, accept ?days=N (max 90)
    days = min(request.args.get("days", 7, type=int), 90)
    since = datetime.utcnow() - timedelta(days=days)

    rows = (
        db.query(
            func.strftime("%Y-%m-%d %H:00", Appearance.timestamp).label("bucket"),
            func.count(Appearance.id).label("cnt"),
        )
        .filter(Appearance.device_id == device.id, Appearance.timestamp >= since)
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )

    return jsonify(
        labels=[r.bucket for r in rows],
        data=[r.cnt for r in rows],
        days=days,
    )


@bp.route("/ssids")
def ssids():
    """Global view of all probed SSIDs with device counts and last-seen times."""
    db = get_db()
    days = min(request.args.get("days", 7, type=int), 90)
    since = datetime.utcnow() - timedelta(days=days)

    rows = (
        db.query(Appearance.ssids_json, Appearance.device_id, Appearance.timestamp)
        .filter(Appearance.timestamp >= since, Appearance.ssids_json.isnot(None))
        .all()
    )

    ssid_data = defaultdict(lambda: {"devices": set(), "count": 0, "last_seen": None})
    for ssids_json, device_id, ts in rows:
        try:
            parsed = json.loads(ssids_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for ssid in parsed:
            if not ssid:
                continue
            entry = ssid_data[ssid]
            entry["devices"].add(device_id)
            entry["count"] += 1
            if entry["last_seen"] is None or (ts and ts > entry["last_seen"]):
                entry["last_seen"] = ts

    ssid_list = sorted(
        [
            {
                "ssid": ssid,
                "device_count": len(info["devices"]),
                "probe_count": info["count"],
                "last_seen": info["last_seen"],
            }
            for ssid, info in ssid_data.items()
        ],
        key=lambda x: x["device_count"],
        reverse=True,
    )

    return render_template("ssids.html", ssids=ssid_list, days=days)
