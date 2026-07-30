from __future__ import annotations

import sys
from pathlib import Path

_PIPELINE_SRC = Path(__file__).resolve().parents[1] / "src"
_DOMAIN_SRC = Path(__file__).resolve().parents[3] / "packages" / "domain" / "src"
_STORAGE_SRC = Path(__file__).resolve().parents[3] / "packages" / "storage" / "src"

for _candidate in (_PIPELINE_SRC, _DOMAIN_SRC, _STORAGE_SRC):
    _candidate_str = str(_candidate)
    if _candidate_str not in sys.path:
        sys.path.insert(0, _candidate_str)

del _candidate
del _candidate_str
del _PIPELINE_SRC
del _DOMAIN_SRC
del _STORAGE_SRC
