"""Constants shared by the curve-tracer server modules: run defaults,
id patterns and request size bounds."""

from __future__ import annotations

import re

from scripts.run_algorithm import BOARD_I_MAX, BOARD_V_MAX, BOARD_V_OUT_MAX

# Hard ceiling on how long a live run can drive the converter, regardless
# of what the operator asks for - the backstop against a run nobody
# remembered to stop (a closed browser tab, a dropped connection). Also
# the duration used when the operator doesn't specify one at all.
_MAX_RUN_DURATION_S = 600.0

# What a run lasts unless the operator says otherwise. Short on purpose:
# this drives a real converter, and a run is something you watch, so the
# default is the length of a look rather than the length of the backstop.
_DEFAULT_RUN_DURATION_S = 10.0

# Duty the algorithm is seeded with. It is not a cosmetic starting point -
# the local trackers hill-climb from here, so on a multi-peak curve it
# decides which maximum they settle on. Exposed so that can be explored
# rather than fixed at whatever the first run happened to use.
_DEFAULT_INITIAL_DUTY = 0.5

# Safety bounds a run is held to unless the operator narrows them: the
# board limits from run_algorithm.py, so the CLI and the UI enforce the
# same values. Served by GET /api/run-config so the page shows the values
# actually enforced. The converter output limit stays under the on-chip
# ADC's `Low` range (~27 V), so the reading that trips it is a real one,
# and well under C15's 100 V rating.
_DEFAULT_V_MAX = BOARD_V_MAX
_DEFAULT_I_MAX = BOARD_I_MAX
_DEFAULT_V_OUT_MAX = BOARD_V_OUT_MAX

# How long a commanded sweep can block a run start without showing any
# progress. Longer than auto-range (one to three seconds); a sweep that
# aborts before its first point (a dark panel) only clears this way.
_SWEEP_PENDING_TIMEOUT_S = 15.0

# Live /api/runs/live polling only ever needs enough points to draw a
# chart, not the full record (that's what the saved RunRecord is for) -
# smaller than _DEFAULT_MAX_SAMPLES because this endpoint is polled
# repeatedly for the run's whole duration, not fetched once.
_DEFAULT_LIVE_MAX_SAMPLES = 500

# A simulated control-loop step is essentially free, so an unpaced loop
# would blow through thousands of samples before a poll of
# GET /api/runs/live could ever observe them - nothing to watch. This
# paces it to a cadence a person can actually follow; it is not tied to
# any real hardware timing.
_SIMULATED_RUN_PERIOD_S = 0.05

# A fixed operating point for a simulated run to track - not calibrated to
# any particular board, matching harness/panel_config.py's
# make_static_source default.
_SIMULATED_LOAD_RESISTANCE = 41.0

# Bounds on inline `curve_points` for a simulated run. A captured sweep is
# a few dozen points; the cap only stops an oversized body from building
# a huge table on the server.
_MAX_INLINE_CURVE_POINTS = 2000

# Points drawn for the built-in panel's reference curve when a simulated
# run has no chosen curve - enough for a smooth line on the live chart.
_BUILTIN_REFERENCE_POINTS = 60


# A run's URL id is its filename stem (library.save's naming scheme), never
# a filesystem path - accepting a path directly in the URL would let a
# client read or delete anything the server process can reach. The
# character set matches what `library._slug` plus the `{captured_at}`
# timestamp can ever produce; in particular it excludes "/", so a path
# segment can never smuggle in a directory component.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# Same scheme, same reasoning, for curves - mpp_sdk/curves/library.py's
# save() names files identically to the run library's.
_CURVE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# Same scheme, same reasoning, for sessions - mpp_sdk/sessions/library.py's
# save() names files identically (a session's id is also its filename
# stem, see SessionRecord's docstring for why it's stored in the body too).
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# Same scheme, same reasoning, for panel models - mpp_sdk/panels/library.py's
# save() names files identically.
_PANEL_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# String bounds for POST/PATCH /api/panels - an operator types these by
# hand (or a picker composes them), so a mistaken paste must not be able
# to grow a library file without limit. Matches mpp_sdk/panels/record.py's
# own bounds, checked again here so a bad request is rejected before it
# ever reaches the library layer.
_PANEL_NAME_MAX_LEN = 200
_PANEL_MANUFACTURER_MAX_LEN = 200
_PANEL_MODEL_MAX_LEN = 200
_PANEL_NOTES_MAX_LEN = 2000

# String/list size bounds for POST/PATCH /api/sessions - an operator types
# these by hand, so a mistaken paste or a runaway client script must not
# be able to grow a session file without limit.
_CURVE_LABEL_MAX_LEN = 200
_CURVE_NOTES_MAX_LEN = 5000
_CURVE_PANELS_MAX = 16
_CURVE_PANEL_ID_MAX_LEN = 50
_RUN_LABEL_MAX_LEN = 200
_SESSION_TITLE_MAX_LEN = 200
_SESSION_NOTES_MAX_LEN = 5000
_SESSION_FIELD_VALUE_MAX_LEN = 500
_SESSION_MAX_LINKED_IDS = 100
# Longer than any id the curve and run libraries create.
_SESSION_LINKED_ID_MAX_LEN = 200

# Ceiling on how many ids one POST /api/{curves,runs}/delete-batch request
# may name. The workbench only ever offers "select all" over one already-
# rendered kind/date's list, which never approaches this - the cap exists
# to stop an oversized body from making the server loop through an
# unbounded list of filesystem operations in a single request.
_MAX_BATCH_DELETE_IDS = 500

# Labels for curves that exist only in the page (demo mode's fixtures),
# saved as a simulated run's curve_ref. No dots, so never "." or "..", and
# bounded, unlike a library id.
_DEMO_LABEL_RE = re.compile(r"^demo-[A-Za-z0-9_-]{1,64}$")

# The player animates the whole series in a browser on a Pi-served page.
# Unbounded, a long run (a multi-minute capture can be hundreds of
# thousands of samples) is a multi-megabyte response and tens of thousands
# of chart points redrawn per animation frame - that does not degrade
# gracefully, it freezes the tab. This is only the default; a caller that
# passes max_samples=0 still gets the full series, for export/analysis.
_DEFAULT_MAX_SAMPLES = 2000
