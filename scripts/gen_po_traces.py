"""Write the P&O cross-check fixtures for firmware/mppt-po.

Runs the Python reference on simulated sources, with V and I rounded to whole
mV and mA like the Pico ADC path. Duty values are u16 counts, so every number
is a dyadic fraction and the float reference matches the Rust integers exactly.

    uv run python scripts/gen_po_traces.py
"""

from __future__ import annotations

from pathlib import Path

from mpp_sdk.algorithms.perturb_observe import PerturbAndObserve
from mpp_sdk.converters.sepic import SEPICConverter
from mpp_sdk.io.simulated import SimulatedSource
from mpp_sdk.models.ideal import IdealSingleDiode

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "firmware" / "mppt-po" / "tests" / "fixtures"
SCALE = 65536
INITIAL, STEP, MIN, MAX = 32768, 66, 3277, 62258
STEPS = 600

# name -> (photocurrent in A, load in ohm)
CASES = {
    "full_sun": (8.0, 10.0),
    "half_sun": (4.0, 10.0),
    "low_sun_small_load": (1.0, 3.0),
}


def trace(photocurrent: float, load: float) -> list[tuple[int, int, int]]:
    source = SimulatedSource(
        IdealSingleDiode(photocurrent=photocurrent),
        SEPICConverter(min_duty=MIN / SCALE, max_duty=MAX / SCALE),
        load_resistance=load,
        initial_duty=INITIAL / SCALE,
    )
    algo = PerturbAndObserve(INITIAL / SCALE, STEP / SCALE, MIN / SCALE, MAX / SCALE)
    rows = []
    for _ in range(STEPS):
        v, i = source.read()
        v_mv, i_ma = round(v * 1000), round(i * 1000)
        duty = round(algo.step(float(v_mv), float(i_ma)) * SCALE)
        source.write(duty / SCALE)
        rows.append((v_mv, i_ma, duty))
    return rows


def render() -> dict[str, str]:
    out = {}
    for name, (iph, load) in CASES.items():
        lines = ["v_mv,i_ma,duty_u16"]
        lines += [f"{v},{i},{d}" for v, i, d in trace(iph, load)]
        out[f"po_{name}.csv"] = "\n".join(lines) + "\n"
    return out


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in render().items():
        (FIXTURE_DIR / name).write_text(text)
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
