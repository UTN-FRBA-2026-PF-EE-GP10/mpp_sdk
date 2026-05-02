"""Ideal (lossless) single-diode panel model."""

import numpy as np

from .base import PanelModel

_BOLTZMANN = 1.380649e-23
_ELECTRON_CHARGE = 1.602176634e-19


class IdealSingleDiode(PanelModel):
    r"""Ideal single-diode panel: no series or shunt resistance.

    Module-level Shockley equation:

        I(V) = I_ph - I_0 * (exp(V / (n * N_s * V_t)) - 1)

    where ``V_t = k_B T / q`` is the cell thermal voltage. Because there is
    no series resistance, ``I(V)`` is explicit — no root-finding needed.

    This is the entry-level model. Later variants will add R_s / R_sh,
    explicit temperature and irradiance dependence, and finally
    interpolation over measured curves.
    """

    def __init__(
        self,
        photocurrent: float = 8.0,
        saturation_current: float = 1e-9,
        ideality_factor: float = 1.3,
        cells_in_series: int = 60,
        temperature_kelvin: float = 298.15,
    ) -> None:
        self.photocurrent = photocurrent
        self.saturation_current = saturation_current
        self.ideality_factor = ideality_factor
        self.cells_in_series = cells_in_series
        self.temperature_kelvin = temperature_kelvin

    @property
    def cell_thermal_voltage(self) -> float:
        return _BOLTZMANN * self.temperature_kelvin / _ELECTRON_CHARGE

    @property
    def module_thermal_voltage(self) -> float:
        return self.ideality_factor * self.cells_in_series * self.cell_thermal_voltage

    def current(self, voltage):
        v = np.asarray(voltage, dtype=float)
        i = self.photocurrent - self.saturation_current * np.expm1(v / self.module_thermal_voltage)
        i = np.maximum(i, 0.0)
        return float(i) if v.ndim == 0 else i

    @property
    def open_circuit_voltage(self) -> float:
        return float(
            self.module_thermal_voltage * np.log(self.photocurrent / self.saturation_current + 1.0)
        )

    @property
    def short_circuit_current(self) -> float:
        return float(self.photocurrent)
