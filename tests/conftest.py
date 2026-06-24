from __future__ import annotations

import os
import tempfile
from pathlib import Path


_DATA_CONFIG_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault(
    "GAPSIM_DATA_CONFIG",
    str(Path(_DATA_CONFIG_TMP.name) / "data_root.json"),
)
