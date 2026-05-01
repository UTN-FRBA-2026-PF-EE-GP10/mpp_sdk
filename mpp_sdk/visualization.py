"""Plotting helpers — both one-shot and live.

``matplotlib`` is imported lazily inside the constructors / functions, so
importing ``mpp_sdk`` itself stays cheap and matplotlib-free.
"""

from collections.abc import Sequence

import numpy as np

from .models.base import PanelModel


def plot_iv_with_operating_point(
    panel: PanelModel,
    operating_point: tuple[float, float] | None = None,
    history: Sequence[tuple[float, float]] | None = None,
    ax_iv=None,
    ax_pv=None,
):
    """One-shot plot of the panel's I-V and P-V curves with MPP and operating point.

    Use this for snapshots and tests; for an animated, indefinitely-running
    view drive a :class:`LivePanelView` from a control loop instead.

    Returns ``(ax_iv, ax_pv)`` so callers can decorate further.
    """
    import matplotlib.pyplot as plt

    if ax_iv is None or ax_pv is None:
        _fig, (ax_iv, ax_pv) = plt.subplots(1, 2, figsize=(10, 4))

    v, i = panel.iv_curve()
    p = v * i
    v_mpp, i_mpp, p_mpp = panel.mpp()

    ax_iv.plot(v, i, label="I-V curve")
    ax_iv.plot(
        v_mpp, i_mpp, "o", color="tab:green",
        label=f"MPP ({v_mpp:.2f} V, {i_mpp:.2f} A)",
    )

    ax_pv.plot(v, p, color="tab:orange", label="P-V curve")
    ax_pv.plot(
        v_mpp, p_mpp, "o", color="tab:green",
        label=f"MPP ({p_mpp:.2f} W)",
    )

    if history:
        h = np.asarray(history, dtype=float)
        ax_iv.plot(h[:, 0], h[:, 1], "-", color="tab:gray", alpha=0.4, label="trajectory")
        ax_pv.plot(h[:, 0], h[:, 0] * h[:, 1], "-", color="tab:gray", alpha=0.4)

    if operating_point is not None:
        v_op, i_op = operating_point
        ax_iv.plot(
            v_op, i_op, "s", color="tab:red",
            label=f"operating ({v_op:.2f} V, {i_op:.2f} A)",
        )
        ax_pv.plot(
            v_op, v_op * i_op, "s", color="tab:red",
            label=f"operating ({v_op * i_op:.2f} W)",
        )

    ax_iv.set_xlabel("V [V]")
    ax_iv.set_ylabel("I [A]")
    ax_iv.set_title("I-V curve")
    ax_iv.legend(loc="lower left")
    ax_iv.grid(True, alpha=0.3)

    ax_pv.set_xlabel("V [V]")
    ax_pv.set_ylabel("P [W]")
    ax_pv.set_title("P-V curve")
    ax_pv.legend(loc="lower center")
    ax_pv.grid(True, alpha=0.3)

    return ax_iv, ax_pv


class LivePanelView:
    """Animatable I-V / P-V view of a panel under MPPT control.

    Owns a 1×2 figure with the panel's I-V and P-V curves, the calculated
    MPP, the latest operating point, and a rolling trajectory. Call
    :meth:`update` once per simulation step; the static curves and MPP
    are recomputed each call so a model whose state mutates over time
    (irradiance, temperature, …) is rendered correctly.

    Typical usage with ``matplotlib.animation.FuncAnimation``::

        view = LivePanelView(panel)

        def step(_frame):
            panel.photocurrent = ...        # vary irradiance, temperature, ...
            v, i = source.read()
            d = controller.step(v, i)
            source.write(d)
            view.update((v, i))

        ani = FuncAnimation(view.fig, step, interval=20, cache_frame_data=False)
        plt.show()
    """

    def __init__(
        self,
        panel: PanelModel,
        history_window: int = 200,
        n_curve_points: int = 401,
        ylim_pad: float = 1.4,
    ) -> None:
        import matplotlib.pyplot as plt

        self.panel = panel
        self._n = n_curve_points
        self._history_window = history_window
        self._history: list[tuple[float, float]] = []

        self.fig, (self.ax_iv, self.ax_pv) = plt.subplots(1, 2, figsize=(11, 5))
        self.fig.suptitle("MPPT — running (close window to stop)")

        (self._iv_line,) = self.ax_iv.plot([], [], color="tab:blue", label="I-V curve")
        (self._pv_line,) = self.ax_pv.plot([], [], color="tab:orange", label="P-V curve")

        (self._traj_iv,) = self.ax_iv.plot(
            [], [], "-", color="tab:gray", alpha=0.45, label="trajectory"
        )
        (self._traj_pv,) = self.ax_pv.plot([], [], "-", color="tab:gray", alpha=0.45)

        (self._mpp_iv,) = self.ax_iv.plot(
            [], [], "o", color="tab:green", markersize=8, label="MPP"
        )
        (self._mpp_pv,) = self.ax_pv.plot(
            [], [], "o", color="tab:green", markersize=8, label="MPP"
        )

        (self._op_iv,) = self.ax_iv.plot(
            [], [], "s", color="tab:red", markersize=9, label="operating"
        )
        (self._op_pv,) = self.ax_pv.plot(
            [], [], "s", color="tab:red", markersize=9, label="operating"
        )

        self._readout_iv = self.ax_iv.text(
            0.02, 0.97, "", transform=self.ax_iv.transAxes,
            ha="left", va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7, edgecolor="none"),
        )
        self._readout_pv = self.ax_pv.text(
            0.02, 0.97, "", transform=self.ax_pv.transAxes,
            ha="left", va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7, edgecolor="none"),
        )

        for ax, ylabel, title, legend_loc in (
            (self.ax_iv, "I [A]", "I-V curve", "lower left"),
            (self.ax_pv, "P [W]", "P-V curve", "lower center"),
        ):
            ax.set_xlabel("V [V]")
            ax.set_ylabel(ylabel)
            ax.set_title(title)
            ax.grid(True, alpha=0.3)
            ax.legend(loc=legend_loc)

        self._set_static_limits(ylim_pad)
        self._refresh_curves()

    def _set_static_limits(self, pad: float) -> None:
        v, i = self.panel.iv_curve(self._n)
        p = v * i
        v_max = float(v[-1])
        i_max = float(np.max(i))
        p_max = float(np.max(p))
        self.ax_iv.set_xlim(0.0, v_max * 1.05)
        self.ax_iv.set_ylim(0.0, max(i_max * pad, 1e-6))
        self.ax_pv.set_xlim(0.0, v_max * 1.05)
        self.ax_pv.set_ylim(0.0, max(p_max * pad, 1e-6))

    def _refresh_curves(self) -> None:
        v, i = self.panel.iv_curve(self._n)
        p = v * i
        self._iv_line.set_data(v, i)
        self._pv_line.set_data(v, p)

        v_mpp, i_mpp, p_mpp = self.panel.mpp()
        self._mpp_iv.set_data([v_mpp], [i_mpp])
        self._mpp_pv.set_data([v_mpp], [p_mpp])
        self._mpp_text = (v_mpp, i_mpp, p_mpp)

    def update(self, operating_point: tuple[float, float]) -> None:
        v_op, i_op = operating_point
        self._history.append((v_op, i_op))
        if len(self._history) > self._history_window:
            del self._history[: len(self._history) - self._history_window]

        self._refresh_curves()

        h = np.asarray(self._history, dtype=float)
        self._traj_iv.set_data(h[:, 0], h[:, 1])
        self._traj_pv.set_data(h[:, 0], h[:, 0] * h[:, 1])

        self._op_iv.set_data([v_op], [i_op])
        self._op_pv.set_data([v_op], [v_op * i_op])

        v_mpp, i_mpp, p_mpp = self._mpp_text
        p_op = v_op * i_op
        eff = (p_op / p_mpp * 100.0) if p_mpp > 0 else 0.0
        self._readout_iv.set_text(
            f"MPP:  {v_mpp:5.2f} V  {i_mpp:5.2f} A\n"
            f"now:  {v_op:5.2f} V  {i_op:5.2f} A"
        )
        self._readout_pv.set_text(
            f"P_mpp: {p_mpp:6.2f} W\n"
            f"P_now: {p_op:6.2f} W  ({eff:5.1f}%)"
        )

    @property
    def history(self) -> list[tuple[float, float]]:
        return list(self._history)
