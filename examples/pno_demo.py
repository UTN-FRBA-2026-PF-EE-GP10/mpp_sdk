"""P&O quickstart — canonical body lives in main.py. Run either one."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "main.py"), run_name="__main__")
