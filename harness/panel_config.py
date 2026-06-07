"""Hardware configuration for the 2× Hissuma PSF10MONO series string.

This module is the single source of truth for the physical setup used in
the thesis experiments. Any script in ``harness/`` imports from here so
that changing a parameter (irradiance, temperature, load) is a one-line
edit that propagates everywhere.

Hardware limits — SEPIC PCB design (do not exceed):
    V_in_max = 40 V   MOSFET V_ds rating (1.5× headroom on 34 V V_oc_series)
    I_max    =  1 A   inductor + sense resistor rated current

Panel: Hissuma PSF10MONO, 10 W mono-Si
    Single:  V_oc=17 V, I_sc=0.79 A, V_mp=14 V, I_mp=0.72 A, P_max=10 W
    Series:  V_oc=34 V, I_sc=0.79 A, V_mp=28 V, I_mp=0.72 A, P_max=20 W
"""

from mpp_sdk import (
    DynamicSimulatedSource,
    PvString,
    SEPICConverter,
    SimulatedSource,
    TabulatedPanel,
)
from mpp_sdk.models.pvlib_adapter import PvlibPanelModel

# ── Hardware safety limits ────────────────────────────────────────────────────
V_IN_MAX: float = 40.0  # V — maximum SEPIC input voltage
I_MAX: float = 1.0  # A — maximum string current

# ── Control loop timing ──────────────────────────────────────────────────────
CONTROL_PERIOD_MS: float = 1.0  # ms — one algorithm step = one control cycle
# Matches the RP2040 firmware target (1 kHz loop).
# Multiply step index by this to get real time and compare against PLECS.

# ── Default environmental conditions ─────────────────────────────────────────
STC_IRRADIANCE: float = 1000.0  # W/m²
STC_TEMPERATURE: float = 25.0  # °C


def series_string(
    irradiance: float = STC_IRRADIANCE,
    temperature: float = STC_TEMPERATURE,
) -> PvString:
    """Two Hissuma PSF10MONO panels wired in series (uniform irradiance).

    Both panels at the same irradiance → a single-peak P-V curve. For partial
    shading use :func:`shaded_string`.
    """
    return shaded_string((irradiance, irradiance), temperature=temperature)


def shaded_string(
    irradiances: tuple[float, float] = (1000.0, 400.0),
    temperature: float = STC_TEMPERATURE,
) -> PvString:
    """Two Hissuma panels in series with per-panel irradiance (partial shading).

    With ``irradiances=(1000, 400)`` one panel is shaded: its bypass diode
    conducts over part of the curve, producing a two-peak P-V curve where
    plain P&O can get trapped on the local maximum.
    """
    panels = [
        PvlibPanelModel.hissuma_psf10mono(irradiance=g, temperature=temperature)
        for g in irradiances
    ]
    return PvString(panels)


def make_dynamic_source(
    panel=None,
    load_resistance: float = 10.0,
    initial_duty: float = 0.5,
) -> DynamicSimulatedSource:
    """Return a ``DynamicSimulatedSource`` for the given panel.

    Uses input-capacitor dynamics so the terminal voltage slews toward the
    operating point instead of jumping — exposing settling time / overshoot.
    The panel is tabulated for speed (the I-V solve runs thousands of times).
    """
    if panel is None:
        panel = series_string()
    return DynamicSimulatedSource(
        panel=TabulatedPanel(panel),
        converter=SEPICConverter(),
        load_resistance=load_resistance,
        initial_duty=initial_duty,
        dt=CONTROL_PERIOD_MS * 1e-3,
    )


def make_static_source(
    panel=None,
    load_resistance: float = 10.0,
    initial_duty: float = 0.5,
) -> SimulatedSource:
    """Return a ``SimulatedSource`` (instant operating point, no dynamics)."""
    if panel is None:
        panel = series_string()
    return SimulatedSource(
        panel=TabulatedPanel(panel),
        converter=SEPICConverter(),
        load_resistance=load_resistance,
        initial_duty=initial_duty,
    )
