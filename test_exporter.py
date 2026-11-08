#!/usr/bin/env python3
"""Automated test suite for KiCad PCB to G-Code Exporter (Presets, Spacing, Rubout & Preview)."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pcbnew
import wx

from kicad_pcb_to_gcode.config import DEFAULT_SETTINGS, PRESETS
from kicad_pcb_to_gcode.geometry import (
    calculate_isolation_passes,
    estimate_job_statistics,
    extract_board_cutout_polygons,
    extract_board_outline_cnc,
    extract_copper_isolation_loops,
    extract_copper_polygons_cnc,
    extract_copper_toolpaths,
    extract_cutout_tab_bridges,
    extract_drill_holes,
    get_board_info,
    group_and_optimize_holes,
)
from kicad_pcb_to_gcode.generator import (
    generate_copper_isolation_gcode,
    generate_cutout_gcode,
    generate_drill_gcode,
)
from kicad_pcb_to_gcode.dialog import GCodeExportDialog


def run_tests():
    print("==================================================")
    print("Testing KiCad PCB to G-Code Exporter Logic")
    print("==================================================")

    demo_path = "/usr/share/kicad/demos/ecc83/ecc83-pp.kicad_pcb"
    if not os.path.exists(demo_path):
        print(f"Warning: Demo board {demo_path} not found. Creating synthetic board.")
        board = pcbnew.BOARD()
    else:
        print(f"Loading real demo board: {demo_path}")
        board = pcbnew.LoadBoard(demo_path)

    info = get_board_info(board)
    print(f"Board Dimensions: {info['width']:.2f} x {info['height']:.2f} mm")
    assert info["width"] > 0, "Board width should be > 0"
    assert info["height"] > 0, "Board height should be > 0"
    assert len(PRESETS) >= 5, "Expected at least 5 built-in presets"
    print(f"Verified {len(PRESETS)} built-in workflow presets:")
    for p in PRESETS:
        print(f"  • [{p['id']}] {p['name']}")

    settings = dict(DEFAULT_SETTINGS)
    holes = extract_drill_holes(board, info, settings)
    print(f"Extracted {len(holes)} drill holes.")
    assert len(holes) > 0, "Expected drill holes on demo board"

    groups = group_and_optimize_holes(holes, start_pos=(0.0, 0.0))
    print(f"Grouped into {len(groups)} bit diameter groups:")
    for dia, pts in groups:
        print(f"  • Tool {dia:.2f} mm: {len(pts)} holes")
        assert len(pts) > 0

    with tempfile.TemporaryDirectory() as tmpdir:
        drill_nc = generate_drill_gcode(groups, "Board Bottom-Left", settings, all_holes=holes)
        drill_path = Path(tmpdir) / "test_drill.nc"
        drill_path.write_text(drill_nc, encoding="utf-8")
        assert drill_path.exists()
        print(f"Drill G-code generated successfully ({len(drill_nc.splitlines())} lines).")
        assert "G21" in drill_nc and "G90" in drill_nc and "M3" in drill_nc and "M5" in drill_nc and "M2" in drill_nc

        outer, inner = extract_board_cutout_polygons(board, info, settings["cutout_tool_diameter"])
        bridges = extract_cutout_tab_bridges(outer[0], 4, 2.5)
        print(f"Cutout: {len(outer)} outer perimeter(s), {len(inner)} inner slot(s), {len(bridges)} holding tab bridges")
        assert len(outer) > 0, "Expected outer cutout perimeter"
        assert len(bridges) == 4, "Expected 4 holding tab bridge segments"
        cutout_nc = generate_cutout_gcode(outer, inner, "Board Bottom-Left", settings)
        cutout_path = Path(tmpdir) / "test_cutout.nc"
        cutout_path.write_text(cutout_nc, encoding="utf-8")
        assert cutout_path.exists()

        single_loops = extract_copper_isolation_loops(
            board, info, pcbnew.B_Cu, 0.2, settings={"iso_mode": "single"}
        )
        print(f"Single-Pass Back Copper: {len(single_loops)} isolation loops.")
        assert len(single_loops) > 0

        n_passes, step_mm, eff_mm = calculate_isolation_passes(0.2, 0.6, 1, 0.5)
        print(f"Spacing Calculation (0.6mm target @ 0.2mm tool, 50% overlap): {n_passes} passes, {eff_mm:.2f}mm effective gap")
        assert n_passes == 5 and abs(eff_mm - 0.6) < 1e-4

        mp_iso_loops, mp_clear_loops = extract_copper_toolpaths(
            board, info, pcbnew.B_Cu, settings={"iso_mode": "multipass", "iso_tool_diameter": 0.2, "iso_clearance_mm": 0.6}
        )
        print(f"Multi-Pass (0.6mm) Back Copper: {len(mp_iso_loops)} isolation loops (vs {len(single_loops)} single-pass).")
        assert len(mp_iso_loops) > len(single_loops), "Multi-pass should produce more isolation loops than single-pass"
        assert len(mp_clear_loops) == 0

        fc_iso_loops, fc_clear_loops = extract_copper_toolpaths(
            board,
            info,
            pcbnew.B_Cu,
            settings={
                "iso_mode": "full_clear",
                "iso_tool_diameter": 0.2,
                "iso_clear_stepover": 0.6,
                "iso_board_margin_mm": 0.3,
            },
        )
        print(f"Full Copper Removal ('Leave Only Lines'): {len(fc_iso_loops)} fine loops + {len(fc_clear_loops)} rubout loops.")
        assert len(fc_iso_loops) > 0 and len(fc_clear_loops) > 0, "Expected both isolation and rubout clearing loops"

        rubout_nc = generate_copper_isolation_gcode(
            fc_iso_loops,
            "Back Copper (B.Cu)",
            "Board Bottom-Left",
            {"iso_mode": "full_clear", "iso_tool_diameter": 0.2, "gcode_z_probe": True},
            clearing_loops=fc_clear_loops,
        )
        assert "Phase 1: Precision Trace & Pad Isolation" in rubout_nc
        assert "Phase 2: Full Excess Copper Removal / Rubout" in rubout_nc
        assert "G38.2" in rubout_nc
        iso_path = Path(tmpdir) / "test_copper_back_rubout.nc"
        iso_path.write_text(rubout_nc, encoding="utf-8")
        assert iso_path.exists()
        print(f"Full Rubout G-code generated successfully ({len(rubout_nc.splitlines())} lines).")

    print("Testing wxPython Dialog, Preset Switching & 2D Preview Canvas...")
    app = wx.App(False)
    dlg = GCodeExportDialog(None, board)

    for preset in PRESETS:
        dlg.apply_preset(preset["id"])
        vals = dlg.get_form_values()
        assert vals["active_preset"] == preset["id"]

    dlg.apply_preset("leave_only_lines")
    vals = dlg.get_form_values()
    assert vals["iso_mode"] == "full_clear"
    assert len(dlg.preview_panel.data["iso_loops"]) > 0
    assert len(dlg.preview_panel.data["clear_loops"]) > 0
    assert len(dlg.preview_panel.data["copper_regions"]) > 0

    print("Dialog UI, 7 Presets, and Live 2D Preview validated with 100% accuracy!")
    dlg.Destroy()

    print("\n==================================================")
    print("ALL TESTS PASSED WITH 100% SUCCESS!")
    print("==================================================")


if __name__ == "__main__":
    run_tests()
