"""State of the one live closed-loop run, and the helpers that shape run
samples for the API."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

from harness.common import AlgorithmSpec
from mpp_sdk.runs.record import RunSample
from scripts.curve_tracer.limits import _DEFAULT_INITIAL_DUTY, _DEFAULT_V_OUT_MAX


@dataclass(frozen=True)
class _RunRequest:
    """One accepted `POST /api/runs/start` request, handed from a
    request-handling thread to the poll thread via `run_requests` - see
    `_LiveRunCache.try_start` for why the acceptance check itself can run
    on the request thread while the run itself cannot."""

    spec: AlgorithmSpec
    duration_s: float
    v_max: float
    i_max: float
    curve_ref: str | None
    label: str
    v_out_max: float = _DEFAULT_V_OUT_MAX
    # Defaulted so a caller that does not care about the seed does not
    # have to state one; the route always passes it explicitly.
    initial_duty: float = _DEFAULT_INITIAL_DUTY
    # (volts, amps) sent in the request body for a simulated run - demo
    # mode's bundled curves are not in the server's library, so they come
    # inline instead of by `curve_ref`.
    curve_points: tuple[tuple[float, float], ...] | None = None
    # The client's "active session" at the moment the run was started -
    # see _SaveCurveRequest.session_id's own doc comment. Stamped onto the
    # saved RunRecord in save_and_finish below.
    session_id: str | None = None
    control_period_ms: float | None = None


class _LiveRunCache:
    """Live state of the one closed-loop run that can be in progress at a
    time - shared between the poll thread (which executes the run via
    `_run_live` and appends one sample per control step through
    `add_sample`) and request-handling threads (which start/stop it and
    poll `snapshot`). Samples accumulate here in full; `snapshot`
    downsamples on read (`_downsample_samples`, same helper the saved-run
    endpoint uses) so a run's per-step rate never has to be throttled to
    match how often a page can usefully redraw - the full series still
    reaches the saved `RunRecord` untouched.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = "idle"  # idle | running | done
        self._algorithm: str | None = None
        self._label = ""
        self._curve_ref: str | None = None
        self._samples: list[RunSample] = []
        self._vout: float | None = None
        self._aborted = False
        self._abort_reason: str | None = None
        self._saved_run_id: str | None = None
        self._simulated = False
        self._reference_points: tuple[tuple[float, float], ...] = ()

    def stop_if_running(self, stop_event: threading.Event) -> bool:
        """Atomically check-and-set: `stop_event.set()` happens under the
        same lock as the running check, so a run that finishes and a new
        one that claims the slot (`try_start`) in the gap between the two
        can never make a stop land on the wrong run. Returns whether a run
        was found running."""
        with self._lock:
            if self._status != "running":
                return False
            stop_event.set()
            return True

    def try_start(
        self,
        *,
        algorithm: str,
        label: str,
        curve_ref: str | None,
        simulated: bool = False,
        reference_points: tuple[tuple[float, float], ...] = (),
    ) -> bool:
        """Claim the single run slot, resetting all live state - returns
        False, leaving everything untouched, if a run is already in
        progress. This only ever touches this cache, never a source
        (that happens later, in `_run_live`/`_run_simulated`), so it is
        safe to call directly from a request-handling thread - it is what
        lets `POST /api/runs/start` reject a second concurrent request
        immediately rather than racing two runs onto the queue, and is
        also what keeps a simulated and a hardware run from ever
        overlapping even though they execute on different threads (see
        the module docstring).
        """
        with self._lock:
            if self._status == "running":
                return False
            self._status = "running"
            self._algorithm = algorithm
            self._label = label
            self._curve_ref = curve_ref
            self._samples = []
            self._vout = None
            self._aborted = False
            self._abort_reason = None
            self._saved_run_id = None
            self._simulated = simulated
            self._reference_points = reference_points
            return True

    def add_sample(self, sample: RunSample, vout: float | None) -> None:
        with self._lock:
            self._samples.append(sample)
            self._vout = vout

    def finish(self, *, aborted: bool, reason: str | None, saved_run_id: str | None) -> None:
        with self._lock:
            self._status = "done"
            self._aborted = aborted
            self._abort_reason = reason
            self._saved_run_id = saved_run_id

    def snapshot(self, max_samples: int) -> dict:
        with self._lock:
            status = self._status
            algorithm = self._algorithm
            label = self._label
            curve_ref = self._curve_ref
            samples = list(self._samples)
            vout = self._vout
            aborted = self._aborted
            abort_reason = self._abort_reason
            saved_run_id = self._saved_run_id
            simulated = self._simulated
            reference_points = self._reference_points

        # Downsampling (and the resulting stride math) doesn't need the
        # lock - it only reads the local copy taken above.
        picked, downsampled = _downsample_samples(tuple(samples), max_samples)
        last = samples[-1] if samples else None
        return {
            "status": status,
            "algorithm": algorithm,
            "label": label,
            "curve_ref": curve_ref,
            "n_samples": len(samples),
            "downsampled": downsampled,
            "samples": [s.to_dict() for s in picked],
            "voltage": last.voltage if last else None,
            "current": last.current if last else None,
            "duty": last.duty if last else None,
            "vout": vout,
            "aborted": aborted,
            "abort_reason": abort_reason,
            "saved_run_id": saved_run_id,
            # Which kind of run is in flight (or just finished) - see
            # RUN_SOURCES in mpp_sdk/runs/record.py. Never "unknown" here:
            # a live run always knows which source it started against.
            "source": "simulated" if simulated else "hardware",
            # The static curve the run tracks, for the grey reference line.
            # Sent by the server rather than looked up by the page, so demo
            # mode's inline curves and the built-in panel draw too.
            "reference_points": [{"v": v, "i": i} for v, i in reference_points],
        }


def _downsample_samples(
    samples: tuple[RunSample, ...], max_samples: int
) -> tuple[list[RunSample], bool]:
    """Stride `samples` down to roughly `max_samples` points for
    GET /api/runs/{id} - see `_DEFAULT_MAX_SAMPLES` for why. `max_samples
    <= 0` means "no cap, return everything".

    Striding is deliberately the simple choice for now: picking every
    Nth sample can hide a brief excursion that falls between the kept
    points, and an MPPT trace's short overshoot is exactly the
    interesting kind of excursion to lose. A future version may want
    min/max-per-bucket downsampling instead.

    The first and last sample are always kept even though they may not
    fall on the stride - a trajectory that silently loses its own
    endpoints is misleading."""
    n = len(samples)
    if max_samples <= 0 or n <= max_samples:
        return list(samples), False
    stride = math.ceil(n / max(max_samples, 2))
    picked = list(samples[::stride])
    if picked[-1] is not samples[-1]:
        picked.append(samples[-1])
    return picked, True


def _run_duration_s(samples: tuple[RunSample, ...]) -> float:
    """Span between the first and last sample, 0.0 for a run with fewer
    than two. Shared by the list and detail routes so their numbers cannot
    drift, and always taken from the full on-disk trace, never a
    downsampled one."""
    return samples[-1].t - samples[0].t if len(samples) >= 2 else 0.0
