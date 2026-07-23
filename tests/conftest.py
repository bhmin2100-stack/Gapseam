from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_DATA_CONFIG_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault(
    "GAPSIM_DATA_CONFIG",
    str(Path(_DATA_CONFIG_TMP.name) / "data_root.json"),
)
