"""On-disk library of panel models: the label values (Voc, Isc, Vmp, Imp,
Pmax) an operator would otherwise retype every bench session.

from mpp_sdk.panels import PanelModelRecord
from mpp_sdk.panels import library as panel_library
from mpp_sdk.panels import list_default_panels
"""

from .defaults import list_default_panels
from .library import (
    create,
    default_dir,
    delete,
    ensure_defaults_seeded,
    load,
    load_all,
    save,
    update,
)
from .record import PanelModelRecord

__all__ = [
    "PanelModelRecord",
    "default_dir",
    "create",
    "save",
    "load",
    "load_all",
    "update",
    "delete",
    "ensure_defaults_seeded",
    "list_default_panels",
]
