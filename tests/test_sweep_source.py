"""Runtime Protocol-presence tests: both curve-tracer sources expose the
members named by `mpp_sdk.io.sweep_source.SweepSource`. These checks catch
removed or renamed methods before `_poll_loop` encounters them. Python's
runtime Protocol checks do not validate parameter or return annotations;
that stronger enforcement requires a future static type-check gate.

`spidev` is a real Linux-only C-backed module and isn't installed in the
base dev environment (it's the optional ``[hardware]`` extra) - a minimal
fake is injected into ``sys.modules`` before importing
``mpp_sdk.io.spi_mcu``, same technique as ``tests/test_spi_mcu.py``.
"""

import sys
import types

from mpp_sdk.io.sweep_source import SweepProgressLike, SweepSource


class _FakeSpiDev:
    def open(self, bus: int, device: int) -> None:
        pass

    max_speed_hz: int | None = None
    mode: int | None = None

    def xfer2(self, tx: list[int]) -> list[int]:
        return [0] * 12

    def close(self) -> None:
        pass


def _make_spi_mcu_source():
    fake_module = types.ModuleType("spidev")
    fake_module.SpiDev = _FakeSpiDev
    sys.modules["spidev"] = fake_module
    sys.modules.pop("mpp_sdk.io.spi_mcu", None)

    from mpp_sdk.io.spi_mcu import SpiMcuSource

    return SpiMcuSource(bus=0, device=0)


def test_spi_mcu_source_satisfies_sweep_source():
    source = _make_spi_mcu_source()
    assert isinstance(source, SweepSource)


def test_demo_sweep_source_satisfies_sweep_source():
    from scripts.curve_tracer_demo_source import DemoSweepSource

    assert isinstance(DemoSweepSource(), SweepSource)


def test_sweep_progress_satisfies_sweep_progress_like():
    from mpp_sdk.io.spi_mcu import SweepProgress

    progress = SweepProgress(index=0, voltage=1.0, current=0.1, active=True, final_point=False)
    assert isinstance(progress, SweepProgressLike)


def test_demo_progress_satisfies_sweep_progress_like():
    from scripts.curve_tracer_demo_source import _DemoProgress

    progress = _DemoProgress(index=0, voltage=1.0, current=0.1, active=True, final_point=False)
    assert isinstance(progress, SweepProgressLike)
