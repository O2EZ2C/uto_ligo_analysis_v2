# Context Document: uto_ligo_analysis_v2

This document is the working spec for the new script. It is meant to be fed back in as context at the start of each build session, and updated as decisions change. Nothing in here is final until it's built and tested — treat it as the plan, not a record of what exists yet.

## 1. What this script is for

The current pipeline (`uto_ligo_analysis.py`) answers "does a star or galaxy sit near a detector's zenith at a glitch's moment, more often than random timing would produce." That question needed a control test, because a star-only hit tells you nothing on its own — with a wide enough search radius, almost every event finds something.

This script answers a different, narrower question: for events where a galaxy is near zenith, which stars sit very close to that galaxy's own centre. This is a plain lookup, not a statistical claim, so on its own it needs no control test. Two lookups, done once each, then combined:

- **The guest list** — for each glitch, which galaxies and which stars are near the detector's zenith at that exact moment. This has time in it (it depends on when the glitch happened) and does need a control test eventually, to check whether the timing lines up with real overhead moments more than chance.
- **The seating chart** — which star sits near which galaxy's centre, in absolute sky position. This has no time in it at all — stars and galaxies don't move in this analysis, so it's a fixed map built once from the catalogs.

The two are combined by checking, for events where a galaxy IS on the guest list, whether any of the seating chart's pairs for that galaxy are ALSO on the guest list. Tight pairs get tagged for later deep-catalog follow-up.

## 2. Relationship to the existing project

- This is the final version, and it replaces both `uto_ligo_analysis.py` and the cross-reference script. It borrows ideas and logic from both, but doesn't import from either — everything it needs is copied in, since the originals are being retired.
- The two old scripts and the existing data pool (raw CSVs, checkpoints, cached catalogs, results) are kept permanently, not just during migration. They serve as an ongoing control/reference to test the new script against, even after it's trusted.
- The new script starts in a **completely new directory** of its own (name and exact location TBA), not nested inside the existing `Ligo_Analysis` folder. This keeps its checkpoints, outputs, and catalogs entirely separate from the old scripts' — nothing gets silently overwritten or reused across the two.
- Before the old scripts are archived (moved aside, never deleted), the new script has to pass acceptance tests against known numbers from the old pipeline (see Section 8).

## 3. File structure

Two files, split from the start:

- **File A** — everything that never touches the network. Loading local CSVs, pointing math, the galaxy/star lookup, the pairs and tier tagging, diagnostics, control tests (which use pre-downloaded catalogs, no live calls), ranking. This is the file that gets built, run, and tested almost every day.
- **File B** — only the network-touching functions: the star/galaxy catalog downloads, and the Gaia/NED deep-recheck. File A imports File B only when a catalog is missing or the deep check is explicitly requested. Until then, File A never even loads it.

This means "the galaxy/star lookup is all one thing until network" is a literal file boundary, not just a mental one.

## 4. Build approach

- Build a **core skeleton first**, then add one stage at a time, manually copied in by hand and tested as it goes, rather than one large build.
- The **full stage menu is shown from day one** (not grown incrementally), with stages that don't have code yet printing "not built yet, skipping." The user plans to build in order anyway but wanted the flexibility.
- **Build order** (as currently understood — the exact order may differ from the numbered stage list below, per the user; will be confirmed when building starts):
  1. Lookup / pairs / tier tagging (File A's new work)
  2. The rest of File A's offline stages (diagnostics, ranking, etc.)
  3. File B (network: downloads, deep check)
  4. Control tests (deliberately built *after* File B, later than originally planned)
- Each stage keeps a checkpoint/rerun/skip prompt. Checkpoints reuse existing results wherever settings still match, and only recompute the specific parts whose settings changed — not an all-or-nothing rerun.
- No incremental README/documentation during the build. This context document is the running spec; anything README-relevant that comes up gets added here. Once the whole script is built, documentation is written in **one pass**, using this full context plus the finished script.
- The existing `editing_code_safely_guide.md` is considered outdated for the user's current skill level. When the first section actually gets built, that session will be used to write a new, updated editing guide reflecting what the user needs to learn at that point — replacing the old one.

## 5. Stage list (reference — order TBD)

1. Load and filter events
2. Pointing and antenna weight
3. Galaxy and star lookup (new)
4. Star-galaxy pairs and deep-check tags (new)
5. Diagnostics (sanity checks, time-clustering)
6. Cross-reference tables and overlap
7. Control tests
8. FDR ranking of candidates
9. Gaia/NED deep check (needs network)
10. Cross-run replication

## 6. Run setup and inputs

- **Runs**: numbered list of runs found in the raw-CSV folder; pick by number, comma-list, or "all"; Enter defaults to all.
- **Multi-run results**: both — every run gets its own output files, plus a combined file (with an `observing_run` column) when more than one run is picked.
- **Detectors**: prompt lists detectors found in the picked CSVs; Enter selects all.
- **Glitch classes / confidence**: same 7-class / 0.9-confidence defaults as the old script, shown at the start, only changeable through an advanced-settings prompt.
- **Virtual environment check**: hard stop at startup if the venv isn't active — this is what broke the old background-run attempt. Shows a clear warning, won't proceed without it.
- **First-time setup check**: runs automatically the first time (lists any missing folders/files and where to get them), and is also available afterward as an on-demand menu option.

## 7. The lookup itself

- **Search scope**: the user only needs a small target list of galaxies for a later, larger pass — roughly 7 degrees of sky around the detector's calculated zenith "pointing direction." This is just the ordinary tolerance-radius search around zenith, not a wide declination-band precomputation.
  - *Future idea, not now*: eventually also look "behind" zenith (nadir) or at 90 degrees off zenith (horizon), tying into the alternate `alt=0` / arm-bisector-azimuth pointing already sketched in `uto_ligo_analysis.py`'s `compute_pointing()` docstring. The observing angle used will change eventually, so this should stay easy to adjust later.
- **Tolerance**: star tolerance and galaxy tolerance are **the same single value**, prompted once, applied to both catalogs around zenith. Default scale ~3 degrees (galaxy tolerance from the original request).
- **The pairing rule**: a galaxy within tolerance of zenith, and a star within the pairing distance of that galaxy's centre. No gate requiring the star itself to also be within zenith tolerance — only the pair itself matters right now. (No separate yes/no tracking column for this either, per the user.)
- **Pairing distance**: default 0.08 degrees from the galaxy's centre, changeable at the prompt. Every pair found within whatever value is entered gets its real separation saved, so a tighter cut can be applied later from the saved data without rerunning.
- **Antenna pattern weight**: kept as a double-check, computed only for events that already have at least one galaxy in range (saves time). Events below the 0.5 threshold are marked, not deleted; threshold lives in advanced settings.
- **Star magnitude range**: not filtering by magnitude. Wants the maximum number of stars available from the existing/first-run catalog, since what matters is which stars fall within distance of a galaxy, not brightness. (This closes out the old deferred "magnitude min+max" item — it's moot for this script.)

## 8. Deep-check tier rules

A pair gets tagged for possible deep-catalog follow-up based on how tight the star-galaxy separation is, or how crowded a galaxy's circle is:

- **Tier 1**: a star within **0.0001 degrees** of a galaxy's centre.
- **Tier 2**: a star within **0.008 degrees** of a galaxy's centre.
- **Tier 3**: a galaxy with **2 or more stars** within **0.03 degrees** of it.
- Everything else found within the outer 0.08-degree pairing distance, but not meeting any tier rule, is listed/recorded but not tiered.
- **Separate flag** (not part of the tier system): a star that pairs with more than one *different* galaxy. The user isn't sure why this would happen (has guesses, not certainty) and wants to know if it occurs.

## 9. What gets saved

- **Event-galaxy file**: one row per event-galaxy pairing. Columns: observing run, gps time, detector, glitch class, zenith RA/Dec, galaxy name, galaxy's distance from zenith, antenna weight, count of stars in range at that moment.
  - No full per-event star list for now (skipped, not designed out — the user says they'll need this "someday," so keep it easy to add back).
- **Pairs file**: the file the user actually cares about right now. Organized per galaxy (galaxies are the primary targets): galaxy name, star ID, separation, which run/detector/gps time/glitch class it came from. The multi-galaxy-star flag (Section 8) surfaces here too.
- **Deep-check candidates file**: pairs/galaxies meeting a tier rule, with a reason column.
- **Output folders**: one folder per run, named from settings (e.g. `O1_gal3_pair0.08`). **Never overwrite an existing output folder without asking first** — this is a hard safeguard, not a default-overwrite. Folders are meant to be kept around long-term so a run's details can be reviewed later without redoing the whole run.
- **Settings record + run log**: every output folder gets a settings file listing everything used for that run; every run also appends one line to a running log, so past runs can be reviewed even without opening their folders.
- **Chance-expectation estimate**: a quick, non-control-test number (star density × circle area × number of galaxies) printed once at the end of a run, for rough context next to the real pair count. Not a real statistical test.

## 10. Safeguards carried over / added

Carried over from the old scripts:
- Network switch with per-call confirmation
- Raw inputs kept apart from outputs
- Checkpoints tagged by settings
- Consistency checks against known/prior results
- Sanity checks (dominant object, duplicates, bad coordinates)
- Time-clustering storm warnings
- Self-checks (e.g. "every pair event must also be a joint event")
- Never reporting a p-value as exactly zero
- Warnings for events outside known run windows

New for this script:
- **Never overwrite an output folder without asking** (hard safeguard — see Section 9)
- **Virtual environment check**: warning, hard stop if venv isn't active
- **First-time setup check**: automatic on first run, available on demand afterward
- **Two-layer network switch**: startup prompt "Allow live network calls this run? [y/N]" (default No) as the outer layer, plus each individual network call still asks its own y/N — this replaces the old code-edit `ALLOW_NETWORK = True/False` switch, matching the README's stated plan to move it into the wrapper.
- **Built-in self-check against the old pipeline**: when a matching run/tolerance exists in the old pipeline's checkpoints, automatically compare and print OK or a warning (e.g. a 1-degree run should reproduce the old 295-galaxy-hit result for O1).

## 11. Folders

- Dedicated **catalogs folder** for cached inputs (star/galaxy catalog CSVs), separate from outputs — inputs and outputs were mixed in the old script only because it was the user's first build and had to generate the cache somewhere. Going forward, anything downloaded goes in the folder that matches what it actually is.
- Script finds its own folder at startup and builds every path relative to that — no home-folder names anywhere in the code, since it's going on GitHub.

## 12. Memory / performance

- Small-chunk approach carried over from the old scripts: events compared in groups of 200, pointing calculated in groups of 5,000. Progress + elapsed time printed after each chunk.
- Chunk sizes exposed as adjustable settings (advanced settings), not hard-coded constants.

## 13. Acceptance tests (before archiving the old scripts)

Baseline checks against the old pipeline's known O1 numbers:
1. 4,784 single-detector events
2. 295 events with a galaxy within 1 degree
3. The 6 pair events for star 58937 + galaxy IC2992 at a pairing distance of 0.05 degrees
4. Joint control p-values of 0.9680 and 0.8860, using seed 42

These are a starting baseline, not a one-time gate — the old scripts and data pool stay as a permanent reference the new script can always be checked against.

## 14. Control tests (built later, after File B)

- Left as a clearly separate, optional section/stage — not mixed into the lookup itself, since the lookup (the "seating chart") has no time in it and can't be tested by shuffling glitch times. Only the "guest list" (galaxy/star-in-range-at-a-moment) has time in it and needs the control test treatment, the same way the existing v5 cross-reference script already does.
- Exact design (number of tests, seed defaults, speed optimizations like the zenith-band trim) to be revisited when this stage is actually built, since it now comes after File B rather than early on.

## 15. Open / deferred items

- New directory name and exact location — TBA.
- Whether raw CSVs get copied into the new directory or read from the existing `Ligo_Analysis/raw_csvs/` — TBA.
- Full per-event star-in-range list output — deferred, not designed out.
- Exact stage build order — will be specified when building starts.
- Magnitude range filter — dropped as moot for this script.
- Looking "behind" zenith or at the horizon — future idea, not now.
