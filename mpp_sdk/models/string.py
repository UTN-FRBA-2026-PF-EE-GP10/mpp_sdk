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
    instances before constructing the string, so partial shading is just
    "give one panel a lower irradiance".

    For speed, each panel's inverse I-V curve ``V(I)`` is sampled onto a
    table at construction time. The panels' conditions are therefore
    snapshotted — rebuild the string if irradiance / temperature change.

    Parameters
    ----------
    panels :
        The series-connected panel models (≥ 1).
    bypass_drop :
        Forward voltage of each bypass diode [V] (default 0.7).
    samples :
        Points per panel inverse-curve table.
    """

    def __init__(
        self,
        panels: list[PanelModel],
        bypass_drop: float = 0.7,
        samples: int = 600,
    ) -> None:
        if not panels:
            raise ValueError("PvString needs at least one panel")
        self._panels = list(panels)
        self._vd = bypass_drop
        # Per-panel inverse tables: current (ascending) → voltage.
        self._tables: list[tuple[np.ndarray, np.ndarray]] = []
        for p in self._panels:
            v, i = p.iv_curve(n=samples)
            v = np.asarray(v, dtype=float)
            i = np.asarray(i, dtype=float)
            # I-V is decreasing in V → I is decreasing along the V grid.
            # Reverse so current is ascending for np.interp.
            order = np.argsort(i)
            self._tables.append((i[order], v[order]))
        self._isc = float(max(p.short_circuit_current for p in self._panels))
        self._voc = float(sum(p.open_circuit_voltage for p in self._panels))

    @property
    def panels(self) -> list[PanelModel]:
        return self._panels

    def _panel_voltage(self, idx: int, string_current: float) -> float:
        i_tab, v_tab = self._tables[idx]
        if string_current >= i_tab[-1]:
            # Panel can't source this much current → bypass diode conducts.
            return -self._vd
        return float(np.interp(string_current, i_tab, v_tab))

    def _string_voltage(self, string_current: float) -> float:
        return sum(self._panel_voltage(k, string_current) for k in range(len(self._panels)))

    def _string_current(self, voltage: float) -> float:
        """Invert: find the string current giving the requested string voltage."""
        # String voltage is monotonically decreasing in current.
        lo, hi = 0.0, self._isc
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
        return self._voc

    @property
    def short_circuit_current(self) -> float:
        return self._isc
