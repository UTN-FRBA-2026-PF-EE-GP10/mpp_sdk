"""Abstract base class for MPPT controllers."""

from abc import ABC, abstractmethod


class MPPTAlgorithm(ABC):
    """Closed-loop maximum-power-point tracking controller.

    A concrete algorithm consumes ``(V, I)`` measurements from a
    ``SignalSource`` and decides on the next converter duty cycle.
    Implementations must be agnostic to the panel and converter models —
    they see only V, I, and (optionally) the duty cycle they previously
    requested. That constraint is what lets the same controller code run
    in simulation and on a Raspberry Pi without modification.
    """

    @abstractmethod
    def step(self, voltage: float, current: float) -> float:
        """Return the next duty cycle to apply, given the latest ``(V, I)``."""
