"""
SSID-pool fingerprinting engine for defeating MAC randomization.

Uses Jaccard similarity to group devices probing for overlapping SSID sets,
identifying the same physical device across multiple randomized MAC addresses.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Set, Tuple

from cyt.models import Device, Appearance, Fingerprint

logger = logging.getLogger(__name__)


def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Compute Jaccard similarity coefficient between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def extract_ssid_pool(device: Device, session) -> Set[str]:
    """Collect all SSIDs ever probed by a device from its appearances."""
    appearances = (
        session.query(Appearance)
        .filter(Appearance.device_id == device.id)
        .filter(Appearance.ssids_json.isnot(None))
        .all()
    )
    pool: Set[str] = set()
    for app in appearances:
        try:
            ssids = json.loads(app.ssids_json)
            pool.update(s for s in ssids if s)
        except (json.JSONDecodeError, TypeError):
            pass
    return pool


def build_ssid_pools(
    session,
    min_ssids: int = 1,
    max_devices_per_ssid: int = 20,
    ignored_ssids: Set[str] = None,
) -> Dict[int, Set[str]]:
    """
    Build SSID pools for all devices that have probed at least `min_ssids` SSIDs.

    Filters out:
    - SSIDs in the ignore list (e.g. the user's own home networks)
    - SSIDs probed by more than `max_devices_per_ssid` devices (too common
      to be useful as a fingerprint signal)

    Returns:
        Dict mapping device.id → set of probed SSIDs.
    """
    if ignored_ssids is None:
        ignored_ssids = set()

    devices = session.query(Device).all()

    # First pass: collect raw pools and count how many devices probe each SSID
    raw_pools: Dict[int, Set[str]] = {}
    ssid_device_count: Dict[str, int] = {}

    for device in devices:
        pool = extract_ssid_pool(device, session)
        # Remove ignored SSIDs
        pool -= ignored_ssids
        if pool:
            raw_pools[device.id] = pool
            for ssid in pool:
                ssid_device_count[ssid] = ssid_device_count.get(ssid, 0) + 1

    # Identify over-common SSIDs
    common_ssids = {s for s, c in ssid_device_count.items() if c > max_devices_per_ssid}
    if common_ssids:
        logger.info(
            "Excluding %d over-common SSIDs (>%d devices): %s",
            len(common_ssids),
            max_devices_per_ssid,
            sorted(common_ssids)[:10],
        )

    # Second pass: remove common SSIDs and apply min_ssids threshold
    pools: Dict[int, Set[str]] = {}
    for did, pool in raw_pools.items():
        filtered = pool - common_ssids
        if len(filtered) >= min_ssids:
            pools[did] = filtered

    logger.info(
        "Built SSID pools for %d devices (min_ssids=%d, max_devices_per_ssid=%d)",
        len(pools),
        min_ssids,
        max_devices_per_ssid,
    )
    return pools


def find_fingerprint_clusters(
    pools: Dict[int, Set[str]],
    threshold: float = 0.85,
) -> List[List[int]]:
    """
    Cluster devices by SSID-pool Jaccard similarity.

    Args:
        pools: Dict of device_id → SSID set.
        threshold: Jaccard similarity threshold for grouping.

    Returns:
        List of clusters, each a list of device IDs.
    """
    device_ids = list(pools.keys())
    visited = set()
    clusters: List[List[int]] = []

    for i, did_a in enumerate(device_ids):
        if did_a in visited:
            continue
        cluster = [did_a]
        visited.add(did_a)

        for did_b in device_ids[i + 1 :]:
            if did_b in visited:
                continue
            sim = jaccard_similarity(pools[did_a], pools[did_b])
            if sim >= threshold:
                cluster.append(did_b)
                visited.add(did_b)

        if len(cluster) > 1:
            clusters.append(cluster)

    logger.info(
        "Found %d fingerprint clusters from %d devices (threshold=%.2f)",
        len(clusters),
        len(device_ids),
        threshold,
    )
    return clusters


def assign_fingerprints(
    session,
    clusters: List[List[int]],
    pools: Dict[int, Set[str]],
) -> int:
    """
    Create or update Fingerprint records and link devices.

    For each cluster, computes a union SSID pool, finds or creates a
    Fingerprint row, and assigns all member devices.

    Returns:
        Number of fingerprints created or updated.
    """
    count = 0

    for cluster in clusters:
        # Union of all SSIDs in the cluster
        union_pool: Set[str] = set()
        for did in cluster:
            union_pool.update(pools.get(did, set()))

        pool_hash = Fingerprint.compute_pool_hash(union_pool)

        fp = session.query(Fingerprint).filter_by(ssid_pool_hash=pool_hash).first()
        if fp is None:
            # Pick the earliest-seen device MAC as canonical
            devices = (
                session.query(Device)
                .filter(Device.id.in_(cluster))
                .order_by(Device.first_seen)
                .all()
            )
            canonical_mac = devices[0].mac if devices else "unknown"

            fp = Fingerprint(
                canonical_mac=canonical_mac,
                ssid_pool_hash=pool_hash,
                ssids_json=json.dumps(sorted(union_pool)),
                appearance_count=len(cluster),
            )
            session.add(fp)
            session.flush()
            count += 1
        else:
            fp.last_seen = datetime.utcnow()
            fp.appearance_count = len(cluster)

        # Link devices to this fingerprint
        for did in cluster:
            device = session.query(Device).get(did)
            if device:
                device.fingerprint_id = fp.id
                device.is_randomized = True

    session.commit()
    logger.info("Assigned %d fingerprints across %d clusters", count, len(clusters))
    return count


def run_fingerprinting(
    session,
    threshold: float = 0.85,
    min_ssids: int = 1,
    max_devices_per_ssid: int = 20,
    ignored_ssids: Set[str] = None,
) -> Tuple[int, int]:
    """
    Full fingerprinting pipeline: build pools → cluster → assign.

    Returns:
        (clusters_found, fingerprints_created_or_updated)
    """
    pools = build_ssid_pools(
        session,
        min_ssids=min_ssids,
        max_devices_per_ssid=max_devices_per_ssid,
        ignored_ssids=ignored_ssids,
    )
    clusters = find_fingerprint_clusters(pools, threshold=threshold)
    fp_count = assign_fingerprints(session, clusters, pools)
    return len(clusters), fp_count
