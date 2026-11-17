"""Single-diode panel model with series and shunt resistance."""

import math

import numpy as np

from .base import PanelModel

_BOLTZMANN = 1.380649e-23
_ELECTRON_CHARGE = 1.602176634e-19
_EXP_LIMIT = 700.0  # exp() overflows past about 709
_MAX_ITER = 200
_F_TOL = 1e-12  # [A] residual that stops the solver
_WIDTH_TOL = 1e-14  # relative bracket width that stops the solver


class SingleDiodeWithLosses(PanelModel):
    r"""Single-diode panel with series (R_s) and shunt (R_sh) resistance.

        I = I_ph - I_0 * (exp((V + I R_s) / (n N_s V_t)) - 1) - (V + I R_s) / R_sh

    ``I`` appears on both sides, so ``current(V)`` solves
    ``f(I) = I_ph - I_0 (exp(.) - 1) - (V + I R_s) / R_sh - I = 0``.
    ``f`` falls strictly as ``I`` rises, so the root is unique and a bracket
    ``[lo, hi]`` with ``f(lo) >= 0 >= f(hi)`` always exists. The solver is a
    Newton method safeguarded by bisection: a Newton step that leaves the
    bracket, or is not finite, is replaced by the bracket midpoint. The
    bracket shrinks at every iteration, so convergence is guaranteed.

    ``photocurrent`` is the value at 1000 W/m2 and scales linearly with the
    mutable ``irradiance`` [W/m2]. ``temperature`` is the cell temperature
    [degC] and sets the thermal voltage. With ``series_resistance=0`` and
    ``shunt_resistance=inf`` the model equals ``IdealSingleDiode``.
    """

    def __init__(
        self,
        photocurrent: float = 8.0,
        saturation_current: float = 1e-9,
        ideality_factor: float = 1.3,
        cells_in_series: int = 60,
        series_resistance: float = 0.3,
        shunt_resistance: float = 300.0,
        irradiance: float = 1000.0,
        temperature: float = 25.0,
    ) -> None:
        if not (math.isfinite(series_resistance) and series_resistance >= 0.0):
            raise ValueError(f"series_resistance must be finite and >= 0; got {series_resistance}")
        if not shunt_resistance > 0.0:  # also rejects nan; inf is allowed
            raise ValueError(f"shunt_resistance must be > 0 (inf allowed); got {shunt_resistance}")
        self.photocurrent = photocurrent
        self.saturation_current = saturation_current
        self.ideality_factor = ideality_factor
        self.cells_in_series = cells_in_series
        self.series_resistance = series_resistance
        self.shunt_resistance = shunt_resistance
        self.irradiance = irradiance
        self.temperature = temperature

    @property
    def module_thermal_voltage(self) -> float:
        vt = _BOLTZMANN * (self.temperature + 273.15) / _ELECTRON_CHARGE
        return self.ideality_factor * self.cells_in_series * vt

    @property
    def _light_current(self) -> float:
        return self.photocurrent * self.irradiance / 1000.0

    def _residual(self, i, v, a, g_sh):
        """Return ``f(I)`` and ``df/dI`` for terminal voltage ``v``."""
        rs = self.series_resistance
        x = v + i * rs
        e = np.exp(np.minimum(x / a, _EXP_LIMIT))
        f = self._light_current - self.saturation_current * (e - 1.0) - x * g_sh - i
        df = -(self.saturation_current * e / a + g_sh) * rs - 1.0
        return f, df

    def _solve(self, v: np.ndarray) -> np.ndarray:
        """Solve the implicit equation for ``I`` at each voltage in ``v``."""
        a = self.module_thermal_voltage
        g_sh = 1.0 / self.shunt_resistance
        iph = self._light_current
        i0 = self.saturation_current
        lo = np.zeros_like(v)
        # f(hi) <= 0: at I = hi the diode and shunt terms take away all of I_ph
        hi = np.full_like(v, iph + i0) + np.maximum(-v, 0.0) * g_sh
        # Root at or below 0 (V >= Voc): current is clamped to 0, as in the ideal model
        f_lo, _ = self._residual(lo, v, a, g_sh)
        dead = f_lo <= 0.0
        i = np.clip(iph - v * g_sh, lo, hi)
        old_step = hi - lo
        for _ in range(_MAX_ITER):
            f, df = self._residual(i, v, a, g_sh)
            # |df| >= 1, so |f| is an upper bound on the error of i
            done = dead | (np.abs(f) <= _F_TOL) | (hi - lo <= _WIDTH_TOL * (1.0 + np.abs(i)))
            if np.all(done):
                break
            # f is decreasing: f > 0 means the root is above i
            lo = np.where(f > 0.0, i, lo)
            hi = np.where(f > 0.0, hi, i)
            with np.errstate(all="ignore"):
                newton = i - f / df
            # Accept Newton only if it stays inside the bracket and at least
            # halves the last step. Otherwise it may crawl, so bisect instead.
            ok = np.isfinite(newton) & (newton > lo) & (newton < hi)
            ok &= np.abs(newton - i) <= 0.5 * old_step
            new = np.where(ok, newton, 0.5 * (lo + hi))
            old_step = np.where(done, old_step, np.abs(new - i))
            i = np.where(done, i, new)
        return np.where(dead, 0.0, i)

    def current(self, voltage):
        v = np.asarray(voltage, dtype=float)
        if not np.all(np.isfinite(v)):
            raise ValueError("voltage must be finite")
        i = self._solve(np.atleast_1d(v).astype(float)).reshape(v.shape)
        return float(i) if v.ndim == 0 else i

    @property
    def open_circuit_voltage(self) -> float:
        a = self.module_thermal_voltage
        g_sh = 1.0 / self.shunt_resistance
        iph = self._light_current
        if iph <= 0.0:
            return 0.0
        # I = 0 gives g(V) = I_ph - I_0 (exp(V/a) - 1) - V/R_sh, decreasing in V.
        # The ideal Voc is an upper bound because R_sh only lowers the current.
        lo, hi = 0.0, a * float(np.log(iph / self.saturation_current + 1.0))
        for _ in range(_MAX_ITER):
            mid = 0.5 * (lo + hi)
            g = iph - self.saturation_current * np.expm1(mid / a) - mid * g_sh
            if g > 0.0:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    @property
    def short_circuit_current(self) -> float:
        return float(self.current(0.0))
