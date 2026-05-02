"""Software ``SignalSource`` backed by a panel + converter + load."""

from ..converters.sepic import SEPICConverter
from ..models.base import PanelModel
from .base import SignalSource


class SimulatedSource(SignalSource):
    """Panel + SEPIC-converter + resistive-load operating-point solver.

    Given a requested duty cycle ``D``, this source resolves the panel
    operating point by solving

        I_panel(V) = V / R_eff

    on ``V ∈ [0, Voc]``, where ``R_eff`` is the converter's reflected
    resistance at duty ``D`` (for an ideal SEPIC,
    ``R_eff = R_load · ((1 - D) / D)²``). The panel I-V is monotonically
    decreasing in V and the right-hand side is monotonically increasing,
    so a simple bisection converges quickly and is robust without needing
    scipy.
    """

    def __init__(
        self,
        panel: PanelModel,
        converter: SEPICConverter,
        load_resistance: float,
        initial_duty: float = 0.5,
        bisection_iterations: int = 60,
    ) -> None:
        if load_resistance <= 0.0:
            raise ValueError(f"load_resistance must be > 0; got {load_resistance!r}")
        self._panel = panel
        self._converter = converter
        self._load = load_resistance
        self._bisect_iters = bisection_iterations
        self._duty = converter.clamp(initial_duty)
        self._v, self._i = self._operating_point(self._duty)

    def _operating_point(self, duty: float) -> tuple[float, float]:
        r_eff = self._converter.reflected_resistance(duty, self._load)
        lo, hi = 0.0, self._panel.open_circuit_voltage
        for _ in range(self._bisect_iters):
            mid = 0.5 * (lo + hi)
            f_mid = float(self._panel.current(mid)) - mid / r_eff
            if f_mid > 0.0:
                lo = mid
            else:
                hi = mid
        v = 0.5 * (lo + hi)
        return v, float(self._panel.current(v))

    def read(self) -> tuple[float, float]:
        return self._v, self._i

    def write(self, duty_cycle: float) -> None:
        self._duty = self._converter.clamp(duty_cycle)
        self._v, self._i = self._operating_point(self._duty)

    @property
    def duty(self) -> float:
        return self._duty

    @property
    def load_resistance(self) -> float:
        return self._load
