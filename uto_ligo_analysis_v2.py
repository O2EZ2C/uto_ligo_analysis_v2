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
DEFAULT_MATCH_TOLERANCE_DEG = 3.0   # one tolerance, used for both galaxies and stars around zenith
LOOKUP_EVENT_CHUNK_SIZE = 200       # events compared against a catalog at a time (memory limit)
BAND_MARGIN_DEG = 1.0               # safety margin when trimming stars to a detector's zenith band
ANTENNA_WEIGHT_THRESHOLD = 0.5      # below this an event is marked low-sensitivity (marked, not deleted)
BASELINE_O1_GALAXY_EVENTS_1DEG = 295   # old pipeline: O1, 1 degree, galaxy hits at or above the threshold

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


# ---------------------------------------------------------------------
# STEP B: STAGE 2 Pointing
# --------------------------------------------------------------------
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



# ---------------------------------------------------------------------
# STEP B: STAGE 3 FUNCTIONS
# --------------------------------------------------------------------
def angular_sep_deg(ra1, dec1, ra2, dec2):
    """Great-circle distance between sky points (haversine formula).
    Inputs in radians, answer in degrees. Works on whole tables at once:
    give it a column of events and a row of catalog objects and it
    returns every event-to-object distance."""
    import numpy as np
    dra = ra2 - ra1
    a = np.sin((dec2 - dec1) / 2) ** 2 + np.cos(dec1) * np.cos(dec2) * np.sin(dra / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(a, 0, 1))))


def pick_catalog_file(label, pattern):
    """Finds cached catalog CSVs in CATALOG_DIR. One file: uses it.
    Several: lists them with row counts and lets you pick. Enter takes
    the one with the most rows (the plan wants the most stars available).
    Returns a Path, or None if there are none."""
    files = sorted(CATALOG_DIR.glob(pattern))
    if not files:
        print(f"No {label} catalog found in the catalogs folder "
              f"(looking for {pattern}).")
        print("  Copy the cached file from the old project's outputs folder into "
              "ligo_uto_analysis/catalogs/ and run again.")
        return None
    if len(files) == 1:
        print(f"{label.capitalize()} catalog: {files[0].name}")
        return files[0]

    counts = [max(sum(1 for _ in open(f)) - 1, 0) for f in files]   # lines minus the header
    default_index = counts.index(max(counts))
    print(f"\nMore than one {label} catalog found:")
    for i, (f, n) in enumerate(zip(files, counts), start=1):
        print(f"  {i}. {f.name}  ({n} objects)")
    raw = input(f"Choose 1-{len(files)} (Enter = {default_index + 1}, the largest): ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(files):
        return files[int(raw) - 1]
    if raw:
        print("Not a valid choice - using the largest.")
    return files[default_index]


def load_catalog_table(path, label):
    """Reads a catalog CSV and checks it has the two position columns."""
    table = pd.read_csv(path)
    missing = [c for c in ("RAICRS", "DEICRS") if c not in table.columns]
    if missing:
        print(f"The {label} catalog {path.name} has no {' or '.join(missing)} column, "
              f"so it cannot be used. (Positions must be decimal degrees.)")
        return None
    print(f"  {label.capitalize()} catalog loaded: {len(table)} objects.")
    return table


def prompt_match_tolerance():
    """One tolerance in degrees, applied to galaxies AND stars around
    the zenith. Enter keeps the default."""
    raw = input(f"\nMatch tolerance around zenith in degrees, for galaxies and stars "
                f"[{DEFAULT_MATCH_TOLERANCE_DEG}]: ").strip()
    if not raw:
        return DEFAULT_MATCH_TOLERANCE_DEG
    try:
        value = float(raw)
    except ValueError:
        print(f"Could not read '{raw}' as a number - keeping {DEFAULT_MATCH_TOLERANCE_DEG}.")
        return DEFAULT_MATCH_TOLERANCE_DEG
    if value <= 0 or value != value:
        print(f"The tolerance must be above zero - keeping {DEFAULT_MATCH_TOLERANCE_DEG}.")
        return DEFAULT_MATCH_TOLERANCE_DEG
    return value


def find_galaxies_in_range(ra_rad, dec_rad, gal_ra_rad, gal_dec_rad, tolerance_deg):
    """For every event, finds every galaxy within tolerance_deg of the
    zenith point. Returns three equal-length arrays, one entry per
    event-galaxy pairing: event position in the table, galaxy position
    in the catalog, and the separation in degrees. Works through the
    events in small groups so memory stays small."""
    import numpy as np
    event_parts, galaxy_parts, sep_parts = [], [], []
    n_events = len(ra_rad)
    for start in range(0, n_events, LOOKUP_EVENT_CHUNK_SIZE):
        end = min(start + LOOKUP_EVENT_CHUNK_SIZE, n_events)
        sep = angular_sep_deg(ra_rad[start:end, None], dec_rad[start:end, None],
                              gal_ra_rad[None, :], gal_dec_rad[None, :])
        ev, gl = np.nonzero(sep <= tolerance_deg)
        event_parts.append(ev + start)
        galaxy_parts.append(gl)
        sep_parts.append(sep[ev, gl])
    if not event_parts:
        return np.array([], dtype=int), np.array([], dtype=int), np.array([])
    return np.concatenate(event_parts), np.concatenate(galaxy_parts), np.concatenate(sep_parts)


def count_stars_in_range(event_idx, ra_rad, dec_rad, detectors, star_ra_deg, star_dec_deg, tolerance_deg):
    """Counts the stars within tolerance_deg of the zenith point, for
    the events listed in event_idx only. Returns an array as long as
    the whole event table (0 for events not asked about).

    Speed-up: a detector's zenith stays near its own latitude, so per
    detector only stars within reach of that band of sky can ever
    match. Stars outside the band are dropped first. This gives the
    same answer, just faster (like only searching the aisle where the
    item is shelved)."""
    import numpy as np
    counts = np.zeros(len(ra_rad), dtype=np.int64)
    dec_deg = np.degrees(dec_rad)
    star_ra_rad = np.radians(star_ra_deg)
    star_dec_rad = np.radians(star_dec_deg)
    for det in sorted(set(detectors[event_idx])):
        rows = event_idx[detectors[event_idx] == det]
        reach = tolerance_deg + BAND_MARGIN_DEG
        keep = ((star_dec_deg >= dec_deg[rows].min() - reach) &
                (star_dec_deg <= dec_deg[rows].max() + reach))
        s_ra, s_dec = star_ra_rad[keep], star_dec_rad[keep]
        if len(s_ra) == 0:
            continue
        for start in range(0, len(rows), LOOKUP_EVENT_CHUNK_SIZE):
            chunk = rows[start:start + LOOKUP_EVENT_CHUNK_SIZE]
            sep = angular_sep_deg(ra_rad[chunk, None], dec_rad[chunk, None],
                                  s_ra[None, :], s_dec[None, :])
            counts[chunk] = np.sum(sep <= tolerance_deg, axis=1)
    return counts


def compute_antenna_weights(event_idx, detectors, gps_times, ra_deg, dec_deg):
    """Antenna pattern weight (0 = blind spot, 1 = peak sensitivity) for
    the events listed in event_idx only. Returns an array as long as
    the whole event table (NaN where not computed), or None if pycbc is
    not installed.

    Uses pycbc, the field-standard implementation, same as the old script.

    One change from the old script: it averaged the response over 200
    polarization angles. The response sqrt(Fplus^2 + Fcross^2) does not
    change when the polarization angle changes (like the length of a
    hand on a clock face not changing when you rotate the whole clock),
    so all 200 answers were identical. One angle gives the same number
    about 200 times faster."""
    import numpy as np
    try:
        from pycbc.detector import Detector
    except ImportError:
        return None
    weights = np.full(len(gps_times), np.nan)
    det_objects = {}
    for i in event_idx:
        det = detectors[i]
        if det not in det_objects:
            det_objects[det] = Detector(det)
        fp, fc = det_objects[det].antenna_pattern(
            np.radians(ra_deg[i]), np.radians(dec_deg[i]), 0.0, float(gps_times[i]))
        weights[i] = float(np.sqrt(fp ** 2 + fc ** 2))
    return weights


def stage_3_galaxy_star_lookup(run_context):
    """Stage 3 - the 'guest list'. For every event, finds the galaxies
    within tolerance of that moment's zenith point, counts the stars in
    range at the same moment, then adds the antenna weight (only for
    events that have at least one galaxy in range).

    Result: one row per event-galaxy pairing, in
    run_context['event_galaxy']. The catalogs and tolerance are also
    stored in run_context for Stage 4 (star-galaxy pairs)."""
    import time
    import numpy as np

    pointing = run_context.get("pointing")
    if pointing is None or len(pointing) == 0:
        print("Stage 3 needs the pointing table from Stage 2, and none is "
              "available - skipping.")
        return None
    run_tag = run_context["run_tag"]

    # --- catalogs and tolerance ---
    galaxy_path = pick_catalog_file("galaxy", "galaxy_catalog_cache*.csv")
    star_path = pick_catalog_file("star", "star_catalog_cache*.csv")
    if galaxy_path is None or star_path is None:
        return None
    galaxy_table = load_catalog_table(galaxy_path, "galaxy")
    star_table = load_catalog_table(star_path, "star")
    if galaxy_table is None or star_table is None:
        return None
    if len(star_table) < 10000:
        print(f"  NOTE: the star catalog has only {len(star_table)} stars, which looks like "
              f"a bright-stars-only cut. The plan wants the most stars available, so "
              f"star counts from this file will be low.")
    tolerance = prompt_match_tolerance()

    name_col = "Name" if "Name" in galaxy_table.columns else galaxy_table.columns[0]
    galaxy_names = galaxy_table[name_col].astype(str).str.strip().values

    tag = f"{run_tag}_tol{tolerance:g}_{star_path.stem}_{galaxy_path.stem}"
    result = load_checkpoint("04_lookup", tag=tag)
    action = prompt_step_action("Stage 3 - galaxy and star lookup", has_checkpoint=(result is not None))

    if action == "checkpoint":
        print(f"   -> using checkpoint ({len(result['event_galaxy'])} event-galaxy pairings, skipped recompute)")
    elif action == "skip":
        print("   -> SKIPPED for this run.")
        return None
    else:
        clock = time.time()
        detectors = pointing["detector"].values
        gps_times = pointing["gps_time"].values.astype(float)
        ra_deg = pointing["ra"].values.astype(float)
        dec_deg = pointing["dec"].values.astype(float)
        ra_rad, dec_rad = np.radians(ra_deg), np.radians(dec_deg)

        # 1. Galaxies in range of each event's zenith.
        ev_idx, gal_idx, gal_sep = find_galaxies_in_range(
            ra_rad, dec_rad,
            np.radians(galaxy_table["RAICRS"].values.astype(float)),
            np.radians(galaxy_table["DEICRS"].values.astype(float)),
            tolerance,
        )
        events_with_galaxy = np.unique(ev_idx)
        print(f"   galaxy matching done: {len(events_with_galaxy)} of {len(pointing)} events "
              f"have a galaxy in range ({time.time() - clock:.1f}s)")

        # 2. Stars in range at those same moments (only events that have a galaxy).
        star_counts = count_stars_in_range(
            events_with_galaxy, ra_rad, dec_rad, detectors,
            star_table["RAICRS"].values.astype(float),
            star_table["DEICRS"].values.astype(float), tolerance,
        )
        print(f"   star counting done ({time.time() - clock:.1f}s)")

        # 3. Antenna weight, last, and only for events that have a galaxy.
        weights = compute_antenna_weights(events_with_galaxy, detectors, gps_times, ra_deg, dec_deg)
        if weights is None:
            print("   WARNING: pycbc is not installed in this environment, so antenna weights "
                  "were NOT computed (column left empty, nothing marked low-sensitivity). "
                  "Install it with:  pip install pycbc   (large download), then rerun this stage.")
            weights = np.full(len(pointing), np.nan)
        else:
            print(f"   antenna weights done ({time.time() - clock:.1f}s)")

        keep_cols = [c for c in ["observing_run", "gps_time", "detector", "ml_label", "ra", "dec"]
                     if c in pointing.columns]
        event_galaxy = pointing.iloc[ev_idx][keep_cols].reset_index(drop=True)
        event_galaxy["galaxy_name"] = galaxy_names[gal_idx]
        event_galaxy["galaxy_sep_deg"] = gal_sep
        event_galaxy["antenna_weight"] = weights[ev_idx]
        event_galaxy["low_sensitivity"] = event_galaxy["antenna_weight"] < ANTENNA_WEIGHT_THRESHOLD
        event_galaxy["stars_in_range"] = star_counts[ev_idx]
        event_galaxy = event_galaxy.sort_values(["gps_time", "galaxy_sep_deg"]).reset_index(drop=True)

        result = {
            "event_galaxy": event_galaxy,
            "tolerance_deg": tolerance,
            "n_events": len(pointing),
            "n_galaxies": len(galaxy_table),
            "n_stars": len(star_table),
            "weights_computed": not np.isnan(weights[events_with_galaxy]).any() if len(events_with_galaxy) else True,
        }
        save_checkpoint("04_lookup", result, tag=tag)

    run_context["event_galaxy"] = result["event_galaxy"]
    run_context["galaxy_table"] = galaxy_table
    run_context["star_table"] = star_table
    run_context["match_tolerance_deg"] = result["tolerance_deg"]
    report_lookup_summary(result, run_context)
    return result["event_galaxy"]


def report_lookup_summary(result, run_context):
    """Prints what Stage 3 found and runs the built-in checks."""
    import numpy as np
    df = result["event_galaxy"]
    tol = result["tolerance_deg"]
    n_events = result["n_events"]

    print("\nStage 3 summary")
    print("-" * 50)
    print(f"Tolerance: {tol} deg | events tested: {n_events} | "
          f"galaxies in catalog: {result['n_galaxies']} | stars in catalog: {result['n_stars']}")
    if len(df) == 0:
        print("No event had a galaxy in range at this tolerance.")
        return

    events = df.drop_duplicates(["gps_time", "detector"])
    print(f"Events with at least one galaxy in range: {len(events)} "
          f"({len(events) / n_events:.1%} of all events)")
    print(f"Event-galaxy pairings (one row each): {len(df)}")
    for det in sorted(events["detector"].unique()):
        print(f"  {det}: {int((events['detector'] == det).sum())} events with a galaxy in range")

    weights_ok = result.get("weights_computed", False)
    if weights_ok:
        usable = events[~events["low_sensitivity"]]
        print(f"Of those, at or above the antenna threshold ({ANTENNA_WEIGHT_THRESHOLD}): {len(usable)}; "
              f"marked low-sensitivity: {len(events) - len(usable)}")
    else:
        print("Antenna weights not available, so no events are marked low-sensitivity.")
    print(f"Stars in range at those moments: min {int(events['stars_in_range'].min())}, "
          f"mean {events['stars_in_range'].mean():.1f}, max {int(events['stars_in_range'].max())}")

    print("\nBuilt-in checks:")
    ok = True
    if (df["galaxy_sep_deg"] > tol + 1e-9).any():
        ok = False
        print("  *** WARNING: some pairings are further away than the tolerance. Something is wrong. ***")
    if df[["ra", "dec", "galaxy_sep_deg"]].isna().any().any():
        ok = False
        print("  *** WARNING: some rows have an empty position or separation. ***")
    if ok:
        print("  Every pairing is within tolerance and no values are empty. OK.")

    selected = run_context.get("selected_runs") or []
    if selected == ["O1"] and abs(tol - 1.0) < 1e-9 and weights_ok:
        n_now = len(events[~events["low_sensitivity"]])
        verdict = "OK" if n_now == BASELINE_O1_GALAXY_EVENTS_1DEG else "*** DOES NOT MATCH ***"
        print(f"  Old-pipeline check (O1, 1 degree): {n_now} events now vs "
              f"{BASELINE_O1_GALAXY_EVENTS_1DEG} before -> {verdict}")
    elif selected == ["O1"] and abs(tol - 1.0) < 1e-9:
        print("  Old-pipeline check (O1, 1 degree, expects 295) skipped: it needs antenna weights.")
    else:
        print("  Old-pipeline check only runs for O1 at 1 degree. Rerun with those "
              "settings to compare against the old 295.")

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
def ask_run_again():
    """After a run: True = start over from run selection, False = exit.
    Enter means exit."""
    while True:
        raw = input(
            "\nWhat next? [R]un again from run selection / [Q]uit [Q]: "
        ).strip().lower()
        if raw in ("", "q", "quit", "exit"):
            return False
        if raw in ("r", "run", "again", "restart"):
            return True
        print("Please type R to run again, or Q to quit.")


def run_pipeline_once():
    """One full pass: pick runs, then go through every stage in order.
    Builds a fresh run_context each time, so nothing from the previous
    pass leaks into the next one."""
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


def main():
    print("=" * 70)
    print("UTO v2 — BUILD IN PROGRESS")
    print("=" * 70)

    # Once per launch:
    check_venv_active()
    ask_network_permission()
    first_time_setup_check()

    # Once per pass. Loops until you choose to quit.
    while True:
        run_pipeline_once()
        if not ask_run_again():
            break

    print("\nExiting. Checkpoints and outputs are saved.")
    print("Next: copy real code into the next stub stage, test, repeat.")


if __name__ == "__main__":
    main()
