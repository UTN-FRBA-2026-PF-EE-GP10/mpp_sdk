"""Static snapshot of the live MPPT view (headless, saves a PNG).

Renders the same two-panel layout as ``harness/animate.py`` but without the
interactive window. The two series panels sit under partial shading
(G1=1000, G2=300 W/m²), which gives the P-V curve two peaks, and every
algorithm starts from the Voc side (duty 0.3). This is the case that
separates the families: the local trackers climb to the nearest (local)
peak and stay trapped, while the global ones search the whole range and
land on the true MPP. Left panel: each algorithm's operating point on the
P-V curve, with the I-V curve as a grey backdrop and the global MPP
starred. Right panel: tracking efficiency vs time.

Useful for slides and the paper, where the live animation cannot be shown.

Run with::

    uv run harness/snapshot.py

Saves a PNG to ``harness/output/animate_frame.png``.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless - save PNG instead of showing a window
import matplotlib.pyplot as plt
import numpy as np

from harness.animate import ALGORITHMS, Runner, build_panel
from harness.panel_config import CONTROL_PERIOD_MS

INITIAL_DUTY = 0.3  # start from the Voc side so locals fall into the local peak
SPEED = 2  # control steps advanced per recorded sample
RECORD = 250  # samples recorded (the visible trace)
G_BRIGHT = 1000.0
G_SHADE = 300.0


def main() -> None:
    shaded = build_panel(G_BRIGHT, G_SHADE)

    runners = [Runner(cls, shaded, INITIAL_DUTY) for _, cls, _ in ALGORITHMS]

    v_curve, i_curve = shaded.iv_curve(n=400)
    p_curve = v_curve * i_curve
    k = int(np.argmax(p_curve))
    mpp_v, mpp_p = float(v_curve[k]), float(p_curve[k])

    t_ms: list[float] = []
    eta_hist: list[list[float]] = [[] for _ in ALGORITHMS]
    for step in range(RECORD):
        t_ms.append(step * SPEED * CONTROL_PERIOD_MS)
        for idx, r in enumerate(runners):
            _v, p = r.advance(SPEED)
            eta_hist[idx].append(p / max(mpp_p, 1e-9) * 100.0)

    fig, (ax, ax_t) = plt.subplots(1, 2, figsize=(15, 7))
    fig.subplots_adjust(left=0.07, right=0.93, top=0.9, bottom=0.12, wspace=0.32)
    fig.suptitle("MPPT bajo sombreado parcial (G1=1000, G2=300 W/m²)", fontweight="bold")

    # left: P-V curve + I-V backdrop
    ax_iv = ax.twinx()
    ax_iv.plot(v_curve, i_curve, color="grey", lw=1.2, ls="--", alpha=0.6, zorder=0)
    ax_iv.set_ylabel("Corriente [A]", color="grey")
    ax_iv.tick_params(axis="y", labelcolor="grey")
    ax_iv.set_ylim(0, i_curve.max() * 1.25)

    ax.plot(v_curve, p_curve, "k-", lw=1.5, zorder=1, label="curva P-V")
    ax.plot([mpp_v], [mpp_p], "k*", ms=18, zorder=5, label="MPP global")
    ax.plot([], [], color="grey", ls="--", alpha=0.6, label="curva I-V")
    for (label, _, color), r in zip(ALGORITHMS, runners, strict=True):
        arr = np.asarray(r.trail)
        ax.plot(arr[:, 0], arr[:, 1], "-", color=color, alpha=0.4, lw=1, zorder=3)
        ax.plot([arr[-1, 0]], [arr[-1, 1]], "o", color=color, ms=12, zorder=4, label=label)
    ax.set_title("Punto de operación sobre la curva P-V")
    ax.set_xlabel("Tensión [V]")
    ax.set_ylabel("Potencia [W]")
    ax.set_xlim(0, v_curve[-1] * 1.05)
    ax.set_ylim(0, p_curve.max() * 1.25)
    ax.set_zorder(ax_iv.get_zorder() + 1)
    ax.patch.set_visible(False)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=9)

    # right: efficiency vs time
    ax_t.axhline(100.0, color="k", lw=1, ls="--", label="MPP global (100 %)")
    for (label, _, color), eta in zip(ALGORITHMS, eta_hist, strict=True):
        ax_t.plot(t_ms, eta, "-", color=color, lw=1.6, label=label)
    ax_t.set_title("Eficiencia de seguimiento vs tiempo")
    ax_t.set_xlabel("Tiempo [ms]")
    ax_t.set_ylabel(r"$\eta = P / P_\mathrm{mpp}$  [%]")
    ax_t.set_xlim(0, t_ms[-1])
    lo = min(min(h) for h in eta_hist)
    ax_t.set_ylim(max(0.0, np.floor(lo / 5) * 5 - 2), 101)
    ax_t.grid(True, alpha=0.3)
    ax_t.legend(loc="lower right", fontsize=9)

    out = Path(__file__).parent / "output" / "animate_frame.png"
    fig.savefig(out, dpi=120)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
