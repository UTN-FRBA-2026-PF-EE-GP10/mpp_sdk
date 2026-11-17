"""Execute one live run on a real or simulated source and save the result."""

from __future__ import annotations

import contextlib
import threading

import numpy as np

from mpp_sdk import IdealSingleDiode, MeasuredPanel, SEPICConverter, SimulatedSource, TabulatedPanel
from mpp_sdk.curves import CurveRecord
from mpp_sdk.curves import library as curve_library
from mpp_sdk.curves.record import now_utc
from mpp_sdk.runs import RunRecord
from mpp_sdk.runs import library as run_library

# run_control_loop is the one control loop and abort path shared by the
# CLI (scripts/run_algorithm.py) and this server - a live run started from
# the web UI must not reimplement it. _BAD_FRAMES_LINK_DOWN is aliased
# because that module's own constant is tuned for this server's ~50 ms
# poll period, not a live run's much tighter control loop - see
# _RUN_BAD_FRAMES_LINK_DOWN below.
from mpp_sdk.runs.loop import _BAD_FRAMES_LINK_DOWN as _RUN_BAD_FRAMES_LINK_DOWN
from mpp_sdk.runs.loop import build_run_settings, run_control_loop
from mpp_sdk.runs.record import RunSample
from mpp_sdk.runs.record import now_utc as runs_now_utc
from mpp_sdk.sessions import library as session_library
from scripts.curve_tracer.cache import _SweepCache
from scripts.curve_tracer.library_paths import _curve_path, _session_path
from scripts.curve_tracer.limits import (
    _BUILTIN_REFERENCE_POINTS,
    _SIMULATED_LOAD_RESISTANCE,
    _SIMULATED_RUN_PERIOD_S,
)
from scripts.curve_tracer.live_run import _LiveRunCache, _RunRequest


def _execute_run(
    src,
    run_cache: _LiveRunCache,
    request: _RunRequest,
    stop_event: threading.Event,
    *,
    source: str,
    period_s: float = 0.0,
    max_consecutive_bad_frames: int = _RUN_BAD_FRAMES_LINK_DOWN,
) -> None:
    """Run `request` against `src` to completion and save the result -
    shared by `_run_live` (hardware, on the poll thread) and
    `_run_simulated` (its own thread). `source` is stamped onto the saved
    `RunRecord` (see `RUN_SOURCES` in `mpp_sdk/runs/record.py`) - the
    caller decides it, never the request body, so a run can't misreport
    what actually drove it.

    Reuses `run_control_loop` (`mpp_sdk/runs/loop.py`) unchanged - one
    control loop and one abort path for the CLI and every caller here.
    """
    algorithm = request.spec.make(request.initial_duty)
    # Passed into run_control_loop as its own `samples` list (rather than
    # letting it build one internally) so this survives an exception
    # raised mid-run: `samples` below still holds it, even though the
    # call that raised never gets to return it normally.
    collected: list[RunSample] = []

    def on_sample(sample: RunSample) -> None:
        # Runs synchronously on the calling thread, right after the
        # write() that produced this telemetry - reading src.vout here
        # needs no extra synchronization. Absent on SimulatedSource, so
        # getattr's default keeps a simulated run's `vout` as None rather
        # than raising.
        run_cache.add_sample(sample, vout=getattr(src, "vout", None))

    run_info: dict = {}
    session_fields: dict[str, str] = {}
    if request.session_id is not None:
        # A session that cannot be read must not block the run.
        with contextlib.suppress(Exception):
            session_fields = session_library.load(_session_path(request.session_id)).fields

    def save_and_finish(samples: tuple[RunSample, ...], aborted: bool, reason: str | None) -> None:
        record = RunRecord(
            captured_at=runs_now_utc(),
            label=request.label,
            algorithm=request.spec.label,
            samples=samples,
            curve_ref=request.curve_ref,
            aborted=aborted,
            notes=reason or "",
            source=source,
            session_id=request.session_id,
            settings=build_run_settings(
                src,
                algorithm,
                control_period_ms=request.control_period_ms,
                session_fields=session_fields,
            ),
            step_period_mean_ms=run_info.get("step_period_mean_ms"),
            step_period_max_ms=run_info.get("step_period_max_ms"),
            bad_frames=run_info.get("bad_frames"),
            settle_failures=run_info.get("settle_failures"),
            suspect_readings=run_info.get("suspect_readings"),
        )
        try:
            path = run_library.save(record)
        except (OSError, ValueError) as exc:
            # ValueError: a non-finite value the JSON writer refuses.
            run_cache.finish(
                aborted=aborted,
                reason=f"{reason or 'completed'}; failed to save: {exc}",
                saved_run_id=None,
            )
            return
        run_cache.finish(aborted=aborted, reason=reason, saved_run_id=path.stem)

    try:
        samples, aborted, reason = run_control_loop(
            src,
            algorithm,
            duration_s=request.duration_s,
            initial_duty=request.initial_duty,
            v_max=request.v_max,
            i_max=request.i_max,
            v_out_max=request.v_out_max,
            should_stop=stop_event.is_set,
            max_consecutive_bad_frames=max_consecutive_bad_frames,
            on_sample=on_sample,
            period_s=period_s,
            samples=collected,
            control_period_ms=request.control_period_ms,
            run_info=run_info,
        )
    except Exception as exc:
        # run_control_loop's own `finally` has already driven duty to zero
        # even here (see its docstring) - this only keeps an unexpected
        # failure (a broken algorithm.step(), a hard SPI fault) from
        # killing the thread that owns the source, which for a hardware
        # run would silently end every future sweep and run for the
        # process's life. `collected` still holds whatever was recorded
        # before the failure - worth saving rather than discarding a run
        # that may have run for most of its duration before crashing.
        reason = f"error: {exc}"
        if collected:
            save_and_finish(tuple(collected), True, reason)
        else:
            run_cache.finish(aborted=True, reason=reason, saved_run_id=None)
        return

    save_and_finish(tuple(samples), aborted, reason)


def _run_live(
    src,
    cache: _SweepCache,
    run_cache: _LiveRunCache,
    request: _RunRequest,
    stop_event: threading.Event,
) -> None:
    """Execute one live closed-loop run to completion, on the poll thread -
    the only thread that may ever touch `src` (see the module docstring).
    This blocks `_poll_loop`'s normal sweep polling for the run's whole
    duration: a live run and curve-tracer polling are mutually exclusive
    on one SPI link, so that displacement is deliberate, not an accidental
    stall - `cache.set` below makes it visible to anyone still polling
    `/api/data` rather than leaving it looking silently frozen.
    """
    cache.set(None, "paused: a live MPPT run is in progress")
    # The curve-tracer relay may still be engaged from an earlier sweep
    # (never released automatically - see SpiMcuSource.release_relay) or
    # from But1 on the bench. Left engaged, the panel stays on the
    # tracer's bleed path and the firmware holds the SEPIC gate at 0 for
    # as long as the relay is on, so a run would drive nothing while
    # looking like it completed normally. Safe to call even when the
    # relay is already released. getattr guards a fake/simulated source,
    # which has no relay to release.
    release_relay = getattr(src, "release_relay", None)
    if release_relay is not None:
        try:
            release_relay()
        except Exception as exc:
            # The run never started driving, but its slot is claimed.
            # Without this the slot stays "running" and every later start
            # gets 409 until the server restarts.
            run_cache.finish(
                aborted=True, reason=f"error: relay release failed: {exc}", saved_run_id=None
            )
            return
    _execute_run(
        src,
        run_cache,
        request,
        stop_event,
        source="hardware",
        max_consecutive_bad_frames=_RUN_BAD_FRAMES_LINK_DOWN,
    )


def _builtin_panel() -> IdealSingleDiode:
    # IdealSingleDiode's own defaults (photocurrent=8.0, 60 cells) model
    # a much bigger module than this bench - Isc/Voc land well outside
    # _DEFAULT_I_MAX/_DEFAULT_V_MAX, so a no-curve run would trip the
    # overcurrent abort on its very first sample. These two params are
    # sized to roughly match a single Hissuma PSF10MONO (Isc=0.79A,
    # Voc=17V - see harness/panel_config.py) so the fallback stays a
    # sane default instead of an immediate, confusing abort.
    return IdealSingleDiode(photocurrent=0.79, cells_in_series=36)


def _builtin_reference_points() -> tuple[tuple[float, float], ...]:
    """The built-in panel's I-V curve, sampled from 0 V to just past Voc."""
    panel = _builtin_panel()
    voltages = np.linspace(0.0, 30.0, _BUILTIN_REFERENCE_POINTS)
    currents = np.asarray(panel.current(voltages), dtype=float)
    return tuple((float(v), float(i)) for v, i in zip(voltages, currents, strict=True) if i > 0)


def _make_simulated_source(
    curve_ref: str | None, curve_points: tuple[tuple[float, float], ...] | None = None
) -> SimulatedSource:
    """Build the panel a simulated run drives against: `MeasuredPanel` over
    the operator's chosen reference curve when one is given - the run then
    hunts the MPP of a curve actually measured on this bench, and the live
    view plots it against that same curve - or `IdealSingleDiode` when
    none is, so a simulated run always works, including against an empty
    curve library. Either way the panel is wrapped in `TabulatedPanel`:
    cheap for `IdealSingleDiode`'s already-closed-form `current()`, and
    `MeasuredPanel`'s own docstring recommends it for a long-running
    simulation.
    """
    if curve_points is not None:
        panel = MeasuredPanel(
            CurveRecord(
                captured_at=now_utc(),
                label="inline",
                measurement="other",
                panels=(),
                points=curve_points,
            )
        )
    elif curve_ref is not None:
        record = curve_library.load(_curve_path(curve_ref))
        panel = MeasuredPanel(record)
    else:
        panel = _builtin_panel()
    return SimulatedSource(
        panel=TabulatedPanel(panel),
        converter=SEPICConverter(),
        load_resistance=_SIMULATED_LOAD_RESISTANCE,
    )


def _run_simulated(
    run_cache: _LiveRunCache, request: _RunRequest, stop_event: threading.Event
) -> None:
    """Execute one live closed-loop run against a `SimulatedSource`, on its
    own dedicated thread. A simulated run never touches `SpiMcuSource`/
    spidev, so unlike `_run_live` it has no reason to wait for (or
    displace) the poll thread that owns the real board - `_LiveRunCache.
    try_start` already claimed the one run slot before this thread was
    even started, so this can never run alongside a hardware run.
    """
    try:
        src = _make_simulated_source(request.curve_ref, request.curve_points)
    except Exception as exc:
        run_cache.finish(aborted=True, reason=f"error: {exc}", saved_run_id=None)
        return
    _execute_run(
        src,
        run_cache,
        request,
        stop_event,
        source="simulated",
        period_s=_SIMULATED_RUN_PERIOD_S,
    )
