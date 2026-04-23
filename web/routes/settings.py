"""Settings blueprint — application config, ignore lists, and credentials."""
import json
from pathlib import Path

from flask import (
    Blueprint, render_template, request, flash, redirect, url_for, current_app,
)
from flask_login import login_required

bp = Blueprint("settings", __name__, url_prefix="/settings")


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
