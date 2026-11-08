"""Configuration management, presets, and default settings for KiCad PCB to G-Code Exporter."""

import json
import os
from pathlib import Path

CONFIG_FILENAME = "kicad_pcb_to_gcode.json"

DEFAULT_SETTINGS = {
    "active_preset": "good_isolation",
    "export_drill": True,
    "export_cutout": True,
    "export_front_copper": False,
    "export_back_copper": True,
    "origin_mode": "bottom_left",

    # Copper Milling Mode & Spacing
    # Options:
    #   "single"     - Single isolation pass around traces (fastest)
    #   "multipass"  - Multi-pass isolation with configurable spacing in mm
    #   "full_clear" - Remove 100% of remaining copper on board (Leave Only Lines)
    "iso_mode": "multipass",
    "iso_tool_diameter": 0.2,           # mm: V-bit tip or micro-endmill width
    "iso_clearance_mm": 0.6,            # mm: Target copper-free gap width around lines/pads
    "iso_passes": 5,                    # Minimum number of isolation passes
    "iso_pass_overlap": 0.5,            # Overlap ratio between passes (0.1 - 0.85, e.g. 0.5 = 50%)
    "iso_pad_extra_offset_mm": 0.0,     # mm: Extra copper annular ring margin around tracks/pads
    "iso_depth": -0.05,                 # mm: Engraving depth into copper
    "iso_z_step_mm": 0.0,               # mm: Optional Z stepdown per pass (0 = full depth at once)
    "iso_feed_xy": 300.0,               # mm/min: Milling feedrate
    "iso_feed_z": 100.0,                # mm/min: Plunge feedrate
    "iso_spindle_rpm": 12000,           # RPM: Spindle speed for milling
    "iso_mirror_bottom": True,          # Mirror X for bottom copper (B.Cu)
    "iso_clip_to_board": True,          # Clip wide isolation passes to stay inside Edge.Cuts
    "iso_climb_milling": False,         # Reverse contour direction for climb milling

    # Full Copper Removal ("Leave Only Lines" / Copper Rubout) Settings
    "iso_board_margin_mm": 0.3,         # mm: Safety inset from Edge.Cuts when clearing copper
    "iso_clear_stepover": 0.6,          # Stepover ratio for bulk copper clearing (0.3 - 0.9)
    "iso_use_separate_clear_tool": False,  # Use a larger flat endmill for fast bulk clearing
    "iso_clear_tool_diameter": 0.8,     # mm: Bulk clearing endmill diameter
    "iso_clear_feed_xy": 450.0,         # mm/min: Bulk clearing horizontal feedrate
    "iso_clear_separate_file": False,   # True = separate _clear.nc file, False = M0 pause in same file

    # Drill Settings
    "drill_safe_z": 3.0,                # mm: Safe Z travel height above board
    "drill_depth": -1.8,                # mm: Drill penetration depth (negative)
    "drill_feed_z": 200.0,              # mm/min: Plunge feedrate
    "drill_spindle_rpm": 10000,         # RPM: Spindle speed for drilling
    "drill_dwell": 2.0,                 # seconds: Dwell time after spindle start
    "drill_peck_enabled": False,        # Enable peck drilling
    "drill_peck_depth": 0.6,            # mm: Peck step increment
    "drill_include_pth": True,          # Include plated through holes (pads)
    "drill_include_npth": True,         # Include non-plated holes (mounting)
    "drill_include_vias": True,         # Include vias
    "drill_mill_slots": True,           # Mill oblong/oval pad slots along their length
    # Tool handling: "combined_pause", "separate_files", "single_tool"
    "drill_tool_mode": "combined_pause",
    "drill_single_diameter": 0.8,       # mm: Fallback single tool diameter
    "drill_toolchange_z": 35.0,         # mm: Z height for manual tool change

    # Board Cutout (Edge.Cuts)
    "cutout_tool_diameter": 2.0,        # mm: Endmill cutter diameter
    "cutout_depth": -1.8,               # mm: Total cutout depth through board
    "cutout_pass_depth": 0.5,           # mm: Max cut depth per pass
    "cutout_feed_xy": 400.0,            # mm/min: Horizontal cutting speed
    "cutout_feed_z": 150.0,             # mm/min: Vertical plunge speed
    "cutout_spindle_rpm": 12000,        # RPM: Spindle speed for cutout
    "cutout_tabs_enabled": True,        # Generate holding tabs / bridges
    "cutout_tab_count": 4,              # Number of holding tabs
    "cutout_tab_width": 2.5,            # mm: Width of each tab
    "cutout_tab_height": 0.6,           # mm: Thickness of remaining tab bridge

    # Machine / G-Code Dialect & Z-Probe
    "gcode_end_z": 25.0,                # mm: Final parking Z height
    "gcode_file_extension": ".nc",      # Output file extension (.nc, .gcode, .tap)
    "gcode_z_probe": False,             # Insert G38.2 Z touch-probe sequence before copper milling
    "gcode_probe_feed": 50.0,           # mm/min: Z-probe downward search feedrate
    "gcode_probe_offset": 0.0,          # mm: Touch plate thickness (0.0 for direct copper probing)
}


PRESETS = [
    {
        "id": "leave_only_lines",
        "name": "1. Leave Only Lines (Remove 100% Rest Copper)",
        "short_label": "Leave Only Lines",
        "description": (
            "Completely mills away ALL unused copper across the entire board, leaving ONLY your "
            "tracks and pads standing on bare FR4 fiberglass. Zero chance of accidental shorts!"
        ),
        "settings": {
            "export_back_copper": True,
            "export_drill": True,
            "export_cutout": True,
            "iso_mode": "full_clear",
            "iso_tool_diameter": 0.2,
            "iso_clearance_mm": 0.4,
            "iso_passes": 2,
            "iso_pass_overlap": 0.5,
            "iso_clear_stepover": 0.6,
            "iso_board_margin_mm": 0.3,
            "iso_use_separate_clear_tool": False,
            "iso_depth": -0.05,
            "iso_feed_xy": 350.0,
        },
    },
    {
        "id": "good_isolation",
        "name": "2. Good Isolation (0.6 mm Easy-Solder Spacing)",
        "short_label": "Good Isolation (0.6mm)",
        "description": (
            "Recommended for hand soldering: mills a generous 0.6 mm wide copper-free trench "
            "around every trace and pad (5 passes with 0.2 mm bit) so solder never bridges."
        ),
        "settings": {
            "export_back_copper": True,
            "export_drill": True,
            "export_cutout": True,
            "iso_mode": "multipass",
            "iso_tool_diameter": 0.2,
            "iso_clearance_mm": 0.6,
            "iso_passes": 5,
            "iso_pass_overlap": 0.5,
            "iso_use_separate_clear_tool": False,
            "iso_depth": -0.05,
            "iso_feed_xy": 300.0,
        },
    },
    {
        "id": "wide_isolation",
        "name": "3. Extra-Wide Isolation (1.2 mm High-Clearance Moat)",
        "short_label": "Wide Spacing (1.2mm)",
        "description": (
            "Creates a wide 1.2 mm copper-free moat around all lines and pads. Ideal for power "
            "electronics, high-voltage clearance, or super-easy beginner soldering."
        ),
        "settings": {
            "export_back_copper": True,
            "export_drill": True,
            "export_cutout": True,
            "iso_mode": "multipass",
            "iso_tool_diameter": 0.2,
            "iso_clearance_mm": 1.2,
            "iso_passes": 11,
            "iso_pass_overlap": 0.5,
            "iso_use_separate_clear_tool": False,
            "iso_depth": -0.05,
            "iso_feed_xy": 350.0,
        },
    },
    {
        "id": "fast_single_pass",
        "name": "4. Fast Standard Isolation (Single 0.2 mm Pass)",
        "short_label": "Fast 1-Pass",
        "description": (
            "Fastest machining time: performs a single 0.2 mm isolation pass around each trace and "
            "pad, plus drilling and board cutout."
        ),
        "settings": {
            "export_back_copper": True,
            "export_drill": True,
            "export_cutout": True,
            "iso_mode": "single",
            "iso_tool_diameter": 0.2,
            "iso_clearance_mm": 0.2,
            "iso_passes": 1,
            "iso_pass_overlap": 0.5,
            "iso_use_separate_clear_tool": False,
            "iso_depth": -0.05,
            "iso_feed_xy": 350.0,
        },
    },
    {
        "id": "two_tool_rubout",
        "name": "5. Fast 2-Tool Full Rubout (0.2 mm V-Bit + 0.8 mm Flat Endmill)",
        "short_label": "2-Tool Full Clear",
        "description": (
            "Best for removing all copper quickly: uses a 0.2 mm V-bit for crisp trace details, "
            "then switches to a 0.8 mm flat endmill to rapidly clear all remaining copper!"
        ),
        "settings": {
            "export_back_copper": True,
            "export_drill": True,
            "export_cutout": True,
            "iso_mode": "full_clear",
            "iso_tool_diameter": 0.2,
            "iso_clearance_mm": 0.4,
            "iso_passes": 2,
            "iso_pass_overlap": 0.5,
            "iso_use_separate_clear_tool": True,
            "iso_clear_tool_diameter": 0.8,
            "iso_clear_stepover": 0.65,
            "iso_clear_feed_xy": 500.0,
            "iso_depth": -0.05,
            "iso_feed_xy": 300.0,
        },
    },
    {
        "id": "fine_smd_precision",
        "name": "6. Fine-Pitch SMD Precision (0.1 mm V-Bit + Peck Drill)",
        "short_label": "Fine SMD (0.1mm)",
        "description": (
            "High-precision profile for dense SMD boards: 0.1 mm V-bit, shallow -0.04 mm depth, "
            "0.30 mm clearance (4 passes), gentle feedrates, and peck drilling for fragile bits."
        ),
        "settings": {
            "export_front_copper": True,
            "export_back_copper": True,
            "export_drill": True,
            "export_cutout": True,
            "iso_mode": "multipass",
            "iso_tool_diameter": 0.1,
            "iso_clearance_mm": 0.3,
            "iso_passes": 4,
            "iso_pass_overlap": 0.45,
            "iso_use_separate_clear_tool": False,
            "iso_depth": -0.04,
            "iso_feed_xy": 220.0,
            "iso_feed_z": 70.0,
            "iso_spindle_rpm": 15000,
            "drill_peck_enabled": True,
            "drill_peck_depth": 0.5,
        },
    },
    {
        "id": "drill_cutout_only",
        "name": "7. Drill & Cutout Only (For Etched / Pre-Made Boards)",
        "short_label": "Drill + Cutout Only",
        "description": (
            "Skips copper milling and only generates optimized drill holes (with peck cycle) and "
            "multi-pass board cutout with 4 holding tabs."
        ),
        "settings": {
            "export_front_copper": False,
            "export_back_copper": False,
            "export_drill": True,
            "export_cutout": True,
            "drill_peck_enabled": True,
            "drill_peck_depth": 0.6,
            "cutout_tabs_enabled": True,
            "cutout_tab_count": 4,
        },
    },
]


def get_preset_by_id(preset_id):
    """Look up preset definition by ID."""
    for preset in PRESETS:
        if preset["id"] == preset_id:
            return preset
    return None


def get_config_dir():
    """Return platform-appropriate configuration directory."""
    if os.name == "nt":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        config_dir = Path(base) / "kicad"
    else:
        config_dir = Path(os.path.expanduser("~/.config/kicad"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path():
    """Return path to saved settings file."""
    return get_config_dir() / CONFIG_FILENAME


def load_settings():
    """Load settings from disk, filling in missing keys with defaults."""
    settings = dict(DEFAULT_SETTINGS)
    path = get_config_path()
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    settings.update(saved)
        except Exception:
            pass
    return settings


def save_settings(settings):
    """Save settings dictionary to disk."""
    path = get_config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception:
        return False
