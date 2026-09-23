# UTO v2 — Design Specification

**Status: design complete, build in progress.** This document describes the
architecture and design decisions for `uto_ligo_analysis_v2.py`, the
successor to `uto_ligo_analysis.py` and `cross_reference.py`. It's written
to be read on its own — by a talent assessor, a collaborator, or a future
version of the author picking the project back up.

For the underlying question the whole pipeline is answering (does a
single-detector glitch's pointing direction line up with a real star or
galaxy more often than chance), see the main `README.md`.

---

## 1. What v2 Is For

The v1 pipeline (`uto_ligo_analysis.py`) answers: *"does a star or galaxy
sit near a detector's zenith at a glitch's moment, more often than random
timing would predict?"* That question needs a control test, because a
raw hit count means nothing on its own — with a wide enough search radius,
almost every event finds something nearby.

v2 answers a narrower, second question: for events where a galaxy is near
zenith, which stars sit very close to that galaxy's own centre. This is a
geometric lookup, not a statistical claim, so on its own it needs no
control test yet. It's built from two separate pieces:

- **The guest list** — for each glitch, which galaxies and which stars are
  near the detector's zenith at that exact moment. This depends on *when*
  the glitch happened, and will eventually get its own control test (built
  later — see Section 8).
- **The seating chart** — which star sits near which galaxy's centre, in
  fixed sky position. This has no time dependency at all: catalog objects
  don't move in this analysis, so it's built once from the catalogs
  themselves.

The two are combined by checking, for events where a galaxy *is* on the
guest list, whether any of the seating chart's pairs for that galaxy are
*also* on the guest list. Tight pairs get flagged for later deep-catalog
follow-up.

## 2. Relationship to the Existing Pipeline

- v2 is the final, consolidated version. It replaces both
  `uto_ligo_analysis.py` and `cross_reference.py`, reusing their logic but
  not importing from either — both originals are being retired.
- Both older scripts, and the data pool they produced, are being kept
  permanently as a reference implementation — not just during migration.
  v2's results are checked against them on an ongoing basis, not just once
  at launch (see Section 9, Acceptance Tests).
- v2 lives in its own top-level project directory, entirely separate from
  the v1 scripts' checkpoints, outputs, and cached catalogs, so nothing
  gets silently overwritten or reused across the two.

## 3. Architecture: File A / File B Split

The project is split into two files from the start, along a strict
boundary: whether a function touches the network.

| File | Contents |
|---|---|
| **File A** (`uto_ligo_analysis_v2.py`) | Everything offline: loading local CSVs, pointing math, the galaxy/star lookup, pairing and tier logic, diagnostics, control tests (run against pre-downloaded catalogs), ranking. This is the file that gets built, run, and tested almost every day. |
| **File B** (`network_catalogs_v2.py`) | Only the network-touching functions: star/galaxy catalog downloads, and the Gaia/NED deep-recheck. |

File A imports File B only inside the two code paths that actually need
it (a missing cached catalog, or an explicit deep-recheck run) — never at
the top of the file. A normal offline run never loads File B at all.

## 4. Build Approach

- A **core skeleton** is built first: folder setup, environment checks,
  the network-permission gate, generic checkpoint helpers, and the full
  10-stage menu (Section 5) with every stage as a stub that prints
  *"not built yet, skipping."*
- Stages are then filled in **one at a time**, tested individually before
  moving to the next, rather than one large build. The stub menu means
  every future piece has a visible slot from day one, even before it has
  code.
- Each stage keeps its own checkpoint/rerun/skip prompt. Checkpoints are
  reused wherever their settings still match, and only the specific parts
  whose settings changed get recomputed — not an all-or-nothing rerun.
- Documentation is written in one pass, after the script is functionally
  complete, using the full design history plus the finished code — rather
  than kept incrementally in sync during the build.

## 5. Stage List

The pipeline is organized into ten stages. Build order does not match
this numbering — the galaxy/star lookup (Stages 3–4) is built first,
since it's the new core logic; the rest of the offline stages follow,
then the network-only file, then control tests last.

1. Load and filter events
2. Pointing and antenna weight
3. Galaxy and star lookup
4. Star-galaxy pairs and deep-check tags
5. Diagnostics (sanity checks, time-clustering)
6. Cross-reference tables and overlap
7. Control tests
8. FDR ranking of candidates
9. Gaia/NED deep check (network)
10. Cross-run replication

## 6. Run Setup & Inputs

- **Run selection** — a numbered list of observing runs detected in the
  raw-CSV folder; pick by number, comma-list, or "all" (Enter defaults to
  all).
- **Multi-run results** — each selected run gets its own output files,
  plus a combined file (tagged with an `observing_run` column) whenever
  more than one run is selected.
- **Detectors** — prompted from whichever detectors are actually present
  in the selected CSVs (Enter selects all).
- **Glitch classes / confidence threshold** — same defaults as v1 (7
  unexplained-cause classes, 0.9 minimum ML confidence), changeable only
  through an advanced-settings prompt, not the main flow.
- **Virtual environment check** — a hard stop at startup if the Python
  virtual environment isn't active, with a clear activation message.
- **First-time setup check** — runs automatically on first launch (lists
  any missing folders/files and where to get them), and is also available
  afterward as an on-demand menu option.

## 7. The Galaxy–Star Lookup

- **Search scope** — a fixed-radius search around the detector's zenith
  pointing direction (the same tolerance-radius concept as v1), rather
  than a full declination-band precomputation. A future, not-yet-planned
  extension may also check the nadir or horizon directions.
- **Tolerance** — one shared tolerance value (default ~3°) applies to
  both the star and galaxy searches around zenith.
- **Pairing rule** — a galaxy within tolerance of zenith, and a star
  within a separate, adjustable pairing distance of that galaxy's centre.
  The paired star is not additionally required to be within zenith
  tolerance itself — only the pair relationship matters for this stage.
- **Pairing distance** — default 0.08°, adjustable at the prompt. Every
  pair found within the chosen distance has its real separation saved, so
  a tighter cut can be applied later from the saved data without
  rerunning the search.
- **Antenna pattern weight** — kept as a double-check, computed only for
  events that already have at least one galaxy in range. Events below the
  sensitivity threshold (default 0.5) are flagged, not discarded.
- **Star magnitude** — not filtered. v2 pulls the maximum number of stars
  available from the catalog, since what matters for this lookup is
  proximity to a galaxy, not brightness.

## 8. Deep-Check Tier Rules

Each star-galaxy pair is tagged for possible deep-catalog follow-up based
on separation tightness or local crowding:

| Tier | Rule |
|---|---|
| Tier 1 | A star within **0.0001°** of a galaxy's centre |
| Tier 2 | A star within **0.008°** of a galaxy's centre |
| Tier 3 | A galaxy with **2 or more stars** within **0.03°** of it |
| Untiered | Found within the outer 0.08° pairing distance, but doesn't meet any tier rule above — still recorded |

A separate flag (outside the tier system) marks any star that pairs with
more than one *different* galaxy, since that's an unexpected enough
pattern to want visibility into, whatever the eventual explanation turns
out to be.

## 9. Outputs & File Layout

- **Event-galaxy file** — one row per event-galaxy pairing: observing
  run, GPS time, detector, glitch class, zenith RA/Dec, galaxy name,
  galaxy's distance from zenith, antenna weight, and count of stars in
  range at that moment.
- **Pairs file** — the primary output, organized per galaxy: galaxy name,
  star ID, separation, and the run/detector/GPS time/glitch class it came
  from. The multi-galaxy-star flag (Section 8) surfaces here too.
- **Deep-check candidates file** — pairs/galaxies meeting a tier rule,
  with a reason column.
- **Output folders** — one folder per run, named from its settings (e.g.
  `O1_gal3_pair0.08`). An existing output folder is never overwritten
  without an explicit prompt — folders are meant to be kept long-term so
  a run can be reviewed later without redoing it.
- **Settings record + run log** — every output folder gets a settings
  file listing everything used for that run; every run also appends one
  line to a running log, so past runs can be reviewed without opening
  their folders individually.
- **Chance-expectation estimate** — a quick, non-control-test number
  (star density × search-circle area × galaxy count) printed once at the
  end of a run, for rough context next to the real pair count. This is
  not a substitute for the control test in Section 8's Stage 7.

## 10. Safeguards

Carried over from v1:

- Network calls gated behind an explicit switch, with per-call
  confirmation on top
- Raw inputs kept physically separate from generated outputs
- Checkpoints tagged by the settings that produced them
- Consistency checks against known/prior results
- Sanity checks (dominant-object bias, duplicate events, bad coordinates)
- Time-clustering storm warnings
- Internal self-checks (e.g. "every pair event must also be a joint
  event")
- p-values are never reported as exactly zero (reported as an upper
  bound instead)
- Warnings for events falling outside known observing-run windows

New in v2:

- **Output folders are never overwritten without an explicit prompt**
- **Hard-stop virtual environment check** at startup
- **First-time setup check**, automatic on first run, available on demand
  afterward
- **Two-layer network switch** — a single startup prompt ("Allow live
  network calls this run?", default No) as the outer gate, with each
  individual network call still asking its own confirmation on top
- **Automatic cross-check against the v1 pipeline** — when a matching
  run/tolerance combination exists in v1's checkpoints, v2 automatically
  compares its own result against it and prints OK or a warning

## 11. Performance & Memory

- Events are compared against the catalog in small chunks (default 200
  at a time); detector pointing is computed in larger batches (default
  5,000 at a time). Progress and elapsed time are printed after each
  chunk.
- Chunk sizes are exposed as adjustable settings rather than hard-coded
  constants, since the right size depends on catalog size and available
  memory.

## 12. Acceptance Tests

Before the v1 scripts are archived, v2 is checked against known baseline
numbers from the v1 pipeline's O1 run:

1. 4,784 single-detector events
2. 295 events with a galaxy within 1°
3. 6 pair events for a specific star/galaxy pair at a 0.05° pairing
   distance
4. Joint control-test p-values of 0.9680 and 0.8860, using a fixed random
   seed

These are a starting baseline, not a one-time gate: the v1 scripts and
data pool remain a permanent reference that v2 can always be re-checked
against, even after it's trusted.

## 13. Open / Deferred Items

- Exact new-directory name and location for v2
- Whether raw CSVs are copied into the new directory or read from the
  existing raw-data folder
- Full per-event star-in-range list output (deferred, not designed out)
- Exact stage build order beyond "lookup and pairs first"
- Looking behind zenith (nadir) or at the horizon as alternate pointing
  directions — a future idea, not part of the current build
