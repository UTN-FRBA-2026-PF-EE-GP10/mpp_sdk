"""Hardware-abstraction layer.

The ``SignalSource`` ABC is the seam between simulation and real hardware.
Concrete sources include ``SimulatedSource`` (panel + converter + load
running in software) and ``SpiMcuSource``, a Raspberry-Pi-backed source that
talks to the RP2040 firmware over SPI to read ``(V, I)`` and write a duty
cycle.
"""

from .base import SignalSource
from .dynamic import DynamicSimulatedSource
from .noisy import NoisySource
from .simulated import SimulatedSource
from .sweep_source import SweepProgressLike, SweepSource

__all__ = [
    "SignalSource",
    "SimulatedSource",
    "DynamicSimulatedSource",
    "NoisySource",
    "SpiMcuSource",
    "SweepProgress",
    "SweepSource",
    "SweepProgressLike",
]


def __getattr__(name: str):
    if name in ("SpiMcuSource", "SweepProgress"):
        from . import spi_mcu  # noqa: PLC0415

        return getattr(spi_mcu, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
