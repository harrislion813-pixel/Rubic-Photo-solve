from __future__ import annotations

import sys
from pathlib import Path


def application_root() -> Path:
    """Return the writable application directory in source and frozen builds."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]
