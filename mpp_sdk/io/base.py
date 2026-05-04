"""Abstract V/I sense + duty-cycle drive interface."""

from abc import ABC, abstractmethod


class SignalSource(ABC):
    """V/I sensing and duty-cycle drive abstraction.

    All MPPT algorithms in this SDK interact with the world exclusively
    through this interface. Two concrete implementations are expected:

    - ``SimulatedSource`` — wraps a panel model + DC-DC converter + load and
      computes ``(V, I)`` from the requested duty cycle.
    - A future hardware source — reads ADC channels for V and I and writes
      a PWM duty cycle on a Raspberry Pi 5 (or similar).

    Algorithms must not branch on which one they are talking to.
    """

    @abstractmethod
    def read(self) -> tuple[float, float]:
        """Return the most recent ``(voltage, current)`` measurement."""

    @abstractmethod
    def write(self, duty_cycle: float) -> None:
        """Apply a new duty cycle to the converter."""
