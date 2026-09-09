"""Shared curve-tracer sweep-control interface.

`_poll_loop` (`scripts/curve_tracer_server.py`) drives either a real
`SpiMcuSource` (`mpp_sdk.io.spi_mcu`, needs `spidev` + a board) or a
`DemoSweepSource` (`scripts/curve_tracer_demo_source.py`, stdlib only)
completely interchangeably - it only ever calls the four methods and the
context-manager protocol declared here. Neither class inherits from
`SweepSource`; `Protocol` conformance is structural, so this module exists
purely to make that already-relied-upon contract explicit and checkable,
not to add a base class either implementation must extend.

This module must stay dependency-free (stdlib `typing` only): both
`mpp_sdk.io.spi_mcu` (needs `spidev` at import time) and
`scripts/curve_tracer_demo_source.py` (deliberately stdlib-only, so `--demo`
mode needs neither a board nor `spidev`) must be able to reference this
module, or be checked against it, without pulling in the other's
dependencies.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SweepProgressLike(Protocol):
    """Structural shape of one in-progress-sweep update - satisfied by both
    `mpp_sdk.io.spi_mcu.SweepProgress` and
    `scripts.curve_tracer_demo_source._DemoProgress` without either
    inheriting from this class."""

    index: int
    voltage: float
    current: float
    active: bool
    final_point: bool


@runtime_checkable
class SweepSource(Protocol):
    """The exact subset of a curve-tracer source that `_poll_loop`
    (`scripts/curve_tracer_server.py`) uses - satisfied structurally by both
    `mpp_sdk.io.spi_mcu.SpiMcuSource` and
    `scripts.curve_tracer_demo_source.DemoSweepSource`.

    Deliberately narrower than `SpiMcuSource`'s full public API (e.g. it
    omits `request_sweep`'s `poll_attempts`/`poll_interval_s` parameters,
    which `_poll_loop` never passes) - this describes what the shared
    caller actually needs, not everything either implementation happens to
    offer.
    """

    def start_sweep(self) -> None: ...
    def release_relay(self) -> None: ...
    def request_sweep(self) -> list[tuple[float, float]] | None: ...
    def poll_sweep_progress(self) -> SweepProgressLike | None: ...
    def __enter__(self) -> SweepSource: ...
    def __exit__(self, *args: object) -> None: ...
