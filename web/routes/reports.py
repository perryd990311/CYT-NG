"""Reports blueprint — list, view, and download analysis reports and KML files."""

from pathlib import Path

from flask import (
    Blueprint,
    render_template,
    send_file,
    abort,
    current_app,
)
from flask_login import login_required

from web.extensions import get_db
from cyt.models import AnalysisRun, Device

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.before_request
@login_required
def require_login():
    pass


@bp.route("/")
def index():
    db = get_db()
    total_devices = db.query(Device).count()
    runs = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.status == "completed")
        .order_by(AnalysisRun.started_at.desc())
        .limit(50)
        .all()
    )
    return render_template("reports.html", runs=runs, total_devices=total_devices)


@bp.route("/<int:run_id>/download")
def download(run_id):
    db = get_db()
    run = db.query(AnalysisRun).get(run_id)
    if not run or not run.report_path:
        abort(404)

    path = Path(run.report_path)
    if not path.is_absolute():
        path = Path(current_app.config["REPORTS_DIR"]) / path

    if not path.is_file():
        abort(404)

    return send_file(path, as_attachment=True)


@bp.route("/<int:run_id>/kml")
def download_kml(run_id):
    db = get_db()
    run = db.query(AnalysisRun).get(run_id)
    if not run or not run.kml_path:
        abort(404)

    path = Path(run.kml_path)
    if not path.is_absolute():
        path = Path(current_app.config["KML_DIR"]) / path

    if not path.is_file():
        abort(404)

    return send_file(path, as_attachment=True, mimetype="application/vnd.google-earth.kml+xml")
