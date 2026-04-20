"""Flask application configuration loaded from config.json + environment."""
import json
import os
from pathlib import Path


def _load_config_json():
    """Load config.json from project root."""
    config_path = Path(__file__).resolve().parent.parent / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


_cfg = _load_config_json()


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get(
        _cfg.get("web", {}).get("secret_key_env", "CYT_SECRET_KEY"),
        "dev-change-me",
    )

    # Database
    _db_path = os.environ.get(
        "CYT_DATABASE_PATH",
        _cfg.get("paths", {}).get("cyt_database", "cyt_data.db"),
    )
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{_db_path}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Kismet data
    KISMET_LOGS = os.environ.get(
        "KISMET_DATA_PATH",
        _cfg.get("paths", {}).get("kismet_logs", ""),
    )

    # Paths
    REPORTS_DIR = _cfg.get("paths", {}).get("reports_dir", "surveillance_reports")
    KML_DIR = _cfg.get("paths", {}).get("kml_dir", "kml_files")
    IGNORE_LISTS = _cfg.get("paths", {}).get("ignore_lists", {})

    # Timing
    TIMING = _cfg.get("timing", {})

    # Search bounds (WiGLE)
    SEARCH = _cfg.get("search", {})

    # Fingerprinting
    JACCARD_THRESHOLD = _cfg.get("fingerprinting", {}).get("jaccard_threshold", 0.85)
    MIN_SSIDS_FOR_FINGERPRINT = _cfg.get("fingerprinting", {}).get("min_ssids_for_fingerprint", 2)

    # Flask-SocketIO
    SOCKETIO_ASYNC_MODE = "gevent"

    # Raw config for sub-components
    RAW_CONFIG = _cfg
