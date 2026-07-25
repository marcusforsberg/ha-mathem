"""Root pytest conftest.

Makes the vendored ``mathem_client`` package importable on a workstation
without installing Home Assistant. The client directory is *appended* to
``sys.path`` so sibling integration modules (``calendar.py``, ``sensor.py``,
...) cannot shadow standard-library modules of the same name.
"""

from __future__ import annotations

import os
import sys

_CLIENT_DIR = os.path.join(os.path.dirname(__file__), "custom_components", "mathem")
if _CLIENT_DIR not in sys.path:
    sys.path.append(_CLIENT_DIR)
