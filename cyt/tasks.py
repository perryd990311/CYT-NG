"""
Background task scheduler for CYT-NG.

Runs periodic Kismet ingestion and fingerprint analysis using APScheduler.
Integrates with the Flask app context and emits SocketIO events on completion.
"""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(daemon=True)


def _run_ingestion(app):
    """Ingest new data from .kismet files."""
    with app.app_context():
        from web.extensions import get_db, _Session
        from cyt.kismet_reader import ingest_all
        from cyt.models import Sensor

        kismet_path = app.config.get("KISMET_LOGS", "")
        if not kismet_path:
            logger.warning("KISMET_LOGS not configured — skipping ingestion")
            return

        pattern = f"{kismet_path}/**/*.kismet" if not kismet_path.endswith("*") else kismet_path

        session = _Session()
        try:
            ingest_all(pattern, lambda: session)
            logger.info("Kismet ingestion completed")
        except Exception:
            logger.exception("Kismet ingestion failed")
        finally:
            _Session.remove()


def _run_fingerprinting(app):
    """Run SSID-pool fingerprinting analysis."""
    with app.app_context():
        from web.extensions import get_db, _Session
        from cyt.fingerprint import run_fingerprinting

        threshold = app.config.get("JACCARD_THRESHOLD", 0.85)
        min_ssids = app.config.get("MIN_SSIDS_FOR_FINGERPRINT", 2)

        session = _Session()
        try:
            clusters, fps = run_fingerprinting(session, threshold=threshold, min_ssids=min_ssids)
            logger.info("Fingerprinting: %d clusters, %d fingerprints", clusters, fps)

            # Notify connected clients
            from web.extensions import socketio
            socketio.emit("fingerprint_update", {
                "clusters": clusters,
                "fingerprints": fps,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            logger.exception("Fingerprinting failed")
        finally:
            _Session.remove()


def init_scheduler(app):
    """
    Configure and start the background scheduler.

    Reads intervals from app.config["TIMING"].
    """
    if scheduler.running:
        return

    timing = app.config.get("TIMING", {})
    ingest_interval = timing.get("check_interval", 60)
    # Run fingerprinting less frequently (every 5 ingestion cycles by default)
    fp_multiplier = timing.get("list_update_interval", 5)
    fp_interval = ingest_interval * fp_multiplier

    scheduler.add_job(
        _run_ingestion,
        "interval",
        seconds=ingest_interval,
        args=[app],
        id="kismet_ingestion",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_fingerprinting,
        "interval",
        seconds=fp_interval,
        args=[app],
        id="ssid_fingerprinting",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started: ingestion every %ds, fingerprinting every %ds",
        ingest_interval, fp_interval,
    )
