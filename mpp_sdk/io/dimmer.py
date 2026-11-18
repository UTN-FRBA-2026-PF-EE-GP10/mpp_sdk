"""Lamp dimmer helpers: alpha wire format, lamp power maths, status frame parser.

No spidev import here, so a server can use it without the hardware extra.
The wire format is described in ``docs/hardware_v1/dimmer_link.md``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

ALPHA_FULL_ON_DEG = 0.0
ALPHA_OFF_DEG = 180.0
WIRE_ALPHA_FULL_ON = 0
WIRE_ALPHA_OFF = 18000
WIRE_ALPHA_UNKNOWN = 0xFFFF
STATUS_MAGIC = 0xD2
_AGE_UNIT_S = 0.1


def alpha_to_wire(alpha_deg: float) -> int:
    """Convert a firing angle in degrees to centi-degrees (rounded to 0.01 degree)."""
    alpha = float(alpha_deg)
    if not math.isfinite(alpha) or alpha < ALPHA_FULL_ON_DEG or alpha > ALPHA_OFF_DEG:
        raise ValueError(f"alpha must be in [0, {ALPHA_OFF_DEG:g}] degrees, got {alpha_deg!r}")
    return round(alpha * 100)


def lamp_power_fraction(alpha_deg: float) -> float:
    """Power fraction of a resistive lamp at firing angle *alpha_deg* (1 at 0, 0 at 180)."""
    a = math.radians(alpha_deg)
    return 1.0 - a / math.pi + math.sin(2.0 * a) / (2.0 * math.pi)


def alpha_for_power(fraction: float) -> float:
    """Firing angle in degrees for a power *fraction* in [0, 1] (inverse of the power law)."""
    p = float(fraction)
    if not math.isfinite(p) or p < 0.0 or p > 1.0:
        raise ValueError(f"power fraction must be in [0, 1], got {fraction!r}")
    if p == 0.0:
        return ALPHA_OFF_DEG
    if p == 1.0:
        return ALPHA_FULL_ON_DEG
    lo, hi = ALPHA_FULL_ON_DEG, ALPHA_OFF_DEG
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        # Power falls as alpha rises.
        if lamp_power_fraction(mid) > p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class DimmerStatus:
    """Dimmer state as reported by the Pico."""

    link_ok: bool
    mains: bool
    locked: bool
    timed_out: bool
    set_alpha_deg: float
    applied_alpha_deg: float | None
    age_s: float


def parse_status_frame(rx: Sequence[int]) -> DimmerStatus | None:
    """Parse the 12-byte reply to the status command, or None on a bad frame."""
    from .spi_crc import crc8  # noqa: PLC0415

    if len(rx) != 12 or rx[0] != STATUS_MAGIC:
        return None
    if rx[8] != crc8([*rx[0:8], rx[9], rx[10]]):
        return None
    flags = rx[1]
    applied = (rx[4] << 8) | rx[5]
    return DimmerStatus(
        link_ok=bool(flags & 0x01),
        mains=bool(flags & 0x02),
        locked=bool(flags & 0x04),
        timed_out=bool(flags & 0x08),
        set_alpha_deg=((rx[2] << 8) | rx[3]) / 100.0,
        applied_alpha_deg=None if applied == WIRE_ALPHA_UNKNOWN else applied / 100.0,
        age_s=rx[6] * _AGE_UNIT_S,
    )
