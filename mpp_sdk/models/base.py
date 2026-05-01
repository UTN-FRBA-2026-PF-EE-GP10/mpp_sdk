"""Abstract base class for solar-panel I-V models."""

from abc import ABC, abstractmethod

import numpy as np


class PanelModel(ABC):
    """Solar-panel I-V model.

    A concrete subclass implements ``current(V)``, ``open_circuit_voltage``,
    and ``short_circuit_current``. Everything else (P-V sampling, MPP search)
    is derived from those.

    Richer models may carry mutable state — e.g. cell temperature and
    incident irradiance — that is set by the simulation loop between steps.
    The ``current(V)`` interface stays uniform so algorithms remain agnostic.
    """

    @abstractmethod
    def current(self, voltage):
        """Return panel output current at the given terminal voltage.

        Accepts a scalar or a ``numpy`` array.
        """

    @property
    @abstractmethod
    def open_circuit_voltage(self) -> float:
        """Voltage at which ``I = 0``."""

    @property
    @abstractmethod
    def short_circuit_current(self) -> float:
        """Current at which ``V = 0``."""

    def power(self, voltage):
        return np.asarray(voltage) * self.current(voltage)

    def iv_curve(self, n: int = 401):
        """Sample the I-V curve from ``0`` to ``Voc`` with ``n`` points."""
        v = np.linspace(0.0, self.open_circuit_voltage, n)
        i = self.current(v)
        return v, np.asarray(i)

    def mpp(self, n: int = 4001) -> tuple[float, float, float]:
        """Numeric maximum power point on a sampled I-V curve.

        Returns ``(V_mpp, I_mpp, P_mpp)``. The grid is fine enough for
        plotting and demos; analytic / Newton-based MPP solvers belong on
        the concrete model when needed.
        """
        v, i = self.iv_curve(n)
        p = v * i
        k = int(np.argmax(p))
        return float(v[k]), float(i[k]), float(p[k])
