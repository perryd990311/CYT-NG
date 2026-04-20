"""Analysis blueprint — run surveillance analysis, view results."""
import threading
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required

from web.extensions import get_db, socketio
from cyt.models import AnalysisRun, Device, Fingerprint

bp = Blueprint("analysis", __name__, url_prefix="/analysis")


@bp.before_request
@login_required
def require_login():
    pass


@bp.route("/")
def index():
    db = get_db()
    runs = (
        db.query(AnalysisRun)
        .order_by(AnalysisRun.started_at.desc())
        .limit(20)
        .all()
    )
    fingerprint_count = db.query(Fingerprint).count()
    return render_template("analysis.html", runs=runs, fingerprint_count=fingerprint_count)


def _execute_analysis(app, run_id):
    """Run analysis in a background thread with app context."""
    with app.app_context():
        from web.extensions import _Session
        from cyt.fingerprint import run_fingerprinting

        session = _Session()
        run = session.query(AnalysisRun).get(run_id)
        try:
            threshold = app.config.get("JACCARD_THRESHOLD", 0.85)
            min_ssids = app.config.get("MIN_SSIDS_FOR_FINGERPRINT", 2)

            # Run SSID fingerprinting
            clusters, fps = run_fingerprinting(session, threshold=threshold, min_ssids=min_ssids)

            devices_count = session.query(Device).count()
            persistent_count = session.query(Device).filter(Device.fingerprint_id.isnot(None)).count()

            run.devices_analyzed = devices_count
            run.persistent_devices = persistent_count
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            session.commit()

            socketio.emit("analysis_complete", {
                "run_id": run_id,
                "devices": devices_count,
                "clusters": clusters,
                "fingerprints": fps,
            })
        except Exception as exc:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
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
        started_at=datetime.now(timezone.utc),
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
