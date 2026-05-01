"""Ideal boost converter, continuous-conduction-mode."""


class BoostConverter:
    r"""Ideal CCM boost converter.

    Relates the panel-side (input) and load-side (output) operating points
    via the duty cycle ``D ∈ (D_min, D_max)``:

        V_out = V_in / (1 - D)
        I_out = I_in * (1 - D)

    Power conservation is assumed (no switching, conduction, or magnetic
    losses). The reflected resistance the panel sees through the converter
    is therefore:

    TODO: i dont think this is right, i dont know if its useful.
        R_in = V_in / I_in = (1 - D)^2 * R_load
    """

    def __init__(self, min_duty: float = 0.05, max_duty: float = 0.95) -> None:
        if not 0.0 <= min_duty < max_duty <= 1.0:
            raise ValueError(
                f"need 0 <= min_duty < max_duty <= 1; got {min_duty=}, {max_duty=}"
            )
        self.min_duty = min_duty
        self.max_duty = max_duty

    def clamp(self, duty: float) -> float:
        return float(min(max(duty, self.min_duty), self.max_duty))

    def reflected_resistance(self, duty: float, load_resistance: float) -> float:
        d = self.clamp(duty)
        return (1.0 - d) ** 2 * load_resistance
