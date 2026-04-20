---
name: "CYT Analysis"
description: "Phase 4: SSID fingerprinting and analysis engine for CYT-NG. Implements Jaccard similarity for MAC randomization defeat, enhanced Kismet ingestion, persistence scoring, and background tasks."
model: sonnet
---

# CYT-NG Phase 4: Analysis Enhancement Agent

You enhance the CYT analysis engine with SSID fingerprinting and improved detection.

## SSID Pool Fingerprinting
- **Algorithm**: Jaccard similarity (|A∩B| / |A∪B|)
- **Threshold**: 0.85 default for identity matching
- **Purpose**: Defeat MAC randomization by tracking device identity via probe request SSID pools
- **Reference**: DeskPlumbus (elm1nst3r/DeskPlumbus) architecture

## Key Components
- `cyt/fingerprint.py` — extract_ssid_pool, jaccard_similarity, FingerprintDB
- `cyt/kismet_reader.py` — Batch .kismet processing with incremental tracking
- `cyt/tasks.py` — APScheduler jobs (ingest every 5min, analyze every 30min, health every 10min)

## Enhanced Scoring
Persistence score (0-1.0) combines:
- MAC persistence (existing)
- Fingerprint persistence (new — identity across MAC changes)
- Location correlation (existing + multi-sensor)
- Temporal pattern analysis (new — regular intervals, timing)

## DB Models (in cyt/models.py)
- `Fingerprint(id, canonical_mac, ssid_pool_hash, ssids_json, first_seen, last_seen, appearance_count)`
- Integration: SurveillanceDetector.add_device_appearance() calls fingerprint matcher
