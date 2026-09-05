"""Hardware-abstraction layer.

The ``SignalSource`` ABC is the seam between simulation and real hardware.
Concrete sources include ``SimulatedSource`` (panel + converter + load
running in software) and, eventually, a Raspberry-Pi-backed source that
reads ADC channels and writes a hardware-PWM duty cycle.
"""

from .base import SignalSource
from .dynamic import DynamicSimulatedSource
from .noisy import NoisySource
from .simulated import SimulatedSource

__all__ = [
    "SignalSource",
    "SimulatedSource",
    "DynamicSimulatedSource",
    "NoisySource",
    "SpiMcuSource",
    "SweepProgress",
]


def __getattr__(name: str):
    if name in ("SpiMcuSource", "SweepProgress"):
        from . import spi_mcu  # noqa: PLC0415

        return getattr(spi_mcu, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
