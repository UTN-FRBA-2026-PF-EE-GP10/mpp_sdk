"""mpp-sdk — solar-panel MPPT algorithm SDK.

The top-level package re-exports the most commonly used symbols. Subpackages
also expose them, so either of these is fine:

    from mpp_sdk import IdealSingleDiode, PerturbAndObserve
    from mpp_sdk.models import IdealSingleDiode
    from mpp_sdk.algorithms import PerturbAndObserve
"""

from .algorithms.base import MPPTAlgorithm
from .algorithms.perturb_observe import PerturbAndObserve
from .converters.sepic import SEPICConverter
from .io.base import SignalSource
from .io.simulated import SimulatedSource
from .models.base import PanelModel
from .models.ideal import IdealSingleDiode
from .visualization import LivePanelView, plot_iv_with_operating_point

__version__ = "0.1.0"

__all__ = [
    "MPPTAlgorithm",
    "PerturbAndObserve",
    "SEPICConverter",
    "SignalSource",
    "SimulatedSource",
    "PanelModel",
    "IdealSingleDiode",
    "LivePanelView",
    "plot_iv_with_operating_point",
    "__version__",
]
