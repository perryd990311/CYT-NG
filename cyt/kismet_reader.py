"""
Batch reader for Kismet .kismet SQLite database files.

Reads synced .kismet files from RPi sensors and extracts device/probe data
for ingestion into CYT's own SQLite database.
"""

import calendar
import glob
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


def is_locally_administered(mac: str) -> bool:
    """Check if a MAC address is locally administered (randomized).

    The second-least-significant bit of the first octet is 1 for
    locally administered addresses (used by iOS/Android/Windows MAC
    randomization).
    """
    try:
        first_octet = int(mac.split(":")[0], 16)
        return bool(first_octet & 0x02)
    except (ValueError, IndexError):
        return False


@dataclass
class DeviceRecord:
    """Parsed device data from a Kismet database."""

    mac: str
    device_type: str
    first_seen: datetime
    last_seen: datetime
    ssids: set = field(default_factory=set)
    lat: Optional[float] = None
    lon: Optional[float] = None
    signal_dbm: Optional[int] = None
    manufacturer: Optional[str] = None


def scan_kismet_directory(path_pattern: str) -> List[str]:
    """Find all .kismet files matching the given glob pattern."""
    files = sorted(glob.glob(path_pattern, recursive=True))
    logger.info("Found %d .kismet files matching '%s'", len(files), path_pattern)
    return files


def process_kismet_file(
    file_path: str,
    last_processed_ts: Optional[datetime] = None,
) -> List[DeviceRecord]:
    """
    Extract device records from a single .kismet SQLite file.

    Args:
        file_path: Path to the .kismet database file.
        last_processed_ts: Only return devices updated after this timestamp.
            If None, return all devices.

    Returns:
        List of DeviceRecord objects.
    """
    records = []
    # Copy file to a temp location to avoid reading an actively-written
    # .kismet SQLite file over SMB (which causes 'database disk image is
    # malformed' errors).
    tmp_copy = None
    read_path = file_path
    try:
        tmp_fd, tmp_copy = tempfile.mkstemp(suffix=".kismet")
        os.close(tmp_fd)
        shutil.copy2(file_path, tmp_copy)
        read_path = tmp_copy
    except OSError as e:
        logger.warning("Could not copy %s to temp — reading in-place: %s", file_path, e)
        tmp_copy = None

    try:
        conn = sqlite3.connect(f"file:{read_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM devices"
        params = []
        if last_processed_ts:
            query += " WHERE last_time > ?"
            # calendar.timegm correctly converts naive UTC to POSIX epoch
            # (unlike .timestamp() which assumes local time for naive datetimes)
            params.append(calendar.timegm(last_processed_ts.timetuple()))

        cursor.execute(query, params)

        for row in cursor.fetchall():
            try:
                device_json = json.loads(row["device"]) if row["device"] else {}
            except (json.JSONDecodeError, KeyError):
                device_json = {}

            # Extract probed SSIDs
            ssids = set()
            probed = device_json.get("dot11.device", {})
            if "dot11.device.probed_ssid_map" in probed:
                for ssid_entry in probed["dot11.device.probed_ssid_map"]:
                    ssid_val = ssid_entry.get("dot11.probedssid.ssid", "")
                    if ssid_val:
                        ssids.add(ssid_val)
            # Fallback: single last probed
            last_probed = probed.get("dot11.device.last_probed_ssid_record", {})
            if last_probed:
                ssid_val = last_probed.get("dot11.probedssid.ssid", "")
                if ssid_val:
                    ssids.add(ssid_val)

            # Extract GPS if available
            lat = lon = None
            location = device_json.get("kismet.device.base.location", {})
            avg_loc = location.get("kismet.common.location.avg_loc", {})
            if avg_loc:
                lat = avg_loc.get("kismet.common.location.geopoint", [None, None])[1]
                lon = avg_loc.get("kismet.common.location.geopoint", [None, None])[0]

            # Extract signal
            signal_dbm = None
            signal_data = device_json.get("kismet.device.base.signal", {})
            if signal_data:
                signal_dbm = signal_data.get("kismet.common.signal.last_signal", None)

            # Strip Kismet PHY type suffix (e.g. "AA:BB:CC:DD:EE:FF/1" → "AA:BB:CC:DD:EE:FF")
            raw_mac = row["devmac"] if "devmac" in row.keys() else "unknown"
            mac = raw_mac.split("/")[0].strip().upper() if raw_mac != "unknown" else "unknown"
            first_time = row["first_time"] if "first_time" in row.keys() else 0
            last_time = row["last_time"] if "last_time" in row.keys() else 0

            records.append(
                DeviceRecord(
                    mac=mac,
                    device_type=device_json.get("kismet.device.base.type", "unknown"),
                    first_seen=datetime.utcfromtimestamp(first_time),
                    last_seen=datetime.utcfromtimestamp(last_time),
                    ssids=ssids,
                    lat=lat,
                    lon=lon,
                    signal_dbm=signal_dbm,
                    manufacturer=device_json.get("kismet.device.base.manuf", None),
                )
            )

        conn.close()
        logger.info("Extracted %d device records from %s", len(records), file_path)
    except sqlite3.Error as e:
        logger.error("SQLite error reading %s: %s", file_path, e)
    except Exception as e:
        logger.error("Error processing %s: %s", file_path, e)
    finally:
        if tmp_copy and os.path.exists(tmp_copy):
            try:
                os.unlink(tmp_copy)
            except OSError:
                pass

    return records


INGEST_BATCH_SIZE = 500


def ingest_all(directory_pattern: str, session_factory, sensor_id: Optional[int] = None):
    """
    Batch ingest all .kismet files, tracking progress per file.

    Uses KismetFileTracker to only process new/updated data.
    Writes Device and Appearance records to CYT's database.
    """
    from cyt.models import Device, Appearance, KismetFileTracker
    from cyt.oui_lookup import lookup_manufacturer
    from sqlalchemy import text as _text

    session = session_factory()
    files = scan_kismet_directory(directory_pattern)

    # Pre-load lightweight MAC→(id, last_seen) map — avoids N+1 SELECT queries.
    # Uses raw SQL to avoid loading heavy ORM objects for every device.
    mac_cache: dict = {}  # mac -> (device_id, last_seen datetime)
    for row in session.execute(_text("SELECT id, mac, last_seen FROM devices")).fetchall():
        mac_cache[row[1]] = (row[0], row[2])

    total_new = 0
    for file_path in files:
        # Check if already processed
        tracker = session.query(KismetFileTracker).filter_by(file_path=file_path).first()
        current_size = os.path.getsize(file_path)

        last_ts = None
        if tracker and tracker.file_size == current_size:
            logger.debug("Skipping unchanged file: %s", file_path)
            continue
        if tracker:
            last_ts = tracker.last_processed_ts

        logger.info("Processing %s (%.1f MB)", os.path.basename(file_path), current_size / 1_048_576)
        records = process_kismet_file(file_path, last_ts)
        logger.info("  Extracted %d records, ingesting...", len(records))

        batch_count = 0
        for i, rec in enumerate(records):
            # Resolve manufacturer — prefer Kismet's value, fall back to OUI DB
            mfr = rec.manufacturer
            if not mfr or mfr == "Unknown":
                mfr = lookup_manufacturer(rec.mac) or mfr or "Unknown"

            # Upsert device using mac_cache (no per-record SELECT)
            cached = mac_cache.get(rec.mac)
            if cached is None:
                # New device — create and flush to get id
                device = Device(
                    mac=rec.mac,
                    device_type=rec.device_type,
                    first_seen=rec.first_seen,
                    last_seen=rec.last_seen,
                    manufacturer=mfr,
                    is_randomized=is_locally_administered(rec.mac),
                )
                session.add(device)
                session.flush()
                device_id = device.id
                mac_cache[rec.mac] = (device_id, rec.last_seen)
            else:
                device_id, cached_last_seen = cached
                if rec.last_seen > (cached_last_seen or datetime.min):
                    session.execute(
                        _text("UPDATE devices SET last_seen=:ts WHERE id=:id"),
                        {"ts": rec.last_seen, "id": device_id},
                    )
                    mac_cache[rec.mac] = (device_id, rec.last_seen)

            # Add appearance
            appearance = Appearance(
                device_id=device_id,
                sensor_id=sensor_id,
                timestamp=rec.last_seen,
                lat=rec.lat,
                lon=rec.lon,
                signal_dbm=rec.signal_dbm,
                ssids_json=json.dumps(sorted(rec.ssids)) if rec.ssids else None,
            )
            session.add(appearance)
            total_new += 1
            batch_count += 1

            # Commit in batches to avoid long-held transactions
            if batch_count >= INGEST_BATCH_SIZE:
                session.commit()
                logger.info("  ...%d/%d records committed", i + 1, len(records))
                batch_count = 0

        # Update tracker
        if not tracker:
            tracker = KismetFileTracker(file_path=file_path)
            session.add(tracker)
        tracker.file_size = current_size
        tracker.last_processed_ts = datetime.utcnow()
        tracker.records_imported = (tracker.records_imported or 0) + len(records)

        session.commit()
        logger.info("Ingested %d records from %s", len(records), os.path.basename(file_path))

    logger.info("Ingestion complete. %d new appearances across %d files.", total_new, len(files))
    session.close()
    return total_new
