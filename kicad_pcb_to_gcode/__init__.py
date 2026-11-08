"""KiCad PCB to G-Code Plugin Package."""

import os
import sys

plugin_dir = os.path.dirname(os.path.abspath(__file__))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from .plugin import PcbToGCodePlugin

try:
    PcbToGCodePlugin().register()
except Exception:
    pass
