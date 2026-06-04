"""Series string of panels with bypass diodes (partial-shading support)."""

import numpy as np

from .base import PanelModel


class PvString(PanelModel):
    """N panels in series, each with an anti-parallel bypass diode.

    All panels share a common string current ``I``. Each panel contributes
    its own voltage ``V_k(I)``; when the string current exceeds a (shaded)
    panel's short-circuit current, that panel's bypass diode conducts and
    clamps its voltage to ``−V_diode``. Summing the clamped per-panel
    voltages yields the characteristic **multi-modal** P-V curve that traps
    plain P&O on a local maximum — the motivation for Global MPPT.

    Per-panel irradiance is set on the individual ``PvlibPanelModel``
    instances (``panel.irradiance = ...``) before sampling, so partial
    shading is just "give one panel a lower irradiance".

    Parameters
    ----------
    panels :
        The series-connected panel models (≥ 1).
    bypass_drop :
        Forward voltage of each bypass diode [V] (default 0.7).
    """

    def __init__(self, panels: list[PanelModel], bypass_drop: float = 0.7) -> None:
        if not panels:
            raise ValueError("PvString needs at least one panel")
        self._panels = list(panels)
        self._vd = bypass_drop

    @property
    def panels(self) -> list[PanelModel]:
        return self._panels

    def _panel_voltage(self, panel: PanelModel, string_current: float) -> float:
        """Voltage of one panel carrying ``string_current`` (with bypass)."""
        isc = panel.short_circuit_current
        if string_current >= isc:
            # Panel can't source this much current → bypass diode conducts.
            return -self._vd
        # Invert the panel I-V: find V where panel.current(V) == string_current.
        lo, hi = 0.0, panel.open_circuit_voltage
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if float(panel.current(mid)) > string_current:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _string_voltage(self, string_current: float) -> float:
        return sum(self._panel_voltage(p, string_current) for p in self._panels)

    def _string_current(self, voltage: float) -> float:
        """Invert: find the string current giving the requested string voltage."""
        # String voltage is monotonically decreasing in current.
        lo, hi = 0.0, self.short_circuit_current
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if self._string_voltage(mid) > voltage:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def current(self, voltage):
        v = np.asarray(voltage, dtype=float)
        if v.ndim == 0:
            return float(self._string_current(float(v)))
        return np.array([self._string_current(float(x)) for x in v])

    @property
    def open_circuit_voltage(self) -> float:
        # At I = 0 no bypass conducts; string Voc is the sum of panel Vocs.
        return float(sum(p.open_circuit_voltage for p in self._panels))

    @property
    def short_circuit_current(self) -> float:
        # The strongest panel sets the max current; weaker panels bypass.
        return float(max(p.short_circuit_current for p in self._panels))
