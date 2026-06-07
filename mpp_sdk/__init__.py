"""mpp-sdk — solar-panel MPPT algorithm SDK.

The top-level package re-exports the most commonly used symbols. Subpackages
also expose them, so either of these is fine:

    from mpp_sdk import IdealSingleDiode, PerturbAndObserve
    from mpp_sdk.models import IdealSingleDiode
    from mpp_sdk.algorithms import PerturbAndObserve
"""

from . import metrics
from .algorithms.base import MPPTAlgorithm
from .algorithms.fuzzy import FuzzyLogic
from .algorithms.incremental_conductance import IncrementalConductance
from .algorithms.perturb_observe import PerturbAndObserve
from .algorithms.scan_and_track import ScanAndTrack
from .converters.sepic import SEPICConverter
from .io.base import SignalSource
from .io.dynamic import DynamicSimulatedSource
from .io.simulated import SimulatedSource
from .models.base import PanelModel
from .models.ideal import IdealSingleDiode
from .models.pvlib_adapter import PvlibPanelModel
from .models.string import PvString
from .models.tabulated import TabulatedPanel
from .visualization import LivePanelView, plot_iv_with_operating_point

__version__ = "0.1.0"

__all__ = [
    "MPPTAlgorithm",
    "FuzzyLogic",
    "IncrementalConductance",
    "PerturbAndObserve",
    "ScanAndTrack",
    "SEPICConverter",
    "SignalSource",
    "SimulatedSource",
    "DynamicSimulatedSource",
    "PanelModel",
    "IdealSingleDiode",
    "PvlibPanelModel",
    "PvString",
    "TabulatedPanel",
    "LivePanelView",
    "plot_iv_with_operating_point",
    "metrics",
    "__version__",
]
