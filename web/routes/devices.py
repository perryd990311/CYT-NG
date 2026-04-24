"""Devices blueprint — browse and inspect detected wireless devices."""
import json
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, abort, jsonify
from flask_login import login_required
from sqlalchemy import func

from web.extensions import get_db
from cyt.models import Device, Appearance, Sensor, Fingerprint
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
            func.row_number().over(
                partition_by=Appearance.device_id,
                order_by=Appearance.timestamp.desc()
            ).label("rn")
        )
        .filter(
            Appearance.device_id.in_(device_ids),
            Appearance.signal_dbm.isnot(None),
        )
        .subquery()
    )
    signal_rows = db.query(signal_sub.c.device_id, signal_sub.c.signal_dbm).filter(signal_sub.c.rn == 1).all()
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
    mac_list_path = os.environ.get("IGNORE_LISTS", "ignore_lists") + "/mac_list.json"
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
            "fingerprint": fp_info,
            "baseline": d.mac.upper() in baseline_macs,
            "notes": d.notes or "",
        }
    return result


@bp.route("/")
def index():
    db = get_db()
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()
    per_page = 50
    offset = (page - 1) * per_page

    query = db.query(Device)
    if search:
        # Sanitize search input
        safe = search.replace("%", "").replace("_", "")
        query = query.filter(
            Device.mac.ilike(f"%{safe}%")
            | Device.manufacturer.ilike(f"%{safe}%")
        )

    total = query.count()
    devices = (
        query.order_by(Device.last_seen.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    ssid_counts = _device_ssid_counts(db, [d.id for d in devices])
    device_ssids = _device_ssid_sets(db, [d.id for d in devices])
    enrichment = _device_enrichment(db, devices)
    new_threshold = datetime.utcnow() - timedelta(hours=24)

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
