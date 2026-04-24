"""Devices blueprint — browse and inspect detected wireless devices."""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, abort, jsonify
from flask_login import login_required
from sqlalchemy import func

from web.extensions import get_db
from cyt.models import Device, Appearance
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
    new_threshold = datetime.now(timezone.utc) - timedelta(hours=24)

    if request.headers.get("HX-Request") == "true":
        return render_template(
            "partials/device_list.html",
            devices=devices,
            page=page,
            total=total,
            per_page=per_page,
            ssid_counts=ssid_counts,
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
    since = datetime.now(timezone.utc) - timedelta(days=days)

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
    since = datetime.now(timezone.utc) - timedelta(days=days)

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
