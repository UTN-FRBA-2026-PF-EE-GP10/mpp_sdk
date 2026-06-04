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

from mpp_sdk import SEPICConverter, SimulatedSource
from mpp_sdk.models.pvlib_adapter import PvlibPanelModel

# ── Hardware safety limits ────────────────────────────────────────────────────
V_IN_MAX: float = 40.0  # V — maximum SEPIC input voltage
I_MAX: float = 1.0  # A — maximum string current

# ── Default environmental conditions ─────────────────────────────────────────
STC_IRRADIANCE: float = 1000.0  # W/m²
STC_TEMPERATURE: float = 25.0  # °C


def series_string(
    irradiance: float = STC_IRRADIANCE,
    temperature: float = STC_TEMPERATURE,
) -> PvlibPanelModel:
    """Two Hissuma PSF10MONO panels wired in series.

    A series string doubles all voltage-related De Soto parameters
    (V_oc, V_mp, a_ref, R_s, R_sh_ref) while current parameters stay
    unchanged (I_sc, I_mp, I_L_ref, I_o_ref, alpha_sc).

    Returns a ``PvlibPanelModel`` representing the string as a single
    equivalent module. Use ``PvString`` (Phase 2) once partial-shading
    simulation is needed.
    """
    single = PvlibPanelModel.hissuma_psf10mono()
    return PvlibPanelModel(
        I_L_ref=single._I_L_ref,
        I_o_ref=single._I_o_ref,  # Voc/a_ref unchanged → I_o unchanged
        R_s=single._R_s * 2,
        R_sh_ref=single._R_sh_ref * 2,
        a_ref=single._a_ref * 2,  # proportional to N_s
        alpha_sc=single._alpha_sc,  # series → same current coefficient
        irradiance=irradiance,
        temperature=temperature,
    )


def make_source(
    panel: PvlibPanelModel | None = None,
    load_resistance: float = 10.0,
    initial_duty: float = 0.5,
) -> SimulatedSource:
    """Return a ``SimulatedSource`` for the series string.

    Default load_resistance=10 Ω places the MPPT start point (D=0.5,
    R_eff=10 Ω) below the series-string MPP impedance (~38.9 Ω), so
    algorithms approach the MPP from the right side of the P-V curve.
    """
    if panel is None:
        panel = series_string()
    return SimulatedSource(
        panel=panel,
        converter=SEPICConverter(),
        load_resistance=load_resistance,
        initial_duty=initial_duty,
    )
