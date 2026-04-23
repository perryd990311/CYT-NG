"""Settings blueprint — application config, ignore lists, and credentials."""
import json
from pathlib import Path

from flask import (
    Blueprint, render_template, request, flash, redirect, url_for, current_app,
)
from flask_login import login_required

bp = Blueprint("settings", __name__, url_prefix="/settings")

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.json"


@bp.before_request
@login_required
def require_login():
    pass


def _read_ignore_list(path: Path) -> list:
    if path.is_file():
        with open(path) as f:
            return json.load(f)
    return []


def _write_ignore_list(path: Path, data: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


@bp.route("/")
def index():
    cfg = current_app.config["RAW_CONFIG"]
    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent

    mac_path = base / ignore_cfg.get("mac_list", "ignore_lists/mac_list.json")
    ssid_path = base / ignore_cfg.get("ssid_list", "ignore_lists/ssid_list.json")

    mac_list = _read_ignore_list(mac_path)
    ssid_list = _read_ignore_list(ssid_path)

    # Collect scheduler job info
    from cyt.tasks import scheduler
    jobs = []
    if scheduler.running:
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.id.replace("_", " ").title(),
                "next_run": job.next_run_time,
                "trigger": str(job.trigger),
            })

    return render_template(
        "settings.html",
        config=cfg,
        mac_list=mac_list,
        ssid_list=ssid_list,
        scheduler_jobs=jobs,
        scheduler_running=scheduler.running,
    )


@bp.route("/ignore/mac", methods=["POST"])
def update_mac_ignore():
    from cyt.input_validation import InputValidator

    raw = request.form.get("mac_list", "").strip()
    entries = [line.strip() for line in raw.splitlines() if line.strip()]

    validated = []
    for mac in entries:
        clean = InputValidator.validate_mac_address(mac)
        if clean:
            validated.append(clean)
        else:
            flash(f"Invalid MAC skipped: {mac}", "warning")

    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    mac_path = base / ignore_cfg.get("mac_list", "ignore_lists/mac_list.json")
    _write_ignore_list(mac_path, validated)
    flash(f"MAC ignore list updated ({len(validated)} entries).", "success")
    return redirect(url_for("settings.index"))


@bp.route("/ignore/ssid", methods=["POST"])
def update_ssid_ignore():
    from cyt.input_validation import InputValidator

    raw = request.form.get("ssid_list", "").strip()
    entries = [line.strip() for line in raw.splitlines() if line.strip()]

    validated = []
    for ssid in entries:
        clean = InputValidator.validate_ssid(ssid)
        if clean:
            validated.append(clean)
        else:
            flash(f"Invalid SSID skipped: {ssid}", "warning")

    ignore_cfg = current_app.config.get("IGNORE_LISTS", {})
    base = Path(current_app.root_path).parent
    ssid_path = base / ignore_cfg.get("ssid_list", "ignore_lists/ssid_list.json")
    _write_ignore_list(ssid_path, validated)
    flash(f"SSID ignore list updated ({len(validated)} entries).", "success")
    return redirect(url_for("settings.index"))


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
        cfg.setdefault("fingerprinting", {})["jaccard_threshold"] = round(max(0.0, min(1.0, val)), 2)
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

    # Persist to config.json
    _save_config(cfg)

    # Reload into running app
    current_app.config["RAW_CONFIG"] = cfg
    current_app.config["KISMET_LOGS"] = cfg.get("paths", {}).get("kismet_logs", "")
    current_app.config["REPORTS_DIR"] = cfg.get("paths", {}).get("reports_dir", "surveillance_reports")
    current_app.config["JACCARD_THRESHOLD"] = cfg.get("fingerprinting", {}).get("jaccard_threshold", 0.85)
    current_app.config["MIN_SSIDS_FOR_FINGERPRINT"] = cfg.get("fingerprinting", {}).get("min_ssids_for_fingerprint", 2)
    current_app.config["TIMING"] = cfg.get("timing", {})

    flash("Configuration saved.", "success")
    return redirect(url_for("settings.index"))


def _load_config() -> dict:
    """Read config.json from disk."""
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    return {}


def _save_config(cfg: dict) -> None:
    """Write config dict to config.json."""
    with open(_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
