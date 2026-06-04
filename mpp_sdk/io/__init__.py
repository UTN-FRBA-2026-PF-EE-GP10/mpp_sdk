"""Hardware-abstraction layer.

The ``SignalSource`` ABC is the seam between simulation and real hardware.
Concrete sources include ``SimulatedSource`` (panel + converter + load
running in software) and, eventually, a Raspberry-Pi-backed source that
reads ADC channels and writes a hardware-PWM duty cycle.
"""

from .base import SignalSource
from .simulated import SimulatedSource

__all__ = ["SignalSource", "SimulatedSource", "SpiMcuSource"]


def __getattr__(name: str):
    if name == "SpiMcuSource":
        from .spi_mcu import SpiMcuSource  # noqa: PLC0415

        return SpiMcuSource
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
