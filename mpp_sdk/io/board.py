"""Board facts shared by the SDK and the scripts. No `spidev` dependency,
so the curve-tracer server can use it without the hardware extra."""

from pathlib import Path

# Hard ceilings for the Pico's dynamic configuration. They match the
# firmware constants of the same name (firmware/pipico_board/src/main.rs).
# The firmware clamps a larger value and refuses 0, which used to turn the
# cutoff off, so a host can only make the cutoffs tighter.
CUTOFF_I_MAX_CEILING_MA = 1000
CUTOFF_V_MAX_CEILING_MV = 40000
PSU_VOUT_TARGET_CEILING_MV = 25000


def default_spi_bus() -> int:
    """SPI1 on a BeagleBone Black (its header wires SPI1 to the Pico), SPI0
    everywhere else. Checks the board model, not which spidev nodes exist:
    a BBB with the SPI0 overlay also has /dev/spidev0.0."""
    try:
        model = Path("/proc/device-tree/model").read_text(errors="replace")
    except OSError:
        return 0
    return 1 if "BeagleBone" in model else 0
