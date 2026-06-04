"""pvlib-backed single-diode panel model (Phase 2 — realistic models).

Requires the ``pvlib`` optional dependency::

    uv sync --extra pvlib
"""

from __future__ import annotations

import math

import numpy as np

from .base import PanelModel

try:
    import pvlib
    import pvlib.ivtools.sdm
    import pvlib.pvsystem
    import pvlib.singlediode

    _PVLIB_AVAILABLE = True
except ImportError:
    _PVLIB_AVAILABLE = False


def _require_pvlib() -> None:
    if not _PVLIB_AVAILABLE:
        raise ImportError(
            "pvlib is required for PvlibPanelModel. Install it with: uv sync --extra pvlib"
        )


class PvlibPanelModel(PanelModel):
    """Single-diode panel model backed by pvlib's De Soto equations.

    Takes the 5-parameter De Soto SDM directly.  Use the ``from_datasheet``
    classmethod to fit parameters from datasheet IV points, or use a
    pre-fitted factory like ``hissuma_psf10mono``.

    ``irradiance`` and ``temperature`` are mutable — update them between
    simulation steps to model changing environmental conditions.

    Parameters
    ----------
    I_L_ref, I_o_ref, R_s, R_sh_ref, a_ref :
        De Soto SDM parameters at STC (1000 W/m², 25 °C).
        See pvlib.pvsystem.calcparams_desoto for exact definitions.
    alpha_sc :
        Short-circuit current temperature coefficient [A/°C].
    irradiance :
        Effective plane-of-array irradiance [W/m²] (default: STC).
    temperature :
        Cell temperature [°C] (default: STC).
    """

    def __init__(
        self,
        I_L_ref: float,
        I_o_ref: float,
        R_s: float,
        R_sh_ref: float,
        a_ref: float,
        alpha_sc: float,
        irradiance: float = 1000.0,
        temperature: float = 25.0,
    ) -> None:
        _require_pvlib()
        self._I_L_ref = I_L_ref
        self._I_o_ref = I_o_ref
        self._R_s = R_s
        self._R_sh_ref = R_sh_ref
        self._a_ref = a_ref
        self._alpha_sc = alpha_sc
        self.irradiance = irradiance
        self.temperature = temperature

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_datasheet(
        cls,
        v_mp: float,
        i_mp: float,
        v_oc: float,
        i_sc: float,
        alpha_sc: float,
        beta_voc: float,
        cells_in_series: int,
        irradiance: float = 1000.0,
        temperature: float = 25.0,
    ) -> PvlibPanelModel:
        """Fit De Soto SDM parameters from standard datasheet IV values.

        Uses pvlib's ``fit_desoto`` with an analytically-derived initial
        guess to improve convergence on small / low-current panels.

        Parameters
        ----------
        v_mp, i_mp : float
            Voltage and current at MPP at STC [V, A].
        v_oc : float
            Open-circuit voltage at STC [V].
        i_sc : float
            Short-circuit current at STC [A].
        alpha_sc : float
            Isc temperature coefficient [A/°C].
        beta_voc : float
            Voc temperature coefficient [V/°C]  (negative for Si).
        cells_in_series : int
            Number of cells in series in the module.
        """
        _require_pvlib()
        # Estimate a_ref from the simplified 3-parameter diode model
        # I_mp = I_ph * (1 - exp((Vmp - Voc) / a))  →  a = (Voc-Vmp) / -ln(1-Imp/Isc)
        a_est = (v_oc - v_mp) / (-math.log(1.0 - i_mp / i_sc))
        io_est = i_sc * math.exp(-v_oc / a_est)
        rs_est = max(0.0, (a_est * math.log1p((i_sc - i_mp) / io_est) - v_mp) / i_mp)
        sdm, _ = pvlib.ivtools.sdm.fit_desoto(
            v_mp=v_mp,
            i_mp=i_mp,
            v_oc=v_oc,
            i_sc=i_sc,
            alpha_sc=alpha_sc,
            beta_voc=beta_voc,
            cells_in_series=cells_in_series,
            init_guess={"a_0": a_est, "Io_0": io_est, "Rs_0": rs_est, "Rsh_0": 500.0},
        )
        return cls(
            I_L_ref=sdm["I_L_ref"],
            I_o_ref=sdm["I_o_ref"],
            R_s=sdm["R_s"],
            R_sh_ref=sdm["R_sh_ref"],
            a_ref=sdm["a_ref"],
            alpha_sc=alpha_sc,
            irradiance=irradiance,
            temperature=temperature,
        )

    @classmethod
    def hissuma_psf10mono(
        cls,
        irradiance: float = 1000.0,
        temperature: float = 25.0,
    ) -> PvlibPanelModel:
        """Hissuma PSF10MONO (10 W, mono-Si).

        Datasheet: Voc=17 V, Isc=0.79 A, Vmp=14 V, Imp=0.72 A, Pmax=10 W.
        SDM parameters derived analytically from the simplified 3-parameter
        diode model with typical mono-Si temperature coefficients
        (αIsc = +0.04 %/°C, βVoc = −0.33 %/°C).

        Validated at STC:
            Voc  ≈ 17.0 V   (= a_ref × ln(I_L / I_o))
            Isc  ≈ 0.79 A   (≈ I_L_ref)
            Pmax ≈ 10.0 W
        """
        # a_ref = (Voc - Vmp) / -ln(1 - Imp/Isc) = 3 / -ln(1 - 0.72/0.79) = 1.238 V
        # I_o  = Isc × exp(-Voc / a_ref) = 0.79 × exp(-13.73) ≈ 8.6e-7 A
        return cls(
            I_L_ref=0.791,
            I_o_ref=8.6e-7,
            R_s=0.10,
            R_sh_ref=800.0,
            a_ref=1.238,
            alpha_sc=0.00032,  # +0.04 %/°C × 0.79 A
            irradiance=irradiance,
            temperature=temperature,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _operating_params(self) -> tuple:
        """Return (IL, I0, Rs, Rsh, nNsVth) at current irradiance / temperature."""
        return pvlib.pvsystem.calcparams_desoto(
            effective_irradiance=self.irradiance,
            temp_cell=self.temperature,
            alpha_sc=self._alpha_sc,
            a_ref=self._a_ref,
            I_L_ref=self._I_L_ref,
            I_o_ref=self._I_o_ref,
            R_sh_ref=self._R_sh_ref,
            R_s=self._R_s,
        )

    # ------------------------------------------------------------------
    # PanelModel interface
    # ------------------------------------------------------------------

    def current(self, voltage):
        v = np.asarray(voltage, dtype=float)
        il, io, rs, rsh, nnsvth = self._operating_params()
        i = pvlib.singlediode.bishop88_i_from_v(v, il, io, rs, rsh, nnsvth, method="newton")
        i = np.maximum(np.asarray(i, dtype=float), 0.0)
        return float(i) if v.ndim == 0 else i

    @property
    def open_circuit_voltage(self) -> float:
        il, io, rs, rsh, nnsvth = self._operating_params()
        out = pvlib.pvsystem.singlediode(il, io, rs, rsh, nnsvth)
        return float(out["v_oc"])

    @property
    def short_circuit_current(self) -> float:
        il, io, rs, rsh, nnsvth = self._operating_params()
        out = pvlib.pvsystem.singlediode(il, io, rs, rsh, nnsvth)
        return float(out["i_sc"])

    def mpp(self, n: int = 4001) -> tuple[float, float, float]:
        """MPP from pvlib's analytic solver — faster than the base-class grid search."""
        il, io, rs, rsh, nnsvth = self._operating_params()
        out = pvlib.pvsystem.singlediode(il, io, rs, rsh, nnsvth)
        return float(out["v_mp"]), float(out["i_mp"]), float(out["p_mp"])
