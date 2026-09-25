"""Launcher for ``final video-ids visualization.py`` (filename has spaces)."""

from __future__ import annotations

import runpy
from pathlib import Path

_target = Path(__file__).resolve().parent / "final video-ids visualization.py"
if not _target.is_file():
    raise FileNotFoundError(f"Missing app: {_target}")
runpy.run_path(str(_target), run_name="__main__")
