"""Smoke tests for the SDK's public surface.

These tests are deliberately minimal — they verify that the abstractions
hold their basic invariants (Isc / Voc, MPP envelope, SEPIC reflected
resistance, P&O convergence) so CI catches gross regressions without
needing the full comparison harness from Phase 4.
"""

import math
from itertools import pairwise

# Force matplotlib to a non-interactive backend before any module under
# test imports it lazily. This keeps the visualization tests headless
# under CI.
import matplotlib

matplotlib.use("Agg")

import mpp_sdk


def test_version_is_a_nonempty_string():
    assert isinstance(mpp_sdk.__version__, str)
    assert mpp_sdk.__version__


def test_ideal_panel_endpoints():
    panel = mpp_sdk.IdealSingleDiode()
    isc = panel.short_circuit_current
    voc = panel.open_circuit_voltage
    assert math.isclose(panel.current(0.0), isc, rel_tol=1e-6)
    assert panel.current(voc) < 1e-3
    assert voc > 0.0
    assert isc > 0.0


def test_ideal_panel_mpp_inside_envelope():
    panel = mpp_sdk.IdealSingleDiode()
    v_mpp, i_mpp, p_mpp = panel.mpp()
    assert 0.0 < v_mpp < panel.open_circuit_voltage
    assert 0.0 < i_mpp < panel.short_circuit_current
    # Fill factor (P_mpp / (Voc·Isc)) for an ideal single-diode is well
    # above 0.7 — pin a generous lower bound rather than the exact value
    # so the test survives parameter tweaks.
    fill_factor = p_mpp / (panel.open_circuit_voltage * panel.short_circuit_current)
    assert fill_factor > 0.7


def test_sepic_unity_at_d_half():
    conv = mpp_sdk.SEPICConverter()
    assert math.isclose(conv.reflected_resistance(0.5, 10.0), 10.0, rel_tol=1e-9)


def test_sepic_clamps_duty():
    conv = mpp_sdk.SEPICConverter(min_duty=0.1, max_duty=0.9)
    assert conv.clamp(-1.0) == 0.1
    assert conv.clamp(0.0) == 0.1
    assert conv.clamp(0.5) == 0.5
    assert conv.clamp(1.0) == 0.9
    assert conv.clamp(2.0) == 0.9


def test_sepic_reflected_resistance_monotonic_in_d():
    conv = mpp_sdk.SEPICConverter()
    duties = [0.1, 0.2, 0.3, 0.5, 0.7, 0.9]
    rs = [conv.reflected_resistance(d, 10.0) for d in duties]
    assert all(a > b for a, b in pairwise(rs))


def test_pno_converges_within_one_percent_of_mpp():
    panel = mpp_sdk.IdealSingleDiode()
    src = mpp_sdk.SimulatedSource(
        panel,
        mpp_sdk.SEPICConverter(),
        load_resistance=10.0,
        initial_duty=0.1,
    )
    ctl = mpp_sdk.PerturbAndObserve(initial_duty=src.duty, step_size=0.005)
    for _ in range(800):
        v, i = src.read()
        src.write(ctl.step(v, i))
    v, i = src.read()
    _, _, p_mpp = panel.mpp()
    assert (v * i) / p_mpp > 0.99


def test_one_shot_plot_renders_headless():
    """The visualization helper must not blow up on a non-interactive backend."""
    import matplotlib.pyplot as plt

    panel = mpp_sdk.IdealSingleDiode()
    v_mpp, i_mpp, _ = panel.mpp()
    mpp_sdk.plot_iv_with_operating_point(panel, operating_point=(v_mpp, i_mpp))
    plt.close("all")
