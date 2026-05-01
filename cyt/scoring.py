"""Foreign device likelihood scoring.

Calculates a 0-100 suspiciousness score based on behavioral signals,
then maps it to a High / Medium / Low label with a Bootstrap color class.
"""


def compute_likelihood(appearances, probed_ssids, is_randomized, manufacturer):
    """Return (score, likelihood, likelihood_cls) for a device.

    Parameters
    ----------
    appearances : int
        Total appearance count for the device.
    probed_ssids : list | set
        Collection of SSIDs the device has probed for.
    is_randomized : bool
        Whether the MAC address is locally-administered / randomized.
    manufacturer : str
        OUI manufacturer string (empty string = unknown).

    Returns
    -------
    tuple[int, str, str]
        (numeric_score, label, bootstrap_class)
        label is "High", "Medium", or "Low".
        bootstrap_class is "danger", "warning", or "success".
    """
    score = 0

    # Appearance frequency
    if appearances >= 50:
        score += 40
    elif appearances >= 10:
        score += 20
    elif appearances >= 3:
        score += 10

    # Probed SSIDs present
    if probed_ssids:
        score += 25

    # Randomized / locally-administered MAC
    if is_randomized:
        score += 20

    # Unknown manufacturer
    if not manufacturer:
        score += 15

    # Map to label
    if score >= 70:
        return score, "High", "danger"
    elif score >= 35:
        return score, "Medium", "warning"
    else:
        return score, "Low", "success"
