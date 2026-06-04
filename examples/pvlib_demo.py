"""PvlibPanelModel demo — Hissuma PSF10MONO I-V and P-V curves.

Shows how irradiance and temperature shift the curves and the MPP.

Run with::

    uv run examples/pvlib_demo.py
"""

import matplotlib.pyplot as plt

from mpp_sdk.models.pvlib_adapter import PvlibPanelModel

# ── colour palettes ────────────────────────────────────────────────────────────
IRRAD_LEVELS = [200, 400, 600, 800, 1000]  # W/m²
TEMP_LEVELS = [15, 25, 45, 65]  # °C
BLUE = plt.cm.Blues_r
RED = plt.cm.Reds


def plot_curves(ax_iv, ax_pv, panel, label, color):
    v, i = panel.iv_curve(n=400)
    p = v * i
    v_mpp, i_mpp, p_mpp = panel.mpp()

    ax_iv.plot(v, i, color=color, label=label)
    ax_iv.plot(v_mpp, i_mpp, "o", color=color, ms=5)

    ax_pv.plot(v, p, color=color, label=label)
    ax_pv.plot(v_mpp, p_mpp, "o", color=color, ms=5)


def main():
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    fig.suptitle("Hissuma PSF10MONO — I-V and P-V curves", fontweight="bold")

    ax_iv_g, ax_pv_g = axes[0]  # irradiance sweep
    ax_iv_t, ax_pv_t = axes[1]  # temperature sweep

    # ── irradiance sweep (T = 25 °C) ──────────────────────────────────────────
    n = len(IRRAD_LEVELS)
    for k, g in enumerate(IRRAD_LEVELS):
        panel = PvlibPanelModel.hissuma_psf10mono(irradiance=g, temperature=25.0)
        color = BLUE(0.15 + 0.7 * k / (n - 1))
        plot_curves(ax_iv_g, ax_pv_g, panel, f"{g} W/m²", color)

    ax_iv_g.set_title("Irradiance sweep (T = 25 °C)")
    ax_iv_g.set_xlabel("Voltage [V]")
    ax_iv_g.set_ylabel("Current [A]")
    ax_iv_g.legend(fontsize=8)

    ax_pv_g.set_title("Irradiance sweep (T = 25 °C)")
    ax_pv_g.set_xlabel("Voltage [V]")
    ax_pv_g.set_ylabel("Power [W]")
    ax_pv_g.legend(fontsize=8)

    # ── temperature sweep (G = 1000 W/m²) ────────────────────────────────────
    n = len(TEMP_LEVELS)
    for k, t in enumerate(TEMP_LEVELS):
        panel = PvlibPanelModel.hissuma_psf10mono(irradiance=1000.0, temperature=t)
        color = RED(0.15 + 0.7 * k / (n - 1))
        plot_curves(ax_iv_t, ax_pv_t, panel, f"{t} °C", color)

    ax_iv_t.set_title("Temperature sweep (G = 1000 W/m²)")
    ax_iv_t.set_xlabel("Voltage [V]")
    ax_iv_t.set_ylabel("Current [A]")
    ax_iv_t.legend(fontsize=8)

    ax_pv_t.set_title("Temperature sweep (G = 1000 W/m²)")
    ax_pv_t.set_xlabel("Voltage [V]")
    ax_pv_t.set_ylabel("Power [W]")
    ax_pv_t.legend(fontsize=8)

    # ── annotate STC MPP ──────────────────────────────────────────────────────
    stc = PvlibPanelModel.hissuma_psf10mono()
    v_mpp, i_mpp, p_mpp = stc.mpp()
    for ax, y, label in [
        (ax_iv_g, i_mpp, f"MPP: ({v_mpp:.1f} V, {i_mpp:.3f} A)"),
        (ax_pv_g, p_mpp, f"MPP: ({v_mpp:.1f} V, {p_mpp:.2f} W)"),
    ]:
        ax.annotate(
            label,
            xy=(v_mpp, y),
            xytext=(v_mpp - 4, y + 0.05 * y),
            fontsize=7,
            arrowprops=dict(arrowstyle="->", lw=0.8),
        )

    for ax in axes.flat:
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        ax.grid(True, alpha=0.3)

    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
