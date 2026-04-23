"""
Background task scheduler for CYT-NG.

Runs periodic Kismet ingestion, fingerprint analysis, scheduled surveillance
analysis, and data cleanup using APScheduler.
Integrates with the Flask app context and emits SocketIO events on completion.
"""
import logging
import os
from datetime import datetime, timezone, timedelta

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

        # Update Sensor.last_seen from .last_sync heartbeat files.
        # kismet_sync.sh writes {kismet_path}/{local_hostname}/.last_sync
        # Match on sensor.local_hostname first, fall back to sensor.hostname.
        session = _Session()
        try:
            if os.path.isdir(kismet_path):
                updated = 0
                for entry in os.scandir(kismet_path):
                    if not entry.is_dir():
                        continue
                    sync_file = os.path.join(entry.path, ".last_sync")
                    if not os.path.isfile(sync_file):
                        continue
                    try:
                        raw = open(sync_file).read().strip()
                        ts = datetime.fromisoformat(raw)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    except (ValueError, OSError):
                        continue
                    sensor = (
                        session.query(Sensor).filter_by(local_hostname=entry.name).first()
                        or session.query(Sensor).filter_by(hostname=entry.name).first()
                    )
                    if sensor:
                        existing = sensor.last_seen
                        if existing and existing.tzinfo is None:
                            existing = existing.replace(tzinfo=timezone.utc)
                        if existing is None or ts > existing:
                            sensor.last_seen = ts
                            updated += 1
                if updated:
                    session.commit()
                    logger.info("Updated last_seen for %d sensor(s)", updated)
        except Exception:
            logger.exception("Sensor heartbeat update failed")
            session.rollback()
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


def _run_scheduled_analysis(app):
    """Run a full surveillance analysis on a schedule."""
    with app.app_context():
        from web.extensions import _Session, socketio
        from cyt.models import AnalysisRun, Device
        from cyt.fingerprint import run_fingerprinting

        session = _Session()
        run = AnalysisRun(
            trigger="scheduled",
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        session.commit()
        run_id = run.id

        try:
            threshold = app.config.get("JACCARD_THRESHOLD", 0.85)
            min_ssids = app.config.get("MIN_SSIDS_FOR_FINGERPRINT", 2)

            clusters, fps = run_fingerprinting(
                session, threshold=threshold, min_ssids=min_ssids
            )
            devices_count = session.query(Device).count()
            persistent_count = (
                session.query(Device)
                .filter(Device.fingerprint_id.isnot(None))
                .count()
            )

            run.devices_analyzed = devices_count
            run.persistent_devices = persistent_count
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            session.commit()

            logger.info(
                "Scheduled analysis #%d complete: %d devices, %d persistent",
                run_id, devices_count, persistent_count,
            )
            socketio.emit("analysis_complete", {
                "run_id": run_id,
                "devices": devices_count,
                "clusters": clusters,
                "fingerprints": fps,
                "trigger": "scheduled",
            })
        except Exception:
            logger.exception("Scheduled analysis #%d failed", run_id)
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            session.commit()
        finally:
            _Session.remove()


def _run_cleanup(app):
    """Purge old appearance records beyond the configured retention window."""
    with app.app_context():
        from web.extensions import _Session
        from cyt.models import Appearance

        timing = app.config.get("TIMING", {})
        retention_days = timing.get("retention_days", 90)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        session = _Session()
        try:
            deleted = (
                session.query(Appearance)
                .filter(Appearance.timestamp < cutoff)
                .delete(synchronize_session=False)
            )
            session.commit()
            if deleted:
                logger.info(
                    "Cleanup: purged %d appearances older than %d days",
                    deleted, retention_days,
                )
        except Exception:
            logger.exception("Cleanup failed")
            session.rollback()
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

    # Scheduled analysis interval (hours, 0 = disabled)
    analysis_hours = timing.get("analysis_interval_hours", 6)

    # Cleanup interval (hours, 0 = disabled)
    cleanup_hours = timing.get("cleanup_interval_hours", 24)

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

    if analysis_hours > 0:
        scheduler.add_job(
            _run_scheduled_analysis,
            "interval",
            hours=analysis_hours,
            args=[app],
            id="scheduled_analysis",
            replace_existing=True,
        )

    if cleanup_hours > 0:
        scheduler.add_job(
            _run_cleanup,
            "interval",
            hours=cleanup_hours,
            args=[app],
            id="data_cleanup",
            replace_existing=True,
        )

    scheduler.start()
    logger.info(
        "Scheduler started: ingestion=%ds, fingerprinting=%ds, analysis=%dh, cleanup=%dh",
        ingest_interval, fp_interval, analysis_hours, cleanup_hours,
    )
