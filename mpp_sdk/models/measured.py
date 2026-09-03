"""Measured panel model — a captured I-V sweep as a `PanelModel`.

This is what lets a real curve run through the same comparison harness as
every synthetic model, with zero algorithm changes: `MeasuredPanel`
implements exactly the three methods `PanelModel` requires, same as
`TabulatedPanel` and `IdealSingleDiode`.
"""

from collections import defaultdict
from collections.abc import Sequence

import numpy as np

from ..curves.record import CurveRecord, now_utc
from .base import PanelModel


class MeasuredPanel(PanelModel):
    """A captured I-V sweep (`CurveRecord`), presented as a `PanelModel`.

    A real sweep is measured from Voc down to Isc (descending voltage,
    unevenly spaced, sometimes repeating a voltage near the knee) - the
    opposite of `TabulatedPanel`'s ascending, evenly-spaced grid. This class
    sorts ascending by voltage and averages duplicate voltages before
    interpolating, so `current()` behaves like any other `PanelModel`.

    The two endpoints need care because the sweep doesn't reach them
    exactly:

    - **Isc** (`V = 0`): the largest measured current (not necessarily at
      the smallest measured voltage - a noisy sweep need not peak there) is
      held flat down to `V = 0` - physically sound, since the I-V curve is
      nearly horizontal in the constant-current region.
    - **Voc** (`I = 0`): the sweep's first point sits at near-zero but
      nonzero current, so using it as-is would place Voc slightly low. With
      `extrapolate=True` (the default), the last two measured points are
      extrapolated linearly to `I = 0` and that voltage is used as Voc; with
      `extrapolate=False`, the measured maximum voltage is used as-is. If
      the extrapolation would not exceed the last measured voltage (e.g. the
      curve isn't decreasing there), it falls back to the measured maximum
      rather than produce a non-monotonic curve.

    `MeasuredPanel` is immutable and carries no irradiance/temperature
    knobs - unlike `PvlibPanelModel`, its conditions are baked into the
    measurement. A request to vary conditions on an instance is really a
    request for a *series* of measured curves, not a mutable one.

    The source `CurveRecord` is kept on `.record` so callers can title
    plots from its `label`/`measurement` without a parallel lookup.

    For speed in a long-running simulation, wrap an instance in
    `TabulatedPanel` - that costs nothing extra and is not done
    automatically here.
    """

    def __init__(self, record: CurveRecord, *, extrapolate: bool = True) -> None:
        if len(record.points) < 2:
            raise ValueError(f"need at least 2 points to build a curve; got {len(record.points)}")

        self.record = record
        self.extrapolate = extrapolate

        by_voltage: dict[float, list[float]] = defaultdict(list)
        for v, i in record.points:
            by_voltage[v].append(i)
        v_sorted = sorted(by_voltage)
        i_avg = [float(np.mean(by_voltage[v])) for v in v_sorted]

        if len(v_sorted) < 2:
            raise ValueError(
                f"need at least 2 distinct voltages to build a curve; got {len(v_sorted)}"
            )

        isc = max(i_avg)  # true largest measured current - a noisy sweep need
        # not peak at the smallest measured voltage, and `current()` holds
        # this value flat down to V=0, so it must match `short_circuit_current`.
        voc = v_sorted[-1]
        if extrapolate:
            # Guard against an unstable slope estimate: two points that sit
            # much closer together than the sweep's average spacing (ADC
            # noise repeating a voltage near the knee) can yield a near-flat
            # slope and an extrapolated Voc far beyond the measured range.
            avg_spacing = (v_sorted[-1] - v_sorted[0]) / (len(v_sorted) - 1)
            gap = v_sorted[-1] - v_sorted[-2]
            if gap >= 0.1 * avg_spacing:
                slope = (i_avg[-1] - i_avg[-2]) / gap
                if slope < 0.0:
                    extrapolated_voc = v_sorted[-2] - i_avg[-2] / slope
                    if extrapolated_voc > voc:
                        voc = extrapolated_voc
                        v_sorted.append(voc)
                        i_avg.append(0.0)

        self._v = np.asarray(v_sorted, dtype=float)
        self._i = np.asarray(i_avg, dtype=float)
        self._voc = float(voc)
        self._isc = float(isc)

    @classmethod
    def from_points(
        cls,
        points: Sequence[tuple[float, float]],
        *,
        label: str = "",
        extrapolate: bool = True,
    ) -> MeasuredPanel:
        """Build a `MeasuredPanel` straight from `(v, i)` pairs, without a
        saved `CurveRecord` - convenient for one-off scripts and tests."""
        record = CurveRecord(
            captured_at=now_utc(),
            label=label,
            measurement="other",
            panels=(),
            points=tuple(points),
        )
        return cls(record, extrapolate=extrapolate)

    def current(self, voltage):
        # If a sweep ever captures points past Isc into reverse, the
        # "hold flat to V=0" assumption below breaks - revisit `left=`.
        v = np.asarray(voltage, dtype=float)
        # np.interp needs increasing x; self._v already is.
        i = np.interp(v, self._v, self._i, left=self._isc, right=0.0)
        return float(i) if v.ndim == 0 else i

    @property
    def open_circuit_voltage(self) -> float:
        return self._voc

    @property
    def short_circuit_current(self) -> float:
        return self._isc
