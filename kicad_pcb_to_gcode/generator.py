"""G-code generator for KiCad PCB milling, copper clearing, drilling, and cutting."""

import datetime


def generate_gcode_header(title, layer_name, origin_desc, settings, include_z_probe=False):
    """Generate standardized G-code header with machine configuration and optional Z-probe."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_z = float(settings.get("drill_safe_z", 3.0))
    lines = [
        "( ========================================================== )",
        f"( {title} )",
        f"( Generated: {now_str} )",
        f"( Layer:     {layer_name} )",
        f"( Origin:    {origin_desc} )",
        "( Units:     Millimeters (G21) | Coordinate: Absolute (G90) )",
        "( ========================================================== )",
        "",
        "G21         (Set units to millimeters)",
        "G90         (Absolute distance mode)",
        "G17         (XY plane selection)",
        "G94         (Feedrate in mm/min)",
        "M5          (Ensure spindle is stopped)",
        f"G0 Z{safe_z:.3f} (Move to safe travel height)",
        "G0 X0.000 Y0.000",
    ]

    if include_z_probe and settings.get("gcode_z_probe", False):
        probe_feed = float(settings.get("gcode_probe_feed", 50.0))
        probe_offset = float(settings.get("gcode_probe_offset", 0.0))
        lines.extend([
            "",
            "( --- Automatic Z-Zero Touch Probe Sequence --- )",
            f"G38.2 Z-10.000 F{probe_feed:.1f} (Probe down to copper surface)",
            f"G92 Z{probe_offset:.3f} (Set Z zero accounting for probe thickness)",
            f"G0 Z{safe_z:.3f} (Retract to safe height after probing)",
        ])

    lines.append("")
    return lines


def generate_gcode_footer(settings):
    """Generate standardized G-code footer with safe parking and spindle stop."""
    end_z = float(settings.get("gcode_end_z", 25.0))
    lines = [
        "",
        "( --- Program End & Safe Parking --- )",
        f"G0 Z{end_z:.3f} (Retract to park height)",
        "G0 X0.000 Y0.000 (Return to origin)",
        "M5          (Spindle stop)",
        "M2          (Program end)",
    ]
    return "\n".join(lines)


def generate_drill_gcode(tool_groups, origin_desc, settings, is_single_group_file=False, all_holes=None):
    """
    Generate drilling G-code from grouped hole coordinates (with optional oblong slot milling).

    Parameters:
      tool_groups: [(diameter_mm, [(x, y), ...]), ...]
      origin_desc: Description string of origin
      settings: Configuration dict
      is_single_group_file: If True, header reflects dedicated single-tool file
      all_holes: Optional list of hole dicts to support oblong/oval slot milling
    """
    safe_z = float(settings.get("drill_safe_z", 3.0))
    drill_depth = float(settings.get("drill_depth", -1.8))
    feed_z = float(settings.get("drill_feed_z", 200.0))
    rpm = int(settings.get("drill_spindle_rpm", 10000))
    dwell = float(settings.get("drill_dwell", 2.0))
    peck_enabled = bool(settings.get("drill_peck_enabled", False))
    peck_depth = float(settings.get("drill_peck_depth", 0.6))
    toolchange_z = float(settings.get("drill_toolchange_z", 35.0))
    mill_slots = bool(settings.get("drill_mill_slots", True))

    slot_lookup = {}
    if all_holes and mill_slots:
        for h in all_holes:
            if h.get("is_slot") and h.get("slot_start") and h.get("slot_end"):
                slot_lookup[(round(h["x"], 4), round(h["y"], 4))] = (h["slot_start"], h["slot_end"])

    total_holes = sum(len(pts) for _, pts in tool_groups)
    summary_str = ", ".join(f"{len(pts)}x {d:.2f}mm" for d, pts in tool_groups)

    lines = generate_gcode_header(
        f"PCB Drilling G-code ({total_holes} holes: {summary_str})",
        "Drill (PTH, NPTH, Vias)",
        origin_desc,
        settings,
    )

    for group_idx, (diameter, points) in enumerate(tool_groups):
        if not points:
            continue

        lines.append("( ---------------------------------------------------------- )")
        lines.append(f"( Tool Section: {diameter:.3f} mm Drill Bit | {len(points)} Holes )")
        lines.append("( ---------------------------------------------------------- )")

        if len(tool_groups) > 1 and not is_single_group_file:
            lines.append("M5 (Spindle stop for tool change)")
            lines.append(f"G0 Z{toolchange_z:.3f} (Raise to tool change height)")
            lines.append(f"M0 (Change bit to {diameter:.2f}mm drill - {len(points)} holes - then resume)")
            lines.append(f"M3 S{rpm} (Spindle restart)")
            lines.append(f"G4 P{dwell:.1f} (Dwell for spindle acceleration)")
            lines.append(f"G0 Z{safe_z:.3f}")
        else:
            lines.append(f"M3 S{rpm} (Start spindle)")
            lines.append(f"G4 P{dwell:.1f} (Dwell for spindle acceleration)")

        lines.append("")

        for idx, (x, y) in enumerate(points, 1):
            slot_pts = slot_lookup.get((round(x, 4), round(y, 4)))
            if slot_pts and slot_pts[0] != slot_pts[1]:
                (sx1, sy1), (sx2, sy2) = slot_pts
                lines.append(f"( Oblong Slot {idx}/{len(points)} @ ({sx1:.3f},{sy1:.3f}) -> ({sx2:.3f},{sy2:.3f}) )")
                lines.append(f"G0 X{sx1:.3f} Y{sy1:.3f}")
                step_z = peck_depth if (peck_enabled and peck_depth > 0) else abs(drill_depth)
                current_z = 0.0
                while current_z > drill_depth + 1e-4:
                    current_z -= max(0.2, step_z)
                    if current_z < drill_depth:
                        current_z = drill_depth
                    lines.append(f"G1 Z{current_z:.3f} F{feed_z:.1f}")
                    lines.append(f"G1 X{sx2:.3f} Y{sy2:.3f} F{feed_z:.1f}")
                    lines.append(f"G1 X{sx1:.3f} Y{sy1:.3f} F{feed_z:.1f}")
                lines.append(f"G0 Z{safe_z:.3f}")
                continue

            lines.append(f"( Hole {idx}/{len(points)} @ X={x:.3f}, Y={y:.3f} )")
            lines.append(f"G0 X{x:.3f} Y{y:.3f}")

            if peck_enabled and peck_depth > 0:
                current_z = 0.0
                while current_z > drill_depth + 1e-4:
                    current_z -= peck_depth
                    if current_z < drill_depth:
                        current_z = drill_depth
                    lines.append(f"G1 Z{current_z:.3f} F{feed_z:.1f}")
                    lines.append(f"G0 Z{safe_z:.3f}")
                    if current_z > drill_depth + 1e-4:
                        lines.append(f"G0 Z{current_z + 0.3:.3f}")
            else:
                lines.append(f"G1 Z{drill_depth:.3f} F{feed_z:.1f}")
                lines.append(f"G0 Z{safe_z:.3f}")

        lines.append("")

    lines.append(generate_gcode_footer(settings))
    return "\n".join(lines)


def generate_cutout_gcode(outer_loops, inner_loops, origin_desc, settings):
    """
    Generate board cutout G-code with multipass stepdown and optional holding tabs.
    """
    from .geometry import slice_path_with_tabs

    safe_z = float(settings.get("drill_safe_z", 3.0))
    cut_depth = float(settings.get("cutout_depth", -1.8))
    pass_depth = float(settings.get("cutout_pass_depth", 0.5))
    feed_xy = float(settings.get("cutout_feed_xy", 400.0))
    feed_z = float(settings.get("cutout_feed_z", 150.0))
    rpm = int(settings.get("cutout_spindle_rpm", 12000))
    dwell = float(settings.get("drill_dwell", 2.0))
    tool_dia = float(settings.get("cutout_tool_diameter", 2.0))
    tabs_enabled = bool(settings.get("cutout_tabs_enabled", True))
    tab_count = int(settings.get("cutout_tab_count", 4))
    tab_width = float(settings.get("cutout_tab_width", 2.5))
    tab_height = float(settings.get("cutout_tab_height", 0.6))

    lines = generate_gcode_header(
        f"Board Cutout G-code (Tool: {tool_dia:.2f}mm endmill)",
        "Edge.Cuts (Board Outline)",
        origin_desc,
        settings,
    )

    lines.append(f"M3 S{rpm} (Start spindle)")
    lines.append(f"G4 P{dwell:.1f} (Dwell for spindle acceleration)")
    lines.append("")

    depth_passes = []
    z = 0.0
    while z > cut_depth + 1e-4:
        z -= pass_depth
        if z < cut_depth:
            z = cut_depth
        depth_passes.append(round(z, 4))

    if inner_loops:
        lines.append("( --- Internal Cutouts & Slots --- )")
        for loop_idx, loop in enumerate(inner_loops, 1):
            lines.append(f"( Internal Cutout {loop_idx} )")
            x0, y0 = loop[0]
            lines.append(f"G0 X{x0:.3f} Y{y0:.3f}")
            for z_pass in depth_passes:
                lines.append(f"G1 Z{z_pass:.3f} F{feed_z:.1f}")
                for pt in loop[1:]:
                    lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{feed_xy:.1f}")
            lines.append(f"G0 Z{safe_z:.3f}")
            lines.append("")

    lines.append("( --- Outer Board Perimeter --- )")
    tab_threshold = cut_depth + tab_height

    for loop_idx, loop in enumerate(outer_loops, 1):
        if not tabs_enabled or tab_count <= 0:
            x0, y0 = loop[0]
            lines.append(f"G0 X{x0:.3f} Y{y0:.3f}")
            for z_pass in depth_passes:
                lines.append(f"G1 Z{z_pass:.3f} F{feed_z:.1f}")
                for pt in loop[1:]:
                    lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{feed_xy:.1f}")
            lines.append(f"G0 Z{safe_z:.3f}")
        else:
            segments = slice_path_with_tabs(loop, tab_count, tab_width)
            for z_pass in depth_passes:
                if z_pass >= tab_threshold:
                    x0, y0 = loop[0]
                    lines.append(f"G0 X{x0:.3f} Y{y0:.3f}")
                    lines.append(f"G1 Z{z_pass:.3f} F{feed_z:.1f}")
                    for pt in loop[1:]:
                        lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{feed_xy:.1f}")
                    lines.append(f"G0 Z{safe_z:.3f}")
                else:
                    lines.append(f"( Pass @ Z={z_pass:.3f} with {len(segments)} holding tabs )")
                    for seg_idx, seg in enumerate(segments, 1):
                        x0, y0 = seg[0]
                        lines.append(f"G0 X{x0:.3f} Y{y0:.3f}")
                        lines.append(f"G1 Z{z_pass:.3f} F{feed_z:.1f}")
                        for pt in seg[1:]:
                            lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{feed_xy:.1f}")
                        lines.append(f"G0 Z{safe_z:.3f}")

        lines.append("")

    lines.append(generate_gcode_footer(settings))
    return "\n".join(lines)


def _emit_contour_loops(lines, loops, z_passes, feed_xy, feed_z, safe_z, section_label="Contour"):
    """Helper to emit G-code lines for a list of closed 2D loops across Z stepdowns."""
    for idx, loop in enumerate(loops, 1):
        if len(loop) < 2:
            continue
        x0, y0 = loop[0]
        lines.append(f"( {section_label} {idx}/{len(loops)} )")
        lines.append(f"G0 X{x0:.3f} Y{y0:.3f}")
        for z_val in z_passes:
            lines.append(f"G1 Z{z_val:.3f} F{feed_z:.1f}")
            for pt in loop[1:]:
                lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{feed_xy:.1f}")
        lines.append(f"G0 Z{safe_z:.3f}")


def generate_copper_isolation_gcode(loops, layer_name, origin_desc, settings, clearing_loops=None):
    """
    Generate copper isolation milling and (optionally) full excess copper clearing G-code.
    """
    safe_z = float(settings.get("drill_safe_z", 3.0))
    iso_depth = float(settings.get("iso_depth", -0.05))
    z_step = float(settings.get("iso_z_step_mm", 0.0))
    feed_xy = float(settings.get("iso_feed_xy", 300.0))
    feed_z = float(settings.get("iso_feed_z", 100.0))
    rpm = int(settings.get("iso_spindle_rpm", 12000))
    dwell = float(settings.get("drill_dwell", 2.0))
    tool_dia = float(settings.get("iso_tool_diameter", 0.2))
    iso_mode = settings.get("iso_mode", "single")

    z_passes = []
    if z_step > 1e-4 and abs(iso_depth) > z_step:
        z_cur = 0.0
        while z_cur > iso_depth + 1e-4:
            z_cur -= z_step
            if z_cur < iso_depth:
                z_cur = iso_depth
            z_passes.append(round(z_cur, 4))
    else:
        z_passes = [round(iso_depth, 4)]

    mode_label = {
        "single": "Single-Pass Isolation",
        "multipass": f"Multi-Pass Isolation ({settings.get('iso_clearance_mm', tool_dia):.2f}mm Spacing)",
        "full_clear": "Full Copper Clearing (Leave Only Lines)",
    }.get(iso_mode, "Copper Isolation")

    lines = generate_gcode_header(
        f"Copper Milling G-code — {mode_label} (Tool: {tool_dia:.2f}mm)",
        layer_name,
        origin_desc,
        settings,
        include_z_probe=True,
    )

    lines.append(f"M3 S{rpm} (Start spindle)")
    lines.append(f"G4 P{dwell:.1f} (Dwell for spindle acceleration)")
    lines.append("")

    if loops:
        lines.append("( ========================================================== )")
        lines.append(f"( Phase 1: Precision Trace & Pad Isolation ({len(loops)} Contours) )")
        lines.append("( ========================================================== )")
        _emit_contour_loops(lines, loops, z_passes, feed_xy, feed_z, safe_z, section_label="Iso Contour")
        lines.append("")

    if clearing_loops:
        use_sep_tool = bool(settings.get("iso_use_separate_clear_tool", False))
        clear_dia = float(settings.get("iso_clear_tool_diameter", 0.8)) if use_sep_tool else tool_dia
        clear_feed = float(settings.get("iso_clear_feed_xy", 450.0)) if use_sep_tool else feed_xy
        toolchange_z = float(settings.get("drill_toolchange_z", 35.0))

        lines.append("( ========================================================== )")
        lines.append(f"( Phase 2: Full Excess Copper Removal / Rubout ({len(clearing_loops)} Contours) )")
        lines.append(f"( Clearing Tool: {clear_dia:.2f} mm | Feedrate: {clear_feed:.1f} mm/min )")
        lines.append("( ========================================================== )")

        if use_sep_tool and loops:
            lines.append("M5 (Stop spindle for clearing bit change)")
            lines.append(f"G0 Z{toolchange_z:.3f} (Raise to tool change height)")
            lines.append(f"M0 (Change bit to {clear_dia:.2f}mm Flat Clearing Endmill - then resume)")
            lines.append(f"M3 S{rpm} (Spindle restart)")
            lines.append(f"G4 P{dwell:.1f} (Dwell for spindle acceleration)")
            lines.append(f"G0 Z{safe_z:.3f}")
            lines.append("")

        _emit_contour_loops(lines, clearing_loops, z_passes, clear_feed, feed_z, safe_z, section_label="Rubout Pass")
        lines.append("")

    lines.append(generate_gcode_footer(settings))
    return "\n".join(lines)
