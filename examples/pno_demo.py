"""Perturb & Observe MPPT against the ideal single-diode panel — live demo.

Run with::

    uv run examples/pno_demo.py

The simulation runs indefinitely (close the plot window or hit Ctrl-C to
stop). Photocurrent drifts on a slow sinusoid so the MPP moves and the
algorithm has something to chase. This is the same demo as ``main.py``;
``examples/`` is the home for future variants and algorithm comparisons.
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
        panel.photocurrent = base_photocurrent * (1.0 + 0.15 * np.sin(0.02 * frame))
        v, i = source.read()
        d = controller.step(v, i)
        source.write(d)
        view.update((v, i))

    _ani = FuncAnimation(view.fig, step, interval=20, cache_frame_data=False)
    plt.show()


if __name__ == "__main__":
    main()
