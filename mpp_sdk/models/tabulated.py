"""Tabulated panel model — caches any PanelModel's I-V curve for fast reuse."""

import numpy as np

from .base import PanelModel


class TabulatedPanel(PanelModel):
    """Frozen I-V lookup table sampled from another panel model.

    Expensive models (``PvString`` with a pvlib-backed solver, measured
    curves) are slow to evaluate point-by-point. This wraps one by sampling
    its I-V curve once onto a dense grid and interpolating thereafter, which
    is what makes the dynamic simulation tractable.

    The snapshot is taken at construction time, so the source model's
    irradiance / temperature at that moment are baked in. Re-create the
    table when conditions change.
    """

    def __init__(self, panel: PanelModel, n: int = 800) -> None:
        v, i = panel.iv_curve(n=n)
        self._v = np.asarray(v, dtype=float)
        self._i = np.asarray(i, dtype=float)
        self._voc = float(self._v[-1])
        self._isc = float(self._i[0])

    def current(self, voltage):
        v = np.asarray(voltage, dtype=float)
        # np.interp needs increasing x; our voltage grid already is.
        i = np.interp(v, self._v, self._i, left=self._isc, right=0.0)
        return float(i) if v.ndim == 0 else i

    @property
    def open_circuit_voltage(self) -> float:
        return self._voc

    @property
    def short_circuit_current(self) -> float:
        return self._isc
