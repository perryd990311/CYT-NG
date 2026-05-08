"""
SQLAlchemy models for CYT-NG's own database.

These models represent CYT's analysis data — not the Kismet database schema.
Kismet .kismet files are read-only via cyt.kismet_reader.
"""

import hashlib
import json
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

Base = declarative_base()


class Device(Base):
    """A unique wireless device identified by MAC address."""

    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    mac = Column(String(17), nullable=False, unique=True, index=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    device_type = Column(String(50))
    manufacturer = Column(String(100))
    is_randomized = Column(Boolean, default=False)
    notes = Column(Text)

    appearances = relationship("Appearance", back_populates="device", cascade="all, delete-orphan")
    fingerprint_id = Column(Integer, ForeignKey("fingerprints.id"), nullable=True)
    fingerprint = relationship("Fingerprint", back_populates="devices")

    __table_args__ = (Index("ix_devices_last_seen", "last_seen"),)


class Appearance(Base):
    """A single sighting of a device at a point in time and space."""

    __tablename__ = "appearances"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=True, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    signal_dbm = Column(Integer, nullable=True)
    ssids_json = Column(Text)  # JSON array of probed SSIDs at this sighting

    device = relationship("Device", back_populates="appearances")
    sensor = relationship("Sensor", back_populates="appearances")

    __table_args__ = (Index("ix_appearances_device_time", "device_id", "timestamp"),)


class Fingerprint(Base):
    """
    SSID-pool fingerprint for defeating MAC randomization.
    Groups devices that probe for the same set of SSIDs.
    """

    __tablename__ = "fingerprints"

    id = Column(Integer, primary_key=True)
    canonical_mac = Column(String(17), nullable=False)
    ssid_pool_hash = Column(String(64), nullable=False, unique=True, index=True)
    ssids_json = Column(Text, nullable=False)  # JSON array of SSIDs in the pool
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    appearance_count = Column(Integer, default=1)

    devices = relationship("Device", back_populates="fingerprint")

    @staticmethod
    def compute_pool_hash(ssids: set) -> str:
        """Deterministic hash of an SSID pool for fast lookups."""
        normalized = json.dumps(sorted(ssids), separators=(",", ":"))
        return hashlib.sha256(normalized.encode()).hexdigest()


class AnalysisRun(Base):
    """Record of each surveillance analysis execution."""

    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    trigger = Column(String(20))  # "scheduled", "manual", "api"
    devices_analyzed = Column(Integer, default=0)
    persistent_devices = Column(Integer, default=0)
    alerts_generated = Column(Integer, default=0)
    report_path = Column(String(500), nullable=True)
    kml_path = Column(String(500), nullable=True)
    status = Column(String(20), default="running")  # running, completed, failed


class User(Base):
    """Web UI user account."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False, unique=True, index=True)
    password_hash = Column(String(128), nullable=True)  # Null for SSO-only users
    is_admin = Column(Boolean, default=False)
    auth_provider = Column(String(20), default="local")  # "local" or "synology_sso"
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)


class Sensor(Base):
    """Remote Kismet sensor (typically a Raspberry Pi)."""

    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    hostname = Column(String(255), nullable=False)
    ssh_port = Column(Integer, default=22)
    ssh_user = Column(String(50), default="pi")
    ssh_key_path = Column(String(500), nullable=True)
    smb_share_path = Column(String(500), nullable=True)
    status = Column(String(20), default="unknown")  # online, offline, error, provisioning
    last_seen = Column(DateTime, nullable=True)
    local_hostname = Column(
        String(255), nullable=True
    )  # Pi's $(hostname) — used for NAS dir matching
    kismet_version = Column(String(20), nullable=True)
    wifi_interface = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    appearances = relationship("Appearance", back_populates="sensor")


class KismetFileTracker(Base):
    """Track which .kismet files have been ingested and to what point."""

    __tablename__ = "kismet_file_tracker"

    id = Column(Integer, primary_key=True)
    file_path = Column(String(500), nullable=False, unique=True, index=True)
    file_size = Column(Integer, default=0)
    last_processed_ts = Column(DateTime, nullable=True)
    records_imported = Column(Integer, default=0)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=True)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


def init_db(db_path: str = "cyt_data.db"):
    """Create engine, session factory, and all tables."""
    from sqlalchemy import event

    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"timeout": 30, "check_same_thread": False},
    )

    # Enable WAL mode: allows concurrent readers while a writer holds the lock
    @event.listens_for(engine, "connect")
    def set_wal_mode(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return engine, Session
