"""Ideal SEPIC converter, continuous-conduction-mode."""


class SEPICConverter:
    r"""Ideal CCM SEPIC (Single-Ended Primary-Inductor Converter).

    A SEPIC is a buck-boost topology built from two inductors, a
    coupling capacitor, and a single switch. We use it instead of a
    plain boost because panel `V_mpp` can sit on either side of the
    battery / load voltage, and a SEPIC tracks both regimes from a
    single duty cycle without polarity inversion or extra switches.

    Steady-state CCM relations (lossless, no on-resistance, no
    inductor DCR, no diode drop):

        V_out / V_in = D / (1 - D)
        I_out / I_in = (1 - D) / D

    so the resistance the panel sees through the converter is

        R_in = V_in / I_in = R_load * ((1 - D) / D)^2

    with `D = 0.5` as the unity point (`R_in == R_load`,
    `V_out == V_in`); `D < 0.5` is the buck regime, `D > 0.5` the
    boost regime. Like the plain boost, *increasing D decreases the
    panel terminal voltage*, so the P&O sign convention used by the
    SDK's algorithms is unchanged.

    These are idealisations. Real-hardware deviations (switching and
    conduction losses, ripple, sub-CCM operation at light load) will
    be added when the demonstrator is wired and we have measurements
    to fit against.
    """

    def __init__(self, min_duty: float = 0.05, max_duty: float = 0.95) -> None:
        if not 0.0 < min_duty < max_duty < 1.0:
            raise ValueError(f"need 0 < min_duty < max_duty < 1; got {min_duty=}, {max_duty=}")
        self.min_duty = min_duty
        self.max_duty = max_duty

    def clamp(self, duty: float) -> float:
        return float(min(max(duty, self.min_duty), self.max_duty))

    def reflected_resistance(self, duty: float, load_resistance: float) -> float:
        d = self.clamp(duty)
        ratio = (1.0 - d) / d
        return ratio * ratio * load_resistance
