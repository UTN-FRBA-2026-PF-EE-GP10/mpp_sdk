"""Quickstart: Perturb & Observe MPPT against an ideal single-diode panel.

The simulation runs indefinitely (close the plot window or hit Ctrl-C to
stop). The panel's photocurrent drifts slowly to imitate changing irradiance
so the MPP moves and you can see the algorithm chasing it. For more demos,
see ``examples/``.
"""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation

from mpp_sdk import (
    IdealSingleDiode,
    LivePanelView,
    PerturbAndObserve,
    SEPICConverter,
    SimulatedSource,
)


def main() -> None:
    panel = IdealSingleDiode()
    converter = SEPICConverter()
    source = SimulatedSource(
        panel=panel,
        converter=converter,
        load_resistance=10.0,
        initial_duty=0.1,
    )
    controller = PerturbAndObserve(initial_duty=source.duty, step_size=0.005)

    view = LivePanelView(panel)
    base_photocurrent = panel.photocurrent

    def step(frame: int):
        # Slow sinusoidal drift of the photocurrent (≈ irradiance proxy in
        # the ideal model). The MPP moves; P&O has to keep up. Replace this
        # block with a constant when richer temperature/irradiance models land.
        panel.photocurrent = base_photocurrent * (1.0 + 0.15 * np.sin(0.02 * frame))

        v, i = source.read()
        d = controller.step(v, i)
        source.write(d)
        view.update((v, i))

    # Hold the animation in a name so it isn't garbage-collected mid-run.
    _ani = FuncAnimation(view.fig, step, interval=20, cache_frame_data=False)
    plt.show()


if __name__ == "__main__":
    main()
