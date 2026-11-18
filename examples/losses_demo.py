"""Plot I-V and P-V curves of the ideal and the lossy single-diode models."""

import matplotlib.pyplot as plt

from mpp_sdk import IdealSingleDiode, SingleDiodeWithLosses

ideal = IdealSingleDiode()
lossy = SingleDiodeWithLosses(series_resistance=0.5, shunt_resistance=200.0)

fig, (ax_iv, ax_pv) = plt.subplots(1, 2, figsize=(10, 4))
for name, panel in (("ideal", ideal), ("R_s, R_sh losses", lossy)):
    v, i = panel.iv_curve()
    v_mp, _, p_mp = panel.mpp()
    ax_iv.plot(v, i, label=name)
    (line,) = ax_pv.plot(v, v * i, label=f"{name} (P_mpp = {p_mp:.1f} W)")
    ax_pv.plot(v_mp, p_mp, "o", color=line.get_color())
ax_iv.set(xlabel="V [V]", ylabel="I [A]", title="I-V")
ax_pv.set(xlabel="V [V]", ylabel="P [W]", title="P-V")
ax_iv.legend()
ax_pv.legend()
fig.tight_layout()
plt.show()
