"""
UTO v2 — Skeleton (File A: offline-only)
==========================================

STATUS: Stage 1 (load + filter) and run selection are now real. Every
other stage function is still a stub that prints "not built yet,
skipping". Keep building one stage at a time — copy real code into
the next stub, test it, move on. See v2_script_context_document.md
for the full design spec this follows.

FILE SPLIT
----------
This is File A: everything that never touches the network (loading
local CSVs, pointing math, the galaxy/star lookup, pairs and tier
tagging, diagnostics, control tests using pre-downloaded catalogs,
ranking). File B (network_catalogs_v2.py) holds ONLY the catalog
downloads and the Gaia/NED deep-recheck. File A imports File B only
when a catalog is missing locally or the deep-recheck stage is
explicitly run — see stage_9_deep_check() below for where that
import will go.

WHY EVERY PATH IS BUILT FROM SCRIPT_DIR
----------------------------------------
No home-folder names anywhere in this file, since it's going on
GitHub. SCRIPT_DIR finds wherever this .py file actually lives, and
every other folder is built relative to that, no matter whose
computer it runs on.
"""

import os
import sys
import re
import pickle
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------
# 0. FOLDERS — all relative to this script's own location.
# ---------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
RAW_CSV_DIR = SCRIPT_DIR / "raw_csvs"
CATALOG_DIR = SCRIPT_DIR / "catalogs"        # cached catalog CSVs — kept separate from outputs
OUTPUT_DIR = SCRIPT_DIR / "outputs"
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"
LOG_PATH = OUTPUT_DIR / "run_log.txt"

for _d in (RAW_CSV_DIR, CATALOG_DIR, OUTPUT_DIR, CHECKPOINT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# STAGE 1 SETTINGS — same defaults as the old script (uto_ligo_analysis.py),
# carried across unchanged. Only changeable via advanced settings later.
# ---------------------------------------------------------------------
GLITCH_CLASSES = [
    "Blip", "Koi_Fish", "Tomte", "Helix",
    "Extremely_Loud", "Repeating_Blips", "Paired_Doves",
]  # only genuinely unexplained-cause classes

ML_CONFIDENCE_MIN = 0.9
COINCIDENCE_WINDOW_MS = 15  # H1-L1 light travel time ~10ms; padded
DETECTOR_LOCATIONS = {
    "H1": (46.4551, -119.4077, 142.6),
    "L1": (30.5629, -90.7742, -6.6),
    "V1": (43.6314, 10.5045, 51.9),
}
 
POINTING_CHUNK_SIZE = 5000        # events converted per astropy call (memory limit)
ZENITH_DEC_TOLERANCE_DEG = 0.5    # how far a zenith Dec may stray from the detector's latitude

# Approximate public start/end GPS times for each LIGO/Virgo observing
# run (same table as the old script — verify against GWOSC before
# treating run boundaries as authoritative:
# https://gwosc.org/eventapi/html/O3_Discovery_Papers/)
RUN_GPS_WINDOWS = {
    "O1":  (1126051217, 1137254417),
    "O2":  (1164556817, 1187733618),
    "O3a": (1238166018, 1253977218),
    "O3b": (1256655618, 1269363618),
}

_RUN_LABEL_RE = re.compile(r"([OoSs])(\d+)([a-cA-C]?)")


def _extract_run_label(filename):
    """Pulls an observing-run label (O1, O2, O3a, ...) out of a raw CSV's
    filename, matching the casing used in RUN_GPS_WINDOWS's keys. Falls
    back to the filename stem if no such pattern is found."""
    m = _RUN_LABEL_RE.search(filename)
    if m:
        return m.group(1).upper() + m.group(2) + m.group(3).lower()
    return os.path.splitext(filename)[0]


def assign_observing_run(gps_time):
    """Labels a GPS time with which observing run it falls in, or
    'unknown' if outside all known run windows."""
    for run, (start, end) in RUN_GPS_WINDOWS.items():
        if start <= gps_time <= end:
            return run
    return "unknown"


# ---------------------------------------------------------------------
# 1. VIRTUAL ENVIRONMENT CHECK — hard stop (not just a warning). This
#    is what broke the old background-run attempt.
# ---------------------------------------------------------------------
def check_venv_active():
    """sys.prefix != sys.base_prefix is only True when a venv is
    active. If it isn't, stop immediately instead of continuing."""
    in_venv = sys.prefix != sys.base_prefix
    if not in_venv:
        print("=" * 70)
        print("STOP: no virtual environment is active.")
        print()
        print("First time here? Run these from the project folder, one at a time:")
        print("    python3 -m venv ligo-env")
        print("    source ligo-env/bin/activate")
        print("    pip install numpy pandas astropy astroquery pycbc")
        print("(pycbc is the largest download and can take a while.)")
        print()
        print("Already set up? Just activate it, then run this script again:")
        print("    source ligo-env/bin/activate")
        print()
        print("=" * 70)
        sys.exit(1)
    print(f"Virtual environment OK ({sys.prefix})")


# ---------------------------------------------------------------------
# 2. FIRST-TIME SETUP CHECK — runs automatically the first time, and
#    is also available later as an on-demand menu option.
# ---------------------------------------------------------------------
def first_time_setup_check():
    """Not built yet. Will check RAW_CSV_DIR / CATALOG_DIR for what's
    missing and print where to get it, instead of crashing later with
    a confusing error."""
    print("\n[First-time setup check — not built yet, skipping]")


# ---------------------------------------------------------------------
# 3. NETWORK SWITCH — two layers.
#    Outer: one prompt for the whole run (this replaces the old
#    hardcoded ALLOW_NETWORK = True/False edit-the-source-code switch).
#    Inner: every individual network call still asks its own y/N on
#    top of that, same as before.
# ---------------------------------------------------------------------
ALLOW_NETWORK_THIS_RUN = False  # set by ask_network_permission() at startup


def ask_network_permission():
    global ALLOW_NETWORK_THIS_RUN
    raw = input("\nAllow live network calls this run? [y/N]: ").strip().lower()
    ALLOW_NETWORK_THIS_RUN = raw in ("y", "yes")
    state = "ALLOWED (still asked per-call)" if ALLOW_NETWORK_THIS_RUN else "BLOCKED"
    print(f"Network calls this run: {state}")


def require_network(feature_name):
    """Call at the top of any code path about to make a live network
    request. Blocks outright if the outer switch is off; otherwise
    still asks its own y/N before that one call goes out."""
    if not ALLOW_NETWORK_THIS_RUN:
        raise RuntimeError(
            f"Network call blocked: {feature_name}. Answer 'y' to the "
            f"'Allow live network calls this run?' prompt at startup "
            f"if you want this run to be allowed to ask."
        )
    answer = input(
        f"\n>>> About to make a live network call: {feature_name}\n"
        f">>> Allow it? [y/N]: "
    ).strip().lower()
    if answer not in ("y", "yes"):
        raise RuntimeError(f"Network call declined at the prompt: {feature_name}.")
    print(f">>> Confirmed — proceeding with: {feature_name}\n")


# ---------------------------------------------------------------------
# 4. GENERIC CHECKPOINT HELPERS — same checkpoint/rerun/skip pattern
#    as the old script, reused by every stage. Once a stage has real
#    settings (tolerance, pairing distance, etc.), pass them in as
#    `tag` so different settings don't collide under the same filename.
# ---------------------------------------------------------------------
def save_checkpoint(name, obj, tag=""):
    suffix = f"_{tag}" if tag else ""
    path = CHECKPOINT_DIR / f"{name}{suffix}.pkl"
    with open(path, "wb") as f:
        pickle.dump(obj, f)


def load_checkpoint(name, tag=""):
    suffix = f"_{tag}" if tag else ""
    path = CHECKPOINT_DIR / f"{name}{suffix}.pkl"
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    return None


def prompt_step_action(step_label, has_checkpoint):
    """Same three-way prompt as the old script: [C]heckpoint / [r]erun
    / [s]kip. Pressing Enter picks the bracketed default."""
    if has_checkpoint:
        prompt = f">>> {step_label}: checkpoint found. [C]heckpoint / [r]erun / [s]kip? [C]: "
        default = "c"
    else:
        prompt = f">>> {step_label}: no checkpoint yet. [R]un / [s]kip? [R]: "
        default = "r"
    answer = (input(prompt).strip().lower() or default)
    if answer.startswith("c") and has_checkpoint:
        return "checkpoint"
    elif answer.startswith("s"):
        return "skip"
    return "run"


# ---------------------------------------------------------------------
# 5. SETTINGS RECORD + RUN LOG — every output folder gets a settings
#    file listing everything used for that run; every run also
#    appends one line to a running log.
# ---------------------------------------------------------------------
def write_settings_file(run_output_dir, settings_dict):
    """Not built yet. Will write settings_dict into
    run_output_dir/settings.txt, one setting per line."""
    print(f"[write_settings_file — not built yet, skipping] (would write to {run_output_dir})")


def append_run_log(line):
    """Not built yet. Will append one line to LOG_PATH."""
    print(f"[append_run_log — not built yet, skipping] (would log: {line})")


# ---------------------------------------------------------------------
# 6. OUTPUT FOLDER SAFEGUARD — never overwrite an existing output
#    folder without asking first.
# ---------------------------------------------------------------------
def make_run_output_dir(folder_name):
    """Builds OUTPUT_DIR/folder_name (e.g. 'O1_gal3_pair0.08'). Asks
    before reusing anything already there."""
    path = OUTPUT_DIR / folder_name
    if path.exists():
        answer = input(
            f"\nOutput folder '{folder_name}' already exists. Reuse it? "
            f"Files inside may be overwritten. [y/N]: "
        ).strip().lower()
        if answer not in ("y", "yes"):
            raise RuntimeError(
                f"Stopped: output folder '{folder_name}' already exists "
                f"and reuse was declined."
            )
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------
# RUN SELECTION — now real. Lists runs found in RAW_CSV_DIR (by
# scanning filenames for an O1/O2/O3a-style label), picks by number,
# comma-list, or "all". Enter defaults to all.
# ---------------------------------------------------------------------
def get_available_runs():
    """Scans RAW_CSV_DIR for raw Gravity Spy CSVs and returns
    (sorted run labels found, the matching filenames). Returns
    ([], []) if the folder has no CSVs yet."""
    if not RAW_CSV_DIR.exists():
        return [], []
    files = sorted(f for f in os.listdir(RAW_CSV_DIR) if f.lower().endswith(".csv"))
    labels = sorted({_extract_run_label(fn) for fn in files})
    return labels, files


def prompt_run_selection():
    """Lists every run label found in raw_csvs/ and asks which to use.
    Accepts a single number, a comma-separated list of numbers, or
    'all'. Enter (no input) defaults to all. Returns a list of run
    labels, e.g. ['O1'] or ['O1', 'O2']."""
    labels, files = get_available_runs()

    if not labels:
        print(f"\nNo raw CSV files found in:\n  {RAW_CSV_DIR}")
        print("Nothing to select — Stage 1 will have nothing to load.")
        return []

    print("\nRuns found in raw_csvs/:")
    for i, label in enumerate(labels, start=1):
        print(f"  {i}. {label}")

    raw = input(
        f"\nPick run(s) by number or name (like 1,3a), or Enter for all "
        f"[{', '.join(labels)}]: "
    ).strip()

    if not raw or raw.lower() == "all":
        return labels

    chosen = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            idx = int(part) - 1
            if 0 <= idx < len(labels):
                chosen.append(labels[idx])
            else:
                print(f"  '{part}' is out of range — ignoring.")
        except ValueError:
            # not a plain number, so treat it as a run name like 3a or O3a
            wanted = part.lower().lstrip("o")
            matches = [lab for lab in labels if lab.lower().lstrip("o") == wanted]
            if matches:
                chosen.append(matches[0])
            else:
                print(f"  '{part}' is not a run I found — ignoring.")

    if not chosen:
        print("Nothing valid selected — defaulting to all runs.")
        return labels

    # de-duplicate while keeping the order the user typed them in
    seen = set()
    ordered = []
    for label in chosen:
        if label not in seen:
            seen.add(label)
            ordered.append(label)
    return ordered


# ---------------------------------------------------------------------
# STAGE 1 — Load glitch catalog + filter to single-detector events.
# Mirrors uto_ligo_analysis.py's Steps 1-2, but reads only the CSV
# files that match the selected run(s) instead of every CSV in the
# folder — that's what makes run selection actually do something.
# ---------------------------------------------------------------------
def fetch_glitch_catalog_from_files(
    csv_files, gps_start, gps_end,
    detectors=("H1", "L1", "V1"),
    ml_confidence_min=ML_CONFIDENCE_MIN,
):
    """
    Loads the given raw Gravity Spy CSVs (from RAW_CSV_DIR) and
    filters down to:
      - gps_time within [gps_start, gps_end] (skipped if either is None)
      - detector in `detectors`
      - ml_confidence >= ml_confidence_min
      - ml_label in GLITCH_CLASSES (the 7 unexplained-cause classes)

    Returns a DataFrame with columns:
        ['gps_time', 'detector', 'ml_label', 'ml_confidence',
         'snr', 'peak_frequency', 'duration', 'gravityspy_id']
    (only the ones actually present in the source CSVs).
    """
    frames = []
    for fname in csv_files:
        frames.append(pd.read_csv(RAW_CSV_DIR / fname))

    if not frames:
        raise FileNotFoundError(
            f"No matching CSV files found in {RAW_CSV_DIR} for the "
            f"selected run(s)."
        )

    raw = pd.concat(frames, ignore_index=True)
    raw = raw.rename(columns={"event_time": "gps_time", "ifo": "detector"})
    if "gps_time" not in raw.columns and "peak_time" in raw.columns:
        raw["gps_time"] = raw["peak_time"]

    required_cols = {"gps_time", "detector", "ml_label", "ml_confidence"}
    missing = required_cols - set(raw.columns)
    if missing:
        raise ValueError(
            f"Loaded data is missing expected columns: {missing}. "
            f"Available columns: {list(raw.columns)}"
        )

    df = raw
    if gps_start is not None and gps_end is not None:
        df = df[(df["gps_time"] >= gps_start) & (df["gps_time"] <= gps_end)]
    df = df[df["detector"].isin(detectors)]
    df = df[df["ml_confidence"] >= ml_confidence_min]
    if GLITCH_CLASSES:
        df = df[df["ml_label"].isin(GLITCH_CLASSES)]

    keep_cols = [c for c in
                 ["gps_time", "detector", "ml_label", "ml_confidence",
                  "snr", "peak_frequency", "duration", "gravityspy_id"]
                 if c in df.columns]
    df = df[keep_cols].sort_values("gps_time").reset_index(drop=True)

    print(f"Loaded {len(df)} glitches after filtering "
          f"(confidence >= {ml_confidence_min}, classes={GLITCH_CLASSES})")

    return df


def filter_single_detector_events(df, window_ms=COINCIDENCE_WINDOW_MS):
    """
    Keeps only events where no OTHER detector has a listed trigger
    within +/- window_ms of the same gps_time. Identical logic to the
    old script's version.
    """
    window_s = window_ms / 1000.0
    keep_rows = []
    times = df["gps_time"].values
    dets = df["detector"].values

    for i, (t, d) in enumerate(zip(times, dets)):
        others = df[
            (df["detector"] != d) &
            (abs(df["gps_time"] - t) <= window_s)
        ]
        if others.empty:
            keep_rows.append(i)

    return df.iloc[keep_rows].reset_index(drop=True)


def stage_1_load_and_filter(run_context):
    """
    Loads the raw glitch CSVs for the selected run(s), filters to
    single-detector-only events, and stores both DataFrames plus the
    combined GPS window in run_context for later stages to use.

    Checkpoints are tagged by the combined run selection (e.g. "O1"
    or "O1_O2"), same pattern as the old script's data-pool tagging.
    """
    selected_runs = run_context.get("selected_runs") or []
    if not selected_runs:
        print("No runs selected — Stage 1 has nothing to load.")
        return None

    all_labels, all_files = get_available_runs()
    matching_files = [f for f in all_files if _extract_run_label(f) in selected_runs]
    if not matching_files:
        print(f"No CSV files in {RAW_CSV_DIR} match the selected run(s) "
              f"{selected_runs}.")
        return None

    known_runs = [r for r in selected_runs if r in RUN_GPS_WINDOWS]
    unknown_runs = [r for r in selected_runs if r not in RUN_GPS_WINDOWS]
    if unknown_runs:
        print(f"WARNING: run label(s) {unknown_runs} not found in "
              f"RUN_GPS_WINDOWS — add them there if you want their "
              f"events properly windowed.")
    gps_start = min(RUN_GPS_WINDOWS[r][0] for r in known_runs) if known_runs else None
    gps_end = max(RUN_GPS_WINDOWS[r][1] for r in known_runs) if known_runs else None

    run_tag = "_".join(sorted(selected_runs))
    print(f"\nStage 1: selected run(s) = {selected_runs}  |  tag = '{run_tag}'  |  "
          f"GPS window = {gps_start} - {gps_end}")
    print(f"Matching CSV file(s): {', '.join(matching_files)}")

    # --- Step 1: load + filter glitch catalog ---
    glitches = load_checkpoint("01_glitches", tag=run_tag)
    action = prompt_step_action("Stage 1 - load glitch catalog", has_checkpoint=(glitches is not None))
    if action == "checkpoint":
        print(f"   -> using checkpoint ({len(glitches)} events, skipped re-load)")
    elif action == "skip":
        print("   -> SKIPPED for this run.")
        glitches = None
    else:
        glitches = fetch_glitch_catalog_from_files(matching_files, gps_start, gps_end)
        save_checkpoint("01_glitches", glitches, tag=run_tag)

    if glitches is None or len(glitches) == 0:
        print("No glitches available — Stage 1 stops here for this run.")
        run_context["glitches"] = glitches
        run_context["single_det"] = None
        return None

    # --- Step 2: filter to single-detector-only events ---
    single_det = load_checkpoint("02_single_det", tag=run_tag)
    action2 = prompt_step_action("Stage 1 - filter to single-detector events", has_checkpoint=(single_det is not None))
    if action2 == "checkpoint":
        print(f"   -> using checkpoint ({len(single_det)} single-detector events, skipped re-filter)")
    elif action2 == "skip":
        print("   -> SKIPPED for this run.")
        single_det = None
    else:
        single_det = filter_single_detector_events(glitches)
        single_det["observing_run"] = single_det["gps_time"].apply(assign_observing_run)
        print(f"   -> {len(single_det)} single-detector events found")
        save_checkpoint("02_single_det", single_det, tag=run_tag)

    run_context["glitches"] = glitches
    run_context["single_det"] = single_det
    run_context["gps_start"] = gps_start
    run_context["gps_end"] = gps_end
    run_context["run_tag"] = run_tag

    return single_det


# ---------------------------------------------------------------------
# STAGES 2-10 — still stubs. Build order runs in actual pipeline
# order now (Stage 1 first, as just built above), not the "Stage 3/4
# first" order mentioned earlier in the design doc.
# ---------------------------------------------------------------------

def compute_pointing_batch(detectors, gps_times):
    """Turns 'straight up from this detector at this GPS time' into
    sky coordinates (RA/Dec), for many events in one astropy call.
    Returns a SkyCoord array in ICRS, same length as the inputs.
 
    Astropy is imported here, inside the function, so the script's
    friendly environment-check message still appears first on a
    machine that does not have the packages installed yet."""
    import numpy as np
    import astropy.units as u
    from astropy.coordinates import EarthLocation, AltAz, SkyCoord
    from astropy.time import Time
 
    detectors = np.asarray(detectors)
    lats = np.array([DETECTOR_LOCATIONS[d][0] for d in detectors])
    lons = np.array([DETECTOR_LOCATIONS[d][1] for d in detectors])
    heights = np.array([DETECTOR_LOCATIONS[d][2] for d in detectors])
 
    locations = EarthLocation(lat=lats * u.deg, lon=lons * u.deg, height=heights * u.m)
    times = Time(np.asarray(gps_times, dtype=float), format="gps")
    zenith = AltAz(alt=90 * u.deg, az=0 * u.deg, location=locations, obstime=times)
    return SkyCoord(zenith).icrs
 
 
def report_pointing_sanity(pointing):
    """Free sanity check. A detector's zenith only sweeps a ring of sky
    at its own latitude, so each detector's Dec should stay close to
    that latitude (H1 about 46.5, L1 about 30.6). Also checks nothing
    came out empty (NaN)."""
    print("\nPointing sanity check (zenith Dec should sit near each detector's latitude):")
    all_ok = True
    for det in sorted(pointing["detector"].unique()):
        rows = pointing[pointing["detector"] == det]
        lat = DETECTOR_LOCATIONS[det][0]
        low, high = rows["dec"].min(), rows["dec"].max()
        ok = (abs(low - lat) <= ZENITH_DEC_TOLERANCE_DEG
              and abs(high - lat) <= ZENITH_DEC_TOLERANCE_DEG)
        all_ok = all_ok and ok
        print(f"  {det}: {len(rows)} events | Dec {low:.2f} to {high:.2f} "
              f"| detector latitude {lat:.2f} | {'OK' if ok else '*** CHECK THIS ***'}")
    n_bad = int(pointing[["ra", "dec"]].isna().any(axis=1).sum())
    if n_bad:
        all_ok = False
        print(f"  *** WARNING: {n_bad} event(s) have an empty RA or Dec. ***")
    if all_ok:
        print("  All detectors pass.")
    else:
        print("  Something looks wrong - do not build Stage 3 on this until it is understood.")
 
 
def stage_2_pointing(run_context):
    """Adds zenith 'ra' and 'dec' columns (degrees) to a copy of the
    single-detector table, in chunks with progress printed. Result goes
    to run_context['pointing'] and is checkpointed per run selection."""
    import time
    import numpy as np
 
    single_det = run_context.get("single_det")
    if single_det is None or len(single_det) == 0:
        print("Stage 2 needs the single-detector events from Stage 1, and none "
              "are available - skipping.")
        return None
    run_tag = run_context["run_tag"]
 
    pointing = load_checkpoint("03_pointing", tag=run_tag)
    action = prompt_step_action("Stage 2 - pointing", has_checkpoint=(pointing is not None))
 
    if action == "checkpoint":
        print(f"   -> using checkpoint ({len(pointing)} events, skipped recompute)")
    elif action == "skip":
        print("   -> SKIPPED for this run.")
        pointing = None
    else:
        n_events = len(single_det)
        detectors = single_det["detector"].values
        gps_times = single_det["gps_time"].values.astype(float)
        ra = np.empty(n_events)
        dec = np.empty(n_events)
 
        clock = time.time()
        for start in range(0, n_events, POINTING_CHUNK_SIZE):
            end = min(start + POINTING_CHUNK_SIZE, n_events)
            coords = compute_pointing_batch(detectors[start:end], gps_times[start:end])
            ra[start:end] = coords.ra.deg
            dec[start:end] = coords.dec.deg
            print(f"   pointing {end}/{n_events} done ({time.time() - clock:.1f}s elapsed)")
 
        pointing = single_det.copy()
        pointing["ra"] = ra
        pointing["dec"] = dec
        save_checkpoint("03_pointing", pointing, tag=run_tag)
 
    if pointing is not None:
        run_context["pointing"] = pointing
        report_pointing_sanity(pointing)
    return pointing


def stage_3_galaxy_star_lookup(run_context):
    print("[Stage 3 - Galaxy and star lookup — not built yet, skipping]")
    return None


def stage_4_pairs_and_tiers(run_context):
    print("[Stage 4 - Star-galaxy pairs and deep-check tags — not built yet, skipping]")
    return None


def stage_5_diagnostics(run_context):
    print("[Stage 5 - Diagnostics (sanity checks, time-clustering) — not built yet, skipping]")
    return None


def stage_6_cross_reference(run_context):
    print("[Stage 6 - Cross-reference tables and overlap — not built yet, skipping]")
    return None


def stage_7_control_tests(run_context):
    print("[Stage 7 - Control tests — not built yet, skipping]")
    return None


def stage_8_fdr_ranking(run_context):
    print("[Stage 8 - FDR ranking of candidates — not built yet, skipping]")
    return None


def stage_9_deep_check(run_context):
    print("[Stage 9 - Gaia/NED deep check (needs network) — not built yet, skipping]")
    # When this gets built:
    #   from network_catalogs_v2 import deep_recheck
    # File A only reaches for File B here, and nowhere else.
    return None


def stage_10_cross_run_replication(run_context):
    print("[Stage 10 - Cross-run replication — not built yet, skipping]")
    return None


STAGES = [
    ("Stage 1 - Load and filter events", stage_1_load_and_filter),
    ("Stage 2 - Pointing", stage_2_pointing),
    ("Stage 3 - Galaxy and star lookup", stage_3_galaxy_star_lookup),
    ("Stage 4 - Star-galaxy pairs and deep-check tags", stage_4_pairs_and_tiers),
    ("Stage 5 - Diagnostics", stage_5_diagnostics),
    ("Stage 6 - Cross-reference tables and overlap", stage_6_cross_reference),
    ("Stage 7 - Control tests", stage_7_control_tests),
    ("Stage 8 - FDR ranking of candidates", stage_8_fdr_ranking),
    ("Stage 9 - Gaia/NED deep check", stage_9_deep_check),
    ("Stage 10 - Cross-run replication", stage_10_cross_run_replication),
]


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------
def main():
    print("=" * 70)
    print("UTO v2 — BUILD IN PROGRESS")
    print("=" * 70)

    check_venv_active()
    ask_network_permission()
    first_time_setup_check()

    selected_runs = prompt_run_selection()

    run_context = {
        "selected_runs": selected_runs,
        # more settings land here as each stage gets built for real
    }

    print("\nFull stage menu (unbuilt stages just skip themselves):")
    for label, func in STAGES:
        print(f"\n--- {label} ---")
        func(run_context)

    print("\nRun complete.")
    print("Next: copy real code into the next stub stage, test, repeat.")


if __name__ == "__main__":
    main()
