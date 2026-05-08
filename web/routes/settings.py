"""Settings blueprint — application config, ignore lists, and credentials."""

import json
import os
from pathlib import Path

from flask import (
    Blueprint,
    render_template,
    request,
    flash,
    redirect,
    url_for,
    current_app,
)
from flask_login import login_required

from cyt.scoring import compute_likelihood

bp = Blueprint("settings", __name__, url_prefix="/settings")

# Baked-in default config (may be read-only in Docker)
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.json"
# Writable override location on the persistent data volume
_OVERRIDE_CONFIG_PATH = Path("/data/cyt/config.json")


def _config_save_path() -> Path:
    """Return the writable config path — prefer the data volume, fall back to app dir."""
    if _OVERRIDE_CONFIG_PATH.parent.is_dir():
        return _OVERRIDE_CONFIG_PATH
    return _DEFAULT_CONFIG_PATH


@bp.before_request
@login_required
def require_login():
    pass


def _read_ignore_list(path: Path) -> list:
    if path.is_file():
        try:
            with open(path) as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [m for m in data if isinstance(m, str)]
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _write_ignore_list(path: Path, data: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = [m for m in data if isinstance(m, str)]
    with open(path, "w") as f:
        json.dump(clean, f, indent=2)


def get_baseline_macs():
    """Return a set of upper-cased MACs from the ignore list. Importable by other routes."""
    from flask import current_app
    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    mac_path = base / ignore_cfg.get("mac", "ignore_lists/mac_list.json")
    return {m.upper() for m in _read_ignore_list(mac_path)}


@bp.route("/")
def index():
    from web.extensions import get_db
    from cyt.models import Device

    cfg = current_app.config["RAW_CONFIG"]
    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent

    mac_path = base / ignore_cfg.get("mac", "ignore_lists/maclist.json")
    ssid_path = base / ignore_cfg.get("ssid", "ignore_lists/ssidlist.json")

    mac_list = _read_ignore_list(mac_path)
    ssid_list = _read_ignore_list(ssid_path)

    db = get_db()
    total_devices = db.query(Device).count()

    # Collect scheduler job info
    from cyt.tasks import scheduler

    jobs = []
    if scheduler.running:
        for job in scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.id.replace("_", " ").title(),
                    "next_run": job.next_run_time,
                    "trigger": str(job.trigger),
                }
            )

    return render_template(
        "settings.html",
        config=cfg,
        mac_count=len(mac_list),
        ssid_count=len(ssid_list),
        scheduler_jobs=jobs,
        scheduler_running=scheduler.running,
        total_devices=total_devices,
    )


@bp.route("/ignore")
def ignore_lists():
    """Dedicated ignore list management page."""
    from web.extensions import get_db
    from cyt.models import Device

    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent

    mac_path = base / ignore_cfg.get("mac", "ignore_lists/maclist.json")
    ssid_path = base / ignore_cfg.get("ssid", "ignore_lists/ssidlist.json")

    mac_list = _read_ignore_list(mac_path)
    ssid_list = _read_ignore_list(ssid_path)

    db = get_db()
    total_devices = db.query(Device).count()

    # Build enrichment: manufacturer, appearances, probed SSIDs, foreign likelihood score
    mac_upper_set = {m.upper() for m in mac_list if isinstance(m, str)}
    mac_info = []
    if mac_upper_set:
        devices_in_baseline = db.query(Device).filter(Device.mac.in_(mac_upper_set)).all()
        device_map = {d.mac.upper(): d for d in devices_in_baseline}

        # Fetch appearance counts and all probed SSIDs per device in one query
        from cyt.models import Appearance
        from sqlalchemy import func
        appearance_rows = (
            db.query(Appearance.device_id, func.count(Appearance.id), Appearance.ssids_json)
            .filter(Appearance.device_id.in_([d.id for d in devices_in_baseline]))
            .all()
        )
        # Aggregate per device_id
        device_id_to_count = {}
        device_id_to_ssids = {}
        for row in appearance_rows:
            did, _cnt, ssids_json = row
            device_id_to_count[did] = device_id_to_count.get(did, 0) + 1
            if ssids_json:
                try:
                    import json as _json
                    for s in _json.loads(ssids_json):
                        if s and s.strip():
                            device_id_to_ssids.setdefault(did, set()).add(s.strip())
                except Exception:
                    pass

        for mac in mac_list:
            d = device_map.get(mac.upper())
            if d:
                app_count = device_id_to_count.get(d.id, 0)
                probed = sorted(device_id_to_ssids.get(d.id, set()))
                mfr = d.manufacturer or ""
                is_rand = bool(d.is_randomized)

                _score, likelihood, likelihood_cls = compute_likelihood(
                    appearances=app_count,
                    probed_ssids=probed,
                    is_randomized=is_rand,
                    manufacturer=mfr,
                )
            else:
                app_count = 0
                probed = []
                is_rand = False
                mfr = ""
                likelihood = "Unknown"
                likelihood_cls = "secondary"

            mac_info.append({
                "mac": mac,
                "manufacturer": mfr,
                "device_type": d.device_type if d else "",
                "last_seen": d.last_seen if d else None,
                "appearances": app_count,
                "probed_ssids": probed,
                "is_randomized": is_rand,
                "likelihood": likelihood,
                "likelihood_cls": likelihood_cls,
            })
    else:
        mac_info = []

    already_ignored = len(set(d.mac.upper() for d in db.query(Device.mac).all()) & mac_upper_set)
    not_yet_ignored = total_devices - already_ignored

    return render_template(
        "ignore_lists.html",
        mac_list=mac_list,
        mac_info=mac_info,
        ssid_list=ssid_list,
        total_devices=total_devices,
        not_yet_ignored=not_yet_ignored,
    )


@bp.route("/ignore/mac", methods=["POST"])
def update_mac_ignore():
    from cyt.input_validation import InputValidator

    raw = request.form.get("mac_list", "").strip()
    entries = [line.strip() for line in raw.splitlines() if line.strip()]

    validated = []
    for mac in entries:
        if InputValidator.validate_mac_address(mac):
            validated.append(mac.upper())
        else:
            flash(f"Invalid MAC skipped: {mac}", "warning")

    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    mac_path = base / ignore_cfg.get("mac", "ignore_lists/maclist.json")
    _write_ignore_list(mac_path, validated)
    flash(f"MAC ignore list updated ({len(validated)} entries).", "success")
    return redirect(url_for("settings.ignore_lists"))


@bp.route("/ignore/ssid", methods=["POST"])
def update_ssid_ignore():
    from cyt.input_validation import InputValidator

    raw = request.form.get("ssid_list", "").strip()
    entries = [line.strip() for line in raw.splitlines() if line.strip()]

    validated = []
    for ssid in entries:
        if InputValidator.validate_ssid(ssid):
            validated.append(ssid)
        else:
            flash(f"Invalid SSID skipped: {ssid}", "warning")

    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    ssid_path = base / ignore_cfg.get("ssid", "ignore_lists/ssidlist.json")
    _write_ignore_list(ssid_path, validated)
    flash(f"SSID ignore list updated ({len(validated)} entries).", "success")
    return redirect(url_for("settings.ignore_lists"))


@bp.route("/ignore/ssid/add", methods=["POST"])
def add_ssid_ignore():
    """Append one or more SSIDs to the ignore list (without replacing the whole list)."""
    from cyt.input_validation import InputValidator

    selected = request.form.getlist("ssids")
    if not selected:
        flash("No SSIDs selected.", "warning")
        return redirect(url_for("devices.ssids"))

    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    ssid_path = base / ignore_cfg.get("ssid", "ignore_lists/ssidlist.json")

    existing = _read_ignore_list(ssid_path)
    existing_set = set(existing)

    added = []
    for ssid in selected:
        ssid = ssid.strip()
        if not ssid or ssid in existing_set:
            continue
        if InputValidator.validate_ssid(ssid):
            existing.append(ssid)
            existing_set.add(ssid)
            added.append(ssid)
        else:
            flash(f"Invalid SSID skipped: {ssid}", "warning")

    if added:
        _write_ignore_list(ssid_path, existing)
        flash(f"Added {len(added)} SSID{'s' if len(added) != 1 else ''} to ignore list.", "success")
    else:
        flash("No new SSIDs were added (already ignored or invalid).", "info")

    return redirect(url_for("devices.ssids"))


@bp.route("/baseline", methods=["POST"])
def baseline_devices():
    """Capture all current DB devices as known — merge into MAC ignore list."""
    from web.extensions import get_db
    from cyt.models import Device
    from cyt.input_validation import InputValidator

    db = get_db()
    all_macs = [d.mac for d in db.query(Device.mac).all()]

    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    mac_path = base / ignore_cfg.get("mac", "ignore_lists/maclist.json")

    existing = set(_read_ignore_list(mac_path))
    new_macs = []
    for mac in all_macs:
        if InputValidator.validate_mac_address(mac) and mac.upper() not in {
            m.upper() for m in existing
        }:
            new_macs.append(mac.upper())

    merged = sorted(existing | set(new_macs))
    _write_ignore_list(mac_path, merged)

    flash(
        f"Baseline complete — {len(new_macs)} new device(s) added to ignore list "
        f"({len(merged)} total).",
        "success",
    )
    return redirect(url_for("settings.ignore_lists"))


@bp.route("/baseline/remove", methods=["POST"])
def baseline_remove():
    """Remove one MAC from the ignore/baseline list."""
    from cyt.input_validation import InputValidator

    mac = request.form.get("mac", "").strip()
    if not InputValidator.validate_mac_address(mac):
        flash(f"Invalid MAC: {mac}", "danger")
        return redirect(url_for("settings.ignore_lists"))

    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    mac_path = base / ignore_cfg.get("mac", "ignore_lists/maclist.json")

    current = _read_ignore_list(mac_path)
    updated = [m for m in current if m.upper() != mac.upper()]

    if len(updated) < len(current):
        _write_ignore_list(mac_path, updated)
        flash(f"Removed {mac.upper()} from ignore list.", "success")
    else:
        flash(f"{mac.upper()} was not in the ignore list.", "warning")

    return redirect(url_for("settings.ignore_lists"))


@bp.route("/baseline/clear", methods=["POST"])
def baseline_clear():
    """Remove all MACs from the ignore/baseline list."""
    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    mac_path = base / ignore_cfg.get("mac", "ignore_lists/maclist.json")

    old = _read_ignore_list(mac_path)
    _write_ignore_list(mac_path, [])
    flash(f"Baseline cleared — removed {len(old)} MAC(s) from ignore list.", "success")
    return redirect(url_for("settings.ignore_lists"))


@bp.route("/baseline/remove-selected", methods=["POST"])
def baseline_remove_selected():
    """Remove multiple selected MACs from the ignore/baseline list."""
    from cyt.input_validation import InputValidator

    selected = request.form.getlist("selected_macs")
    if not selected:
        flash("No devices selected.", "warning")
        return redirect(url_for("settings.ignore_lists"))

    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    mac_path = base / ignore_cfg.get("mac", "ignore_lists/maclist.json")

    remove_set = set()
    for mac in selected:
        if InputValidator.validate_mac_address(mac):
            remove_set.add(mac.upper())

    current = _read_ignore_list(mac_path)
    updated = [m for m in current if m.upper() not in remove_set]
    removed = len(current) - len(updated)
    _write_ignore_list(mac_path, updated)

    flash(f"Removed {removed} MAC(s) from ignore list.", "success")
    return redirect(url_for("settings.ignore_lists"))


@bp.route("/baseline/add-selected", methods=["POST"])
def baseline_add_selected():
    """Add multiple selected MACs to the ignore/baseline list. Redirects to referrer."""
    from cyt.input_validation import InputValidator

    selected = request.form.getlist("selected_macs")
    redirect_to = request.form.get("redirect", url_for("settings.ignore_lists"))
    if not selected:
        flash("No devices selected.", "warning")
        return redirect(redirect_to)

    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    mac_path = base / ignore_cfg.get("mac", "ignore_lists/maclist.json")

    current_list = _read_ignore_list(mac_path)
    existing = set(m.upper() for m in current_list)
    new_list = list(current_list)
    added = 0
    for mac in selected:
        if not InputValidator.validate_mac_address(mac):
            flash(f"Invalid MAC skipped: {mac}", "warning")
            continue
        if mac.upper() not in existing:
            new_list.append(mac.upper())
            existing.add(mac.upper())
            added += 1

    _write_ignore_list(mac_path, sorted(new_list))
    flash(f"Added {added} device(s) to ignore list.", "success")
    return redirect(redirect_to)


@bp.route("/config", methods=["POST"])
def update_config():
    """Save editable config values back to config.json."""
    cfg = _load_config()

    # --- Timing ---
    try:
        val = int(request.form.get("check_interval", 60))
        cfg.setdefault("timing", {})["check_interval"] = max(10, val)
    except (ValueError, TypeError):
        flash("Ingestion interval must be an integer.", "danger")

    try:
        val = int(request.form.get("analysis_interval_hours", 6))
        cfg.setdefault("timing", {})["analysis_interval_hours"] = max(1, val)
    except (ValueError, TypeError):
        flash("Analysis interval must be an integer.", "danger")

    try:
        val = int(request.form.get("cleanup_interval_hours", 24))
        cfg.setdefault("timing", {})["cleanup_interval_hours"] = max(1, val)
    except (ValueError, TypeError):
        flash("Cleanup interval must be an integer.", "danger")

    try:
        val = int(request.form.get("retention_days", 90))
        cfg.setdefault("timing", {})["retention_days"] = max(1, val)
    except (ValueError, TypeError):
        flash("Retention days must be an integer.", "danger")

    # --- Fingerprinting ---
    try:
        val = float(request.form.get("jaccard_threshold", 0.85))
        cfg.setdefault("fingerprinting", {})["jaccard_threshold"] = round(
            max(0.0, min(1.0, val)), 2
        )
    except (ValueError, TypeError):
        flash("Jaccard threshold must be a number 0–1.", "danger")

    try:
        val = int(request.form.get("min_ssids_for_fingerprint", 2))
        cfg.setdefault("fingerprinting", {})["min_ssids_for_fingerprint"] = max(1, val)
    except (ValueError, TypeError):
        flash("Min SSIDs must be an integer.", "danger")

    # --- Paths ---
    kismet_logs = request.form.get("kismet_logs", "").strip()
    if kismet_logs:
        cfg.setdefault("paths", {})["kismet_logs"] = kismet_logs

    reports_dir = request.form.get("reports_dir", "").strip()
    if reports_dir:
        cfg.setdefault("paths", {})["reports_dir"] = reports_dir

    # --- Sensor ---
    try:
        val = int(request.form.get("sync_interval_minutes", 5))
        cfg.setdefault("sensor", {})["sync_interval_minutes"] = max(1, val)
    except (ValueError, TypeError):
        pass

    smb_share = request.form.get("smb_share", "").strip()
    if smb_share:
        cfg.setdefault("sensor", {})["smb_share"] = smb_share

    # --- Display ---
    cfg.setdefault("display", {})["hide_unknown_manufacturer"] = (
        request.form.get("hide_unknown_manufacturer") == "on"
    )

    # Persist to config.json
    _save_config(cfg)

    # Reload into running app
    current_app.config["RAW_CONFIG"] = cfg
    current_app.config["KISMET_LOGS"] = cfg.get("paths", {}).get("kismet_logs", "")
    current_app.config["REPORTS_DIR"] = cfg.get("paths", {}).get(
        "reports_dir", "/data/reports"
    )
    current_app.config["JACCARD_THRESHOLD"] = cfg.get("fingerprinting", {}).get(
        "jaccard_threshold", 0.85
    )
    current_app.config["MIN_SSIDS_FOR_FINGERPRINT"] = cfg.get("fingerprinting", {}).get(
        "min_ssids_for_fingerprint", 2
    )
    current_app.config["TIMING"] = cfg.get("timing", {})
    current_app.config["HIDE_UNKNOWN_MANUFACTURER"] = cfg.get("display", {}).get(
        "hide_unknown_manufacturer", False
    )

    # Reschedule APScheduler jobs to match updated timing values
    _reschedule_jobs(cfg.get("timing", {}))

    flash("Configuration saved.", "success")
    return redirect(url_for("settings.index"))


def _load_config() -> dict:
    """Read config — merge baked-in defaults with writable overrides."""
    cfg = {}
    if _DEFAULT_CONFIG_PATH.exists():
        with open(_DEFAULT_CONFIG_PATH) as f:
            cfg = json.load(f)
    # Layer overrides on top (if they exist on the data volume)
    if _OVERRIDE_CONFIG_PATH.is_file():
        with open(_OVERRIDE_CONFIG_PATH) as f:
            overrides = json.load(f)
        _deep_merge(cfg, overrides)
    return cfg


def _save_config(cfg: dict) -> None:
    """Write config to the writable data volume."""
    save_path = _config_save_path()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge overrides into base dict (mutates base)."""
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _reschedule_jobs(timing: dict) -> None:
    """Reschedule running APScheduler jobs to match updated timing values."""
    from apscheduler.triggers.interval import IntervalTrigger
    from cyt.tasks import scheduler

    if not scheduler.running:
        return

    ingest_interval = timing.get("check_interval", 60)
    fp_multiplier = timing.get("list_update_interval", 5)
    fp_interval = ingest_interval * fp_multiplier
    analysis_hours = timing.get("analysis_interval_hours", 6)
    cleanup_hours = timing.get("cleanup_interval_hours", 24)

    try:
        scheduler.reschedule_job("kismet_ingestion", trigger=IntervalTrigger(seconds=ingest_interval))
    except Exception:
        pass

    try:
        scheduler.reschedule_job("ssid_fingerprinting", trigger=IntervalTrigger(seconds=fp_interval))
    except Exception:
        pass

    if analysis_hours > 0:
        try:
            scheduler.reschedule_job("scheduled_analysis", trigger=IntervalTrigger(hours=analysis_hours))
        except Exception:
            pass

    if cleanup_hours > 0:
        try:
            scheduler.reschedule_job("data_cleanup", trigger=IntervalTrigger(hours=cleanup_hours))
        except Exception:
            pass
        try:
            scheduler.reschedule_job("kismet_file_cleanup", trigger=IntervalTrigger(hours=cleanup_hours))
        except Exception:
            pass


@bp.route("/backfill-devices", methods=["POST"])
def backfill_devices():
    """Backfill is_randomized and manufacturer for all existing devices."""
    from web.extensions import get_db
    from cyt.models import Device
    from cyt.kismet_reader import is_locally_administered
    from cyt.oui_lookup import lookup_manufacturer

    db = get_db()
    devices = db.query(Device).all()
    rand_fixed = 0
    mfr_fixed = 0

    for d in devices:
        # Fix is_randomized
        expected = is_locally_administered(d.mac)
        if d.is_randomized != expected:
            d.is_randomized = expected
            rand_fixed += 1

        # Fix unknown manufacturer (skip randomized — won't have OUI)
        if (not d.manufacturer or d.manufacturer == "Unknown") and not expected:
            new_mfr = lookup_manufacturer(d.mac)
            if new_mfr:
                d.manufacturer = new_mfr
                mfr_fixed += 1

    db.commit()
    flash(
        f"Backfill complete: {rand_fixed} randomized flags fixed, "
        f"{mfr_fixed} manufacturers resolved.",
        "success",
    )
    return redirect(url_for("settings.index"))
