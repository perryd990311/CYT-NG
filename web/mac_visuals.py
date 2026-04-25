"""Deterministic visual identifiers for MAC addresses.

Provides color-dot HSL values and friendly two-word names generated
from a MAC address hash.  Same MAC always produces the same visual.
"""

import hashlib

ADJECTIVES = [
    "Swift",
    "Bold",
    "Calm",
    "Dark",
    "Echo",
    "Faint",
    "Gold",
    "Hazy",
    "Iron",
    "Jade",
    "Keen",
    "Loud",
    "Mint",
    "Neon",
    "Opal",
    "Pine",
    "Rust",
    "Silk",
    "Teal",
    "Void",
    "Warm",
    "Zinc",
    "Blue",
    "Ashen",
    "Coral",
    "Dusky",
    "Foggy",
    "Grim",
    "Ivory",
    "Lunar",
]

ANIMALS = [
    "Falcon",
    "Otter",
    "Lynx",
    "Cobra",
    "Raven",
    "Shark",
    "Tiger",
    "Viper",
    "Eagle",
    "Heron",
    "Mantis",
    "Puma",
    "Gecko",
    "Crane",
    "Bison",
    "Manta",
    "Newt",
    "Osprey",
    "Drake",
    "Finch",
    "Hornet",
    "Jackal",
    "Kodiak",
    "Lemur",
    "Moose",
    "Narwhal",
    "Parrot",
    "Quail",
    "Stork",
    "Toucan",
]


def _mac_hash(mac: str) -> int:
    """Stable integer hash from a MAC address string."""
    clean = mac.upper().replace(":", "").replace("-", "")
    return int(hashlib.sha256(clean.encode()).hexdigest()[:12], 16)


def color_dot_hsl(mac: str) -> str:
    """Return an HSL color string deterministically derived from a MAC."""
    h = _mac_hash(mac)
    hue = h % 360
    sat = 60 + (h >> 12) % 25  # 60-84 %
    lum = 48 + (h >> 24) % 15  # 48-62 %
    return f"hsl({hue}, {sat}%, {lum}%)"


def friendly_name(mac: str) -> str:
    """Return a two-word name (adjective + animal) for a MAC address."""
    h = _mac_hash(mac)
    adj = ADJECTIVES[h % len(ADJECTIVES)]
    animal = ANIMALS[(h >> 16) % len(ANIMALS)]
    return f"{adj} {animal}"


def ssid_color_hsl(ssid: str) -> dict:
    """Return bg/border/text HSL values for an SSID tag."""
    h = int(hashlib.sha256(ssid.encode()).hexdigest()[:8], 16)
    hue = h % 360
    return {
        "bg": f"hsla({hue}, 60%, 40%, 0.2)",
        "border": f"hsla({hue}, 60%, 50%, 0.35)",
        "text": f"hsl({hue}, 70%, 70%)",
    }
