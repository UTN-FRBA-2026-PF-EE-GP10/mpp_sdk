"""Hardware-abstraction layer.

The ``SignalSource`` ABC is the seam between simulation and real hardware.
Concrete sources include ``SimulatedSource`` (panel + converter + load
running in software) and, eventually, a Raspberry-Pi-backed source that
reads ADC channels and writes a hardware-PWM duty cycle.
"""

from .base import SignalSource
from .simulated import SimulatedSource

__all__ = ["SignalSource", "SimulatedSource"]
