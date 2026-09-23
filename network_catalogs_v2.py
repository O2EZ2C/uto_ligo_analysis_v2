"""
network_catalogs_v2.py — File B: network-touching functions ONLY
==================================================================

Every function in this file makes a live network call. This is the
ONLY file in the v2 project allowed to do that.

uto_ligo_analysis_v2.py (File A) imports from this file in exactly
two situations:
  1. A cached catalog CSV is missing locally and needs downloading.
  2. The Gaia/NED deep-recheck stage is explicitly run.

File A never imports this file at the top — only inside the specific
function that needs it, right before it's used. That way, a normal
offline run never even loads this file.

STATUS: SKELETON. Every function below is a stub for now — build
order puts File B after the offline stages are working (see
v2_script_context_document.md, Section 4).
"""


def download_star_catalog(catalog="I/239/hip_main"):
    """Not built yet.

    Will mirror uto_ligo_analysis.py's download_star_catalog(), with
    one difference per the v2 design: no magnitude filter — v2 wants
    the maximum number of stars available, since what matters is
    which stars fall within pairing distance of a galaxy, not
    brightness (see context doc Section 7, 'Star magnitude range').
    """
    raise NotImplementedError("download_star_catalog() not built yet")


def download_galaxy_catalog(catalog="J/AJ/145/101"):
    """Not built yet.

    Will mirror uto_ligo_analysis.py's download_galaxy_catalog()
    (Updated Nearby Galaxy Catalog, Karachentsev et al. 2013).
    """
    raise NotImplementedError("download_galaxy_catalog() not built yet")


def deep_recheck(candidates, gaia_mag_limit=18.0):
    """Not built yet.

    Will mirror uto_ligo_analysis.py's deep_recheck() — one targeted
    Gaia + NED cone query per candidate, run only on the small
    tier-tagged subset, never in bulk.
    """
    raise NotImplementedError("deep_recheck() not built yet")
