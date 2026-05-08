"""OUI manufacturer lookup with auto-updating IEEE database.

Uses mac-vendor-lookup as the primary source (downloads IEEE MA-L list).
Falls back gracefully if the package is unavailable or the lookup fails.
"""

import logging

logger = logging.getLogger(__name__)

_lookup = None
_init_attempted = False


def _get_lookup():
    """Lazy-init the MacLookup instance (uses cached DB only, no download)."""
    global _lookup, _init_attempted
    if _init_attempted:
        return _lookup
    _init_attempted = True
    try:
        from mac_vendor_lookup import MacLookup
        _lookup = MacLookup()
        # Do NOT call update_vendors() — it downloads from IEEE over the
        # network, which blocks the gevent event loop indefinitely in
        # containers without internet.  The bundled/cached DB is sufficient.
        logger.info("OUI vendor database loaded successfully")
    except ImportError:
        logger.warning("mac-vendor-lookup not installed — OUI fallback disabled")
    except Exception as e:
        logger.warning("Failed to initialize OUI database: %s", e)
    return _lookup


def lookup_manufacturer(mac: str) -> str:
    """Look up the manufacturer for a MAC address.

    Returns the vendor name or empty string if not found.
    """
    ml = _get_lookup()
    if ml is None:
        return ""
    try:
        return ml.lookup(mac)
    except Exception:
        return ""
