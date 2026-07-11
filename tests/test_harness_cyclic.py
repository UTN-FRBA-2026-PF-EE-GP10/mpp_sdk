"""Characterization tests for harness/compare_cyclic.py profile machinery."""

import numpy as np
import pytest

pytest.importorskip("pvlib", reason="pvlib extra not installed")  # noqa: E402

from harness.compare_cyclic import (  # noqa: E402
    BAND,
    COLD_START_STEPS,
    LEVELS,
    N_SEGMENTS,
    RAMP_QUANTUM,
    _ramp_chunks,
    make_profile,
    plateau_spans,
    segment_stats,
)

# ------------------------------------------------------------------
# make_profile
# ------------------------------------------------------------------


def test_make_profile_deterministic():
    plateaus1, schedule1 = make_profile(seed=1)
    plateaus2, schedule2 = make_profile(seed=1)
    assert plateaus1 == plateaus2
    assert schedule1 == schedule2


def test_make_profile_seed_sensitivity():
    plateaus1, _ = make_profile(seed=1)
    plateaus2, _ = make_profile(seed=2)
    assert plateaus1 != plateaus2


def test_make_profile_cold_start():
    plateaus, _ = make_profile(seed=1)
    assert plateaus[0] == ("1000/1000", (1000.0, 1000.0), COLD_START_STEPS)


def test_make_profile_plateau_count():
    plateaus, _ = make_profile(seed=1)
    assert len(plateaus) == N_SEGMENTS


def test_make_profile_no_repeated_conditions():
    plateaus, _ = make_profile(seed=1)
    irrs = [irr for _, irr, _ in plateaus]
    for a, b in zip(irrs, irrs[1:], strict=False):
        assert a != b


def test_make_profile_vocabulary():
    plateaus, _ = make_profile(seed=1)
    vocabulary = set(LEVELS) | {1000.0}
    for _, irr, _ in plateaus:
        assert irr[0] in vocabulary
        assert irr[1] in vocabulary


def test_make_profile_schedule_consistency():
    plateaus, schedule = make_profile(seed=1)
    tagged = [entry for entry in schedule if entry[2] is not None]
    assert [entry[2] for entry in tagged] == list(range(N_SEGMENTS))
    for irr, n_steps, idx in tagged:
        assert (irr, n_steps) == plateaus[idx][1:]


# ------------------------------------------------------------------
# _ramp_chunks
# ------------------------------------------------------------------


def test_ramp_chunks_grid():
    chunks = _ramp_chunks((1000.0, 1000.0), (200.0, 400.0), 300)
    for pair, _, _ in chunks:
        for value in pair:
            assert value % RAMP_QUANTUM == 0


def test_ramp_chunks_step_conservation():
    n_steps = 300
    chunks = _ramp_chunks((1000.0, 1000.0), (200.0, 400.0), n_steps)
    assert sum(n for _, n, _ in chunks) == n_steps


def test_ramp_chunks_terminal_value():
    start, end = (1000.0, 1000.0), (200.0, 400.0)
    chunks = _ramp_chunks(start, end, 300)
    quantized_end = tuple(RAMP_QUANTUM * round(v / RAMP_QUANTUM) for v in end)
    assert chunks[-1][0] == quantized_end


def test_ramp_chunks_plateau_idx_is_none():
    chunks = _ramp_chunks((1000.0, 1000.0), (200.0, 400.0), 300)
    assert all(idx is None for _, _, idx in chunks)


def test_ramp_chunks_degenerate():
    start = (600.0, 600.0)
    chunks = _ramp_chunks(start, start, 42)
    assert chunks == [(start, 42, None)]


# ------------------------------------------------------------------
# plateau_spans
# ------------------------------------------------------------------


def test_plateau_spans_hand_built_schedule():
    schedule = [
        ((1000.0, 1000.0), 5, 0),
        ((900.0, 900.0), 3, None),
        ((800.0, 200.0), 7, 1),
    ]
    assert plateau_spans(schedule) == [
        (0, 5, (1000.0, 1000.0)),
        (8, 7, (800.0, 200.0)),
    ]


# ------------------------------------------------------------------
# segment_stats
# ------------------------------------------------------------------


def test_segment_stats_settled_from_the_start():
    conditions = {(1000.0, 1000.0): (None, 10.0)}
    spans = [(0, 200, (1000.0, 1000.0))]
    powers = np.full(200, 10.0)
    times, finals = segment_stats(powers, spans, conditions)
    assert times == [0.0]
    assert finals == [pytest.approx(1.0)]


def test_segment_stats_trapped_below_band():
    conditions = {(1000.0, 1000.0): (None, 10.0)}
    spans = [(0, 200, (1000.0, 1000.0))]
    powers = np.full(200, 5.0)
    assert 1.0 - BAND > 0.5  # sanity: 5.0/10.0 is genuinely below the band
    times, finals = segment_stats(powers, spans, conditions)
    assert times == [None]
    assert finals == [pytest.approx(0.5)]


def test_segment_stats_settles_partway_through():
    conditions = {(1000.0, 1000.0): (None, 10.0)}
    spans = [(0, 200, (1000.0, 1000.0))]
    powers = np.concatenate([np.full(100, 5.0), np.full(100, 10.0)])
    times, finals = segment_stats(powers, spans, conditions)
    assert times == [pytest.approx(100 * 1.0)]
    assert finals == [pytest.approx(1.0)]
