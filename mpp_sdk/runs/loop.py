"""The closed-loop MPPT run loop: drives a `SignalSource` with an algorithm,
records `RunSample`s and aborts safely. Shared by the run CLI
(`scripts/run_algorithm.py`) and the curve-tracer web server.

Stdlib only, so it imports without any optional extra.
"""

from __future__ import annotations

import contextlib
import inspect
import logging
import math
import time
from collections.abc import Callable

from .record import RunSample

# Consecutive bad SPI frames before a run treats the link as down (see
# SpiMcuSource.consecutive_bad_frames). Conceptually the same idea as
# curve_tracer_server.py's own _BAD_FRAMES_LINK_DOWN (8, at that loop's
# ~50 ms poll period - about 400 ms to notice a pulled cable), but this
# loop has no sleep between exchanges by default (period_s=0) and each
# exchange is on the order of 1-2 ms, so the count is scaled up to reach
# a similar wall-clock detection time rather than tripping on one burst
# of ordinary line noise.
_BAD_FRAMES_LINK_DOWN = 300

# Consecutive readings over v_max / i_max / v_out_max before a run aborts.
# A single garbage sample (seen on the bench: normal readings, then one
# absurd V, I or V out) would otherwise end the run at once. A real
# overvoltage or overcurrent lasts far longer than this many exchanges.
_LIMIT_DEBOUNCE_SAMPLES = 5
# Also require the streak to span this long: a failed SPI frame replays the
# last good reading, so one garbage frame can repeat for several exchanges.
_LIMIT_DEBOUNCE_S = 0.05

# Board limits a run is held to unless the operator narrows them. The web
# server imports these, so the CLI and the UI enforce the same values.
#
# Current: the INA229 is scaled to a 1000 mA full scale (`I_MAX_MA` in
# firmware/pipico_board/src/ina229.rs). Its CURRENT register is 20-bit
# signed, so the largest real reading is 999 mA. A 1.0 A limit could never
# trip on a real reading, so the limit sits below the sensor maximum.
#
# Output voltage: the on-chip ADC's `Low` divider range reads up to about
# 27 V; above that the reading saturates and a higher limit never trips.
BOARD_V_MAX = 40.0
BOARD_I_MAX = 0.9
BOARD_V_OUT_MAX = 25.0

# Longest allowed control period, and the longest single sleep inside it.
MAX_CONTROL_PERIOD_MS = 1000.0
_WAIT_SLICE_S = 0.05

_log = logging.getLogger(__name__)


def _check_positive_finite(name: str, value: float) -> None:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, not a bool; got {value!r}")
    # NaN compares False against everything, so a NaN limit would switch
    # its abort off without a sign. Refuse it before any duty is written.
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a finite number above 0; got {value!r}")


def run_control_loop(
    source,
    algorithm,
    *,
    duration_s: float,
    v_max: float,
    i_max: float,
    v_out_max: float | None = None,
    initial_duty: float = 0.5,
    clock=time.monotonic,
    sleep=time.sleep,
    period_s: float = 0.0,
    should_stop: Callable[[], bool] | None = None,
    max_consecutive_bad_frames: int = _BAD_FRAMES_LINK_DOWN,
    on_sample: Callable[[RunSample], None] | None = None,
    samples: list[RunSample] | None = None,
    control_period_ms: float | None = None,
    run_info: dict | None = None,
) -> tuple[list[RunSample], bool, str | None]:
    """Run `algorithm` against `source` for `duration_s` seconds,
    recording one `RunSample` per control step. Returns
    `(samples, aborted, reason)`.

    `samples`, if given, is the list appended to and returned - the
    caller's own reference, not a copy. Pass one in when the samples
    collected before an exception propagates still matter (e.g. a web
    server wants to save a partial run rather than lose it): the caller
    keeps a live view of what was recorded even though this function
    never gets to return normally. Defaults to a fresh list.

    `aborted` is True, and `reason` names why, if any of these fire
    (source is driven to 0 duty before returning either way):

    - `"overvoltage"` / `"overcurrent"`: a reading exceeded `v_max`/`i_max`.
      A limit aborts only when `_LIMIT_DEBOUNCE_SAMPLES` readings in a row
      break it and the streak spans `_LIMIT_DEBOUNCE_S`. A shorter streak is
      dropped: the loop holds the duty, reads again, and the reading never
      reaches the algorithm or `samples`. This applies to the output limit
      below too.
    - `"output-overvoltage"`: the converter output (`source.vout`, absent on
      a simulated source, which never trips this) exceeded `v_out_max`. The
      panel limits cannot see this: with a light or missing load the SEPIC
      output climbs far past the input while the panel side looks normal.
    - `"link-down"`: `source.consecutive_bad_frames` (absent on a fake or
      simulated source, which reads as 0 and never trips this) reached
      `max_consecutive_bad_frames` - SPI has no presence detection, so a
      disconnected board otherwise looks like valid-but-stale telemetry.
    - `"stopped"`: `should_stop()` returned True - an explicit request to
      end the run early (e.g. a UI Stop button), checked once per step.
    - `"invalid-reading"`: V or I is not a finite number, held for the same
      debounce as the limits.
    - `"invalid-duty"`: the algorithm returned a duty that is not a finite
      number. It is never written.

    A limit or `initial_duty` that is not finite, or not in range, raises
    `ValueError` before any duty is written.

    `reason` is `None` on an ordinary `duration_s` timeout - that is not
    an abort.

    Every exit path - normal completion, an abort above, or an exception
    raised by `source`/`algorithm` - drives duty to zero before returning
    or propagating. This is the function's one safety-critical guarantee;
    do not reimplement this loop elsewhere; extend it here instead so the
    CLI and any other caller keep exactly one abort path.

    `control_period_ms`, if given, keeps the algorithm steps at least this
    far apart: the loop sleeps off the rest of the period after each step.
    `None` (default) runs one step per source exchange, as before. The
    sensor gives a new V/I pair only every few ms, so steps faster than
    that act on repeated readings.

    `run_info`, if given, is filled at the end (also on an exception) with
    `step_period_mean_ms`, `step_period_max_ms` (None below two steps) and
    `bad_frames` (frames the source rejected during this run, None if the
    source does not count them).

    `period_s > 0` adds a `sleep()` pad between steps; 0 (default) runs as
    fast as `source.read()/write()` allow. `on_sample`, if given, is
    called with each `RunSample` as it's recorded - for a caller (e.g. a
    web server) that wants to observe the run live without waiting for it
    to finish.
    """
    _check_positive_finite("v_max", v_max)
    _check_positive_finite("i_max", i_max)
    if v_out_max is not None:
        _check_positive_finite("v_out_max", v_out_max)
    if not (math.isfinite(initial_duty) and 0.0 <= initial_duty < 1.0):
        raise ValueError(f"initial_duty must be a finite number in [0, 1); got {initial_duty!r}")
    if control_period_ms is not None:
        _check_positive_finite("control_period_ms", control_period_ms)
        if control_period_ms > MAX_CONTROL_PERIOD_MS:
            raise ValueError(
                f"control_period_ms must be at most {MAX_CONTROL_PERIOD_MS}; "
                f"got {control_period_ms!r}"
            )
    samples = [] if samples is None else samples
    suspect_total = 0

    def wait_until(step_t: float) -> None:
        # Short slices: the converter holds its last duty while we wait, so
        # a stop request or the run end must not wait out a whole period.
        if control_period_ms is None:
            return
        while True:
            remaining = step_t + control_period_ms / 1000.0 - (clock() - start)
            if remaining <= 0 or clock() - start >= duration_s:
                return
            if should_stop is not None and should_stop():
                return
            sleep(min(remaining, _WAIT_SLICE_S))

    bad_frames_start = getattr(source, "bad_frames", None)
    settle_start = getattr(source, "settle_failures", None)
    step_starts: list[float] = []
    start = clock()
    aborted = False
    reason: str | None = None
    try:
        # Seed write moved inside the try: a raising seed write used to
        # skip the `finally` below entirely, breaking the zero-duty
        # guarantee this docstring promises for every exit path.
        source.write(initial_duty)  # SpiMcuSource.read() raises before the first write()
        duty = initial_duty
        over_limit = 0
        streak: list[tuple[float, float, float, float | None, float, str]] = []
        while clock() - start < duration_s:
            voltage, current = source.read()
            t = clock() - start
            v_out = getattr(source, "vout", None)
            suspect: str | None = None
            if not (math.isfinite(voltage) and math.isfinite(current)):
                suspect = "invalid-reading"
            elif voltage > v_max:
                suspect = "overvoltage"
            elif current > i_max:
                suspect = "overcurrent"
            elif v_out_max is not None and v_out is not None and v_out > v_out_max:
                suspect = "output-overvoltage"
            over_limit = over_limit + 1 if suspect else 0
            if suspect:
                suspect_total += 1
                streak.append((round(t, 4), voltage, current, v_out, duty, suspect))
            elif streak:
                _log.warning("ignored %d suspect reading(s): %s", len(streak), streak)
                streak = []
            if (
                suspect
                and over_limit >= _LIMIT_DEBOUNCE_SAMPLES
                and t - streak[0][0] >= _LIMIT_DEBOUNCE_S
            ):
                aborted = True
                reason = suspect
                _log.warning("run aborted (%s), t,V,I,Vout,duty,kind: %s", reason, streak)
                break
            if getattr(source, "consecutive_bad_frames", 0) >= max_consecutive_bad_frames:
                aborted = True
                reason = "link-down"
                break
            if should_stop is not None and should_stop():
                aborted = True
                reason = "stopped"
                break
            if suspect:
                # Hold the duty and fetch a fresh reading; the suspect one
                # never reaches the algorithm or the saved samples.
                source.write(duty)
                if period_s > 0:
                    sleep(period_s)
                continue
            next_duty = algorithm.step(voltage, current)
            if not math.isfinite(next_duty):
                aborted = True
                reason = "invalid-duty"
                break
            duty = next_duty
            source.write(duty)
            sample = RunSample(t=t, voltage=voltage, current=current, duty=duty)
            samples.append(sample)
            if on_sample is not None:
                on_sample(sample)
            step_starts.append(t)
            if period_s > 0:
                sleep(period_s)
            wait_until(t)
    finally:
        # Zeroing duty is the priority on the way out; a broken write here
        # must not mask whatever exception is already propagating (or
        # silently replace a clean return with a spurious one).
        with contextlib.suppress(Exception):
            source.write(0.0)
        if run_info is not None:
            gaps = [(b - a) * 1000.0 for a, b in zip(step_starts, step_starts[1:], strict=False)]
            run_info["suspect_readings"] = suspect_total
            run_info["settle_failures"] = (
                settle_end - settle_start
                if settle_start is not None
                and (settle_end := getattr(source, "settle_failures", None)) is not None
                else None
            )
            run_info["step_period_mean_ms"] = sum(gaps) / len(gaps) if gaps else None
            run_info["step_period_max_ms"] = max(gaps) if gaps else None
            bad_frames_end = getattr(source, "bad_frames", None)
            run_info["bad_frames"] = (
                bad_frames_end - bad_frames_start
                if bad_frames_start is not None and bad_frames_end is not None
                else None
            )
    return samples, aborted, reason


def _algorithm_params(algorithm) -> dict:
    """Constructor parameters of `algorithm` that it still holds as a plain
    number, read by name (`step_size` or `_step_size`). Algorithms keep no
    public parameter list, so a parameter held under another name is left
    out rather than guessed."""
    params: dict = {}
    try:
        names = inspect.signature(type(algorithm).__init__).parameters
    except TypeError, ValueError:
        return params
    for name in names:
        if name in ("self", "initial_duty"):
            continue
        for attr in (name, f"_{name}"):
            value = getattr(algorithm, attr, None)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                params[name] = value
                break
    return params


def build_run_settings(
    source,
    algorithm,
    *,
    control_period_ms: float | None,
    session_fields: dict[str, str] | None = None,
) -> dict:
    """The `RunRecord.settings` block. Anything the source or the session
    does not know is None. The firmware has no version readout, so its
    commit and the load come only from the session checklist fields."""
    fields = session_fields or {}
    ranges = (getattr(source, "vin_range", None), getattr(source, "vout_range", None))
    return {
        "algorithm_params": _algorithm_params(algorithm),
        "averaging": getattr(source, "averaging", None),
        "adc_divider_range": (
            {"vin": ranges[0], "vout": ranges[1]} if None not in ranges else None
        ),
        "load": fields.get("load_resistor") or None,
        "firmware_commit": fields.get("firmware_commit") or None,
        "control_period_ms": control_period_ms,
    }
