"""Devices blueprint — browse and inspect detected wireless devices."""
import json

from flask import Blueprint, render_template, request, abort
from flask_login import login_required

from web.extensions import get_db
from cyt.models import Device, Appearance
from cyt.input_validation import InputValidator

bp = Blueprint("devices", __name__, url_prefix="/devices")


@bp.before_request
@login_required
def require_login():
    pass


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

    if request.headers.get("HX-Request") == "true":
        return render_template(
            "partials/device_list.html",
            devices=devices,
            page=page,
            total=total,
            per_page=per_page,
        )

    return render_template(
        "devices.html",
        devices=devices,
        page=page,
        total=total,
        per_page=per_page,
        search=search,
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
    )
