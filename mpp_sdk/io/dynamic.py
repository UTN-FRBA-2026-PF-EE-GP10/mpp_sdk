"""Dynamic software ``SignalSource`` with first-order capacitor dynamics."""

import math

from ..converters.sepic import SEPICConverter
from ..models.base import PanelModel
from .base import SignalSource


class DynamicSimulatedSource(SignalSource):
    """Panel + SEPIC + load with input-capacitor dynamics.

    Unlike :class:`SimulatedSource`, which jumps instantly to the
    steady-state operating point, this source integrates the panel input
    capacitor so the terminal voltage *slews* toward the operating point:

        C · dV/dt = I_panel(V) − V / R_eff(D)

    This exposes the electrical transient — settling time, overshoot — that
    a real SEPIC exhibits between duty-cycle updates. The control period
    ``dt`` is split into ``substeps`` forward-Euler integration steps for
    numerical stability.

    Parameters
    ----------
    capacitance :
        Panel-terminal capacitance [F]. Larger C → slower, smoother slew.
    dt :
        Control period [s] — wall-clock time advanced per ``write()`` call.
    substeps :
        Integration sub-steps per control period (stability vs speed).
    """

    def __init__(
        self,
        panel: PanelModel,
        converter: SEPICConverter,
        load_resistance: float,
        capacitance: float = 100e-6,
        dt: float = 1e-3,
        initial_duty: float = 0.5,
        substeps: int = 50,
    ) -> None:
        if load_resistance <= 0.0:
            raise ValueError(f"load_resistance must be > 0; got {load_resistance!r}")
        if capacitance <= 0.0:
            raise ValueError(f"capacitance must be > 0; got {capacitance!r}")
        if not (math.isfinite(dt) and dt > 0.0):
            raise ValueError(f"dt must be a finite positive number; got {dt!r}")
        if substeps < 1:
            raise ValueError(f"substeps must be >= 1; got {substeps!r}")
        self._panel = panel
        self._converter = converter
        self._load = load_resistance
        self._cap = capacitance
        self._dt = dt
        self._substeps = substeps
        self._duty = converter.clamp(initial_duty)
        # Start at open-circuit voltage (capacitor charged, no load drawn yet).
        self._v = panel.open_circuit_voltage
        self._i = float(panel.current(self._v))

    def _advance(self, duty: float) -> None:
        """Integrate the capacitor ODE over one control period.

        The stiff linear term (``-V/R_eff``) is stepped exactly via
        exponential Euler (treating ``I_panel`` as constant over one
        substep); explicit Euler on that term is only stable for
        ``h < 2*R_eff*C``, which the scan's high-duty samples
        (``R_eff`` shrinks as ``D`` rises) violate at the harness's
        default ``dt``/``substeps``/``load_resistance``/``capacitance``.
        """
        r_eff = self._converter.reflected_resistance(duty, self._load)
        h = self._dt / self._substeps
        voc = self._panel.open_circuit_voltage  # constant over the control period
        decay = math.exp(-h / (r_eff * self._cap))
        v = self._v
        for _ in range(self._substeps):
            i_panel = float(self._panel.current(v))
            v_eq = i_panel * r_eff
            v = v_eq + (v - v_eq) * decay
            v = max(0.0, min(v, voc))
        self._v = v
        self._i = float(self._panel.current(v))

    def set_panel(self, panel: PanelModel) -> None:
        """Swap the panel model in place, keeping the dynamic state (V, duty).

        Lets a caller change irradiance / shading live and watch the controller
        re-track the new operating point. The terminal voltage is clamped to the
        new open-circuit voltage.
        """
        self._panel = panel
        self._v = min(self._v, panel.open_circuit_voltage)
        self._i = float(panel.current(self._v))

    def read(self) -> tuple[float, float]:
        return self._v, self._i

    def write(self, duty_cycle: float) -> None:
        self._duty = self._converter.clamp(duty_cycle)
        self._advance(self._duty)

    @property
    def duty(self) -> float:
        return self._duty

    @property
    def load_resistance(self) -> float:
        return self._load
