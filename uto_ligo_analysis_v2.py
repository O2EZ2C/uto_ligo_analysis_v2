"""
UTO v2 — Skeleton (File A: offline-only)
==========================================

STATUS: SKELETON. Every stage function below is a stub that just
prints "not built yet, skipping". This file is meant to be built one
stage at a time — copy real code into one stub, test it, move on.
See v2_script_context_document.md for the full design spec this
follows.

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
import pickle
from pathlib import Path

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
        print("Activate it first, e.g.:")
        print("    source ligo-env/bin/activate")
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
# STAGES — full menu shown from day one (per the context doc), even
# though most of these are empty right now. Build order will NOT
# match this numbering (Stage 3/4 first, per the plan) — this list is
# just the reference menu, not the build order.
# ---------------------------------------------------------------------

def stage_1_load_and_filter(run_context):
    print("[Stage 1 - Load and filter events — not built yet, skipping]")
    return None


def stage_2_pointing_and_weight(run_context):
    print("[Stage 2 - Pointing and antenna weight — not built yet, skipping]")
    return None


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
    ("Stage 2 - Pointing and antenna weight", stage_2_pointing_and_weight),
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
# RUN SELECTION — stub. Will list runs found in RAW_CSV_DIR, pick by
# number / comma-list / "all" (Enter = all).
# ---------------------------------------------------------------------
def prompt_run_selection():
    print("[Run selection prompt — not built yet, skipping. Using 'all' as a placeholder.]")
    return "all"


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------
def main():
    print("=" * 70)
    print("UTO v2 — SKELETON BUILD")
    print("=" * 70)

    check_venv_active()
    first_time_setup_check()

    selected_runs = prompt_run_selection()
    ask_network_permission()

    run_context = {
        "selected_runs": selected_runs,
        # more settings land here as each stage gets built for real
    }

    print("\nFull stage menu (unbuilt stages just skip themselves):")
    for label, func in STAGES:
        print(f"\n--- {label} ---")
        func(run_context)

    print("\nSkeleton run complete. No real analysis done yet.")
    print("Next: copy real code into one stage function at a time, test, repeat.")


if __name__ == "__main__":
    main()
