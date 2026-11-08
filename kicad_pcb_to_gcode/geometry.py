"""Geometry extraction, multi-pass isolation, full copper clearing, and coordinate transformations."""

import math
import pcbnew


def get_board_info(board):
    """
    Extract board dimensions, bounding box, and origins from KiCad board.
    All dimensions returned in millimeters.
    """
    info = {
        "min_x": 0.0,
        "max_x": 0.0,
        "min_y": 0.0,
        "max_y": 0.0,
        "width": 0.0,
        "height": 0.0,
        "aux_x": 0.0,
        "aux_y": 0.0,
        "center_x": 0.0,
        "center_y": 0.0,
        "has_edges": False,
        "outline_count": 0,
    }

    poly = pcbnew.SHAPE_POLY_SET()
    has_outlines = False
    try:
        has_outlines = board.GetBoardPolygonOutlines(poly, True) and poly.OutlineCount() > 0
    except Exception:
        has_outlines = False

    if has_outlines:
        info["has_edges"] = True
        info["outline_count"] = poly.OutlineCount()
        all_x = []
        all_y = []
        for i in range(poly.OutlineCount()):
            outline = poly.Outline(i)
            for j in range(outline.PointCount()):
                pt = outline.CPoint(j)
                all_x.append(pcbnew.ToMM(pt.x))
                all_y.append(pcbnew.ToMM(pt.y))
        if all_x and all_y:
            info["min_x"] = min(all_x)
            info["max_x"] = max(all_x)
            info["min_y"] = min(all_y)
            info["max_y"] = max(all_y)
    else:
        bbox = board.GetBoardEdgesBoundingBox()
        if bbox.GetWidth() > 0 and bbox.GetHeight() > 0:
            info["has_edges"] = True
            info["min_x"] = pcbnew.ToMM(bbox.GetX())
            info["max_x"] = pcbnew.ToMM(bbox.GetRight())
            info["min_y"] = pcbnew.ToMM(bbox.GetY())
            info["max_y"] = pcbnew.ToMM(bbox.GetBottom())
        else:
            full_bbox = board.GetBoundingBox()
            if full_bbox.GetWidth() > 0 and full_bbox.GetHeight() > 0:
                info["min_x"] = pcbnew.ToMM(full_bbox.GetX())
                info["max_x"] = pcbnew.ToMM(full_bbox.GetRight())
                info["min_y"] = pcbnew.ToMM(full_bbox.GetY())
                info["max_y"] = pcbnew.ToMM(full_bbox.GetBottom())

    info["width"] = max(0.0, info["max_x"] - info["min_x"])
    info["height"] = max(0.0, info["max_y"] - info["min_y"])
    info["center_x"] = (info["min_x"] + info["max_x"]) / 2.0
    info["center_y"] = (info["min_y"] + info["max_y"]) / 2.0

    try:
        ds = board.GetDesignSettings()
        aux = ds.GetAuxOrigin()
        info["aux_x"] = pcbnew.ToMM(aux.x)
        info["aux_y"] = pcbnew.ToMM(aux.y)
    except Exception:
        info["aux_x"] = info["min_x"]
        info["aux_y"] = info["max_y"]

    return info


def kicad_to_cnc(x_mm, y_mm, board_info, origin_mode="bottom_left", mirror_x=False):
    """
    Convert KiCad coordinate (mm, Y downwards) to CNC coordinate (mm, Y upwards).

    Origin options:
      - 'bottom_left': (0,0) at board bottom-left corner (standard CNC practice)
      - 'aux_origin':  (0,0) at KiCad auxiliary / drill origin
      - 'center':      (0,0) at board center
      - 'top_left':    (0,0) at board top-left corner
    """
    min_x = board_info["min_x"]
    min_y = board_info["min_y"]
    max_y = board_info["max_y"]
    width = board_info["width"]

    if origin_mode == "bottom_left":
        cnc_x = x_mm - min_x
        cnc_y = max_y - y_mm
        if mirror_x:
            cnc_x = width - cnc_x
    elif origin_mode == "aux_origin":
        aux_x = board_info["aux_x"]
        aux_y = board_info["aux_y"]
        cnc_x = x_mm - aux_x
        cnc_y = aux_y - y_mm
        if mirror_x:
            cnc_x = -cnc_x
    elif origin_mode == "center":
        cx = board_info["center_x"]
        cy = board_info["center_y"]
        cnc_x = x_mm - cx
        cnc_y = cy - y_mm
        if mirror_x:
            cnc_x = -cnc_x
    else:
        cnc_x = x_mm - min_x
        cnc_y = min_y - y_mm
        if mirror_x:
            cnc_x = width - cnc_x

    return round(cnc_x, 4), round(cnc_y, 4)


def extract_drill_holes(board, board_info, settings):
    """
    Extract all drill holes (pads and vias) matching the settings.
    Returns list of dicts with coordinates, diameter, and optional oblong slot endpoints.
    """
    holes = []
    include_pth = settings.get("drill_include_pth", True)
    include_npth = settings.get("drill_include_npth", True)
    include_vias = settings.get("drill_include_vias", True)
    origin_mode = settings.get("origin_mode", "bottom_left")

    for fp in board.GetFootprints():
        for pad in fp.Pads():
            attr = pad.GetAttribute()
            is_pth = (attr == pcbnew.PAD_ATTRIB_PTH)
            is_npth = (attr == pcbnew.PAD_ATTRIB_NPTH)

            if is_pth and not include_pth:
                continue
            if is_npth and not include_npth:
                continue
            if not is_pth and not is_npth:
                continue

            drill_size = pad.GetDrillSize()
            dx = pcbnew.ToMM(drill_size.x)
            dy = pcbnew.ToMM(drill_size.y)
            if dx <= 0.0 and dy <= 0.0:
                continue

            is_oblong = (pad.GetDrillShape() == pcbnew.PAD_DRILL_SHAPE_OBLONG) or (abs(dx - dy) > 0.01)
            dia = min(dx, dy) if (is_oblong and min(dx, dy) > 0) else max(dx, dy)

            pos = pad.GetPosition()
            x_raw = pcbnew.ToMM(pos.x)
            y_raw = pcbnew.ToMM(pos.y)
            cnc_x, cnc_y = kicad_to_cnc(x_raw, y_raw, board_info, origin_mode, mirror_x=False)

            slot_x1, slot_y1 = cnc_x, cnc_y
            slot_x2, slot_y2 = cnc_x, cnc_y
            if is_oblong:
                try:
                    orient = pad.GetOrientation()
                    angle_deg = orient.AsDegrees() if hasattr(orient, "AsDegrees") else float(orient) / 10.0
                except Exception:
                    angle_deg = 0.0
                slot_len = max(0.0, max(dx, dy) - dia)
                half_len = slot_len / 2.0
                rad = math.radians(angle_deg)
                if dx >= dy:
                    kx1 = x_raw - half_len * math.cos(rad)
                    ky1 = y_raw + half_len * math.sin(rad)
                    kx2 = x_raw + half_len * math.cos(rad)
                    ky2 = y_raw - half_len * math.sin(rad)
                else:
                    kx1 = x_raw - half_len * math.sin(rad)
                    ky1 = y_raw - half_len * math.cos(rad)
                    kx2 = x_raw + half_len * math.sin(rad)
                    ky2 = y_raw + half_len * math.cos(rad)
                slot_x1, slot_y1 = kicad_to_cnc(kx1, ky1, board_info, origin_mode, mirror_x=False)
                slot_x2, slot_y2 = kicad_to_cnc(kx2, ky2, board_info, origin_mode, mirror_x=False)

            holes.append({
                "diameter": round(dia, 3),
                "x": cnc_x,
                "y": cnc_y,
                "type": "PTH" if is_pth else "NPTH",
                "is_slot": is_oblong,
                "slot_dx": round(dx, 3),
                "slot_dy": round(dy, 3),
                "slot_start": (slot_x1, slot_y1),
                "slot_end": (slot_x2, slot_y2),
            })

    if include_vias:
        for item in board.GetTracks():
            if isinstance(item, pcbnew.PCB_VIA) or (hasattr(pcbnew, "PCB_VIA_T") and item.Type() == pcbnew.PCB_VIA_T):
                drill_val = 0.0
                if hasattr(item, "GetDrillValue"):
                    drill_val = pcbnew.ToMM(item.GetDrillValue())
                elif hasattr(item, "GetDrill"):
                    drill_val = pcbnew.ToMM(item.GetDrill())

                if drill_val > 0.0:
                    pos = item.GetPosition()
                    x_raw = pcbnew.ToMM(pos.x)
                    y_raw = pcbnew.ToMM(pos.y)
                    cnc_x, cnc_y = kicad_to_cnc(x_raw, y_raw, board_info, origin_mode, mirror_x=False)
                    holes.append({
                        "diameter": round(drill_val, 3),
                        "x": cnc_x,
                        "y": cnc_y,
                        "type": "VIA",
                        "is_slot": False,
                        "slot_dx": round(drill_val, 3),
                        "slot_dy": round(drill_val, 3),
                        "slot_start": (cnc_x, cnc_y),
                        "slot_end": (cnc_x, cnc_y),
                    })

    return holes


def group_and_optimize_holes(holes, start_pos=(0.0, 0.0), single_diameter=None):
    """
    Group drill holes by diameter and optimize travel order using nearest-neighbor TSP.
    Returns:
      [(diameter_mm, [(x, y), ...]), ...]
    """
    if not holes:
        return []

    grouped = {}
    for h in holes:
        d = round(single_diameter, 3) if single_diameter is not None else h["diameter"]
        grouped.setdefault(d, []).append((h["x"], h["y"]))

    sorted_diameters = sorted(grouped.keys())
    optimized_groups = []
    current_pos = start_pos

    for d in sorted_diameters:
        points = list(grouped[d])
        ordered_points = []
        while points:
            best_idx = min(
                range(len(points)),
                key=lambda i: (points[i][0] - current_pos[0]) ** 2 + (points[i][1] - current_pos[1]) ** 2
            )
            pt = points.pop(best_idx)
            ordered_points.append(pt)
            current_pos = pt

        optimized_groups.append((d, ordered_points))

    return optimized_groups


def _get_board_outline_poly_set(board, board_info):
    """Return a SHAPE_POLY_SET of the board outline in KiCad internal units."""
    poly = pcbnew.SHAPE_POLY_SET()
    try:
        if board.GetBoardPolygonOutlines(poly, True) and poly.OutlineCount() > 0:
            return poly
    except Exception:
        pass

    if board_info["width"] > 0 and board_info["height"] > 0:
        min_x = pcbnew.FromMM(board_info["min_x"])
        max_x = pcbnew.FromMM(board_info["max_x"])
        min_y = pcbnew.FromMM(board_info["min_y"])
        max_y = pcbnew.FromMM(board_info["max_y"])
        poly.NewOutline()
        poly.Append(min_x, min_y)
        poly.Append(max_x, min_y)
        poly.Append(max_x, max_y)
        poly.Append(min_x, max_y)
    return poly


def extract_board_outline_cnc(board, board_info, origin_mode="bottom_left", mirror_x=False):
    """
    Extract exact (un-offset) board outline and internal cutouts in CNC coordinates for previewing.
    Returns (outer_loops, inner_loops).
    """
    poly = _get_board_outline_poly_set(board, board_info)
    outer_loops = []
    inner_loops = []
    for i in range(poly.OutlineCount()):
        outline = poly.Outline(i)
        pts = []
        for j in range(outline.PointCount()):
            pt = outline.CPoint(j)
            cx, cy = kicad_to_cnc(pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y), board_info, origin_mode, mirror_x=mirror_x)
            pts.append((cx, cy))
        if pts:
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            outer_loops.append(pts)

        for h_idx in range(poly.HoleCount(i)):
            hole = poly.Hole(i, h_idx)
            h_pts = []
            for j in range(hole.PointCount()):
                pt = hole.CPoint(j)
                cx, cy = kicad_to_cnc(pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y), board_info, origin_mode, mirror_x=mirror_x)
                h_pts.append((cx, cy))
            if h_pts:
                if h_pts[0] != h_pts[-1]:
                    h_pts.append(h_pts[0])
                inner_loops.append(h_pts)
    return outer_loops, inner_loops


def extract_board_cutout_polygons(board, board_info, tool_diameter, origin_mode="bottom_left"):
    """
    Extract board perimeter and internal cutouts, offset by tool radius:
      - Outer perimeter offset outwards (+R)
      - Inner cutouts offset inwards (-R)
    Returns:
      outer_loops: list of [(x, y), ...] in CNC coordinates
      inner_loops: list of [(x, y), ...] in CNC coordinates
    """
    poly = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(poly, True) or poly.OutlineCount() == 0:
        w = board_info["width"]
        h = board_info["height"]
        if w <= 0 or h <= 0:
            return [], []
        r = tool_diameter / 2.0
        outer = [
            (-r, -r),
            (w + r, -r),
            (w + r, h + r),
            (-r, h + r),
            (-r, -r)
        ]
        return [outer], []

    radius_nm = pcbnew.FromMM(tool_diameter / 2.0)
    outer_loops = []
    inner_loops = []

    for i in range(poly.OutlineCount()):
        single_poly = pcbnew.SHAPE_POLY_SET()
        single_poly.AddOutline(poly.Outline(i))
        try:
            single_poly.Inflate(radius_nm, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, pcbnew.FromMM(0.02))
        except Exception:
            pass

        for o_idx in range(single_poly.OutlineCount()):
            outline = single_poly.Outline(o_idx)
            pts = []
            for j in range(outline.PointCount()):
                pt = outline.CPoint(j)
                cx, cy = kicad_to_cnc(pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y), board_info, origin_mode)
                pts.append((cx, cy))
            if pts:
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                outer_loops.append(pts)

        for h_idx in range(poly.HoleCount(i)):
            hole = poly.Hole(i, h_idx)
            hole_poly = pcbnew.SHAPE_POLY_SET()
            hole_poly.AddOutline(hole)
            try:
                hole_poly.Inflate(-radius_nm, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, pcbnew.FromMM(0.02))
            except Exception:
                pass

            for ho_idx in range(hole_poly.OutlineCount()):
                h_out = hole_poly.Outline(ho_idx)
                pts = []
                for j in range(h_out.PointCount()):
                    pt = h_out.CPoint(j)
                    cx, cy = kicad_to_cnc(pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y), board_info, origin_mode)
                    pts.append((cx, cy))
                if pts:
                    if pts[0] != pts[-1]:
                        pts.append(pts[0])
                    inner_loops.append(pts)

    return outer_loops, inner_loops


def compute_path_length(path):
    """Calculate cumulative perimeter distance of a point list."""
    cum = [0.0]
    for i in range(len(path) - 1):
        d = math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
        cum.append(cum[-1] + d)
    return cum


def interpolate_point(path, cum, dist):
    """Interpolate (x, y) along path at target cumulative distance."""
    if dist <= 0.0:
        return path[0]
    if dist >= cum[-1]:
        return path[-1]
    for i in range(len(cum) - 1):
        if cum[i] <= dist <= cum[i + 1]:
            seg_len = cum[i + 1] - cum[i]
            if seg_len < 1e-6:
                return path[i]
            t = (dist - cum[i]) / seg_len
            x = path[i][0] + (path[i + 1][0] - path[i][0]) * t
            y = path[i][1] + (path[i + 1][1] - path[i][1]) * t
            return round(x, 4), round(y, 4)
    return path[-1]


def slice_path_with_tabs(path, num_tabs, tab_width):
    """
    Divide a closed loop path into cutting segments separated by holding tabs.
    Returns:
      segments: list of [pt0, pt1, ...] to cut at full depth
    """
    if num_tabs <= 0:
        return [path]

    cum = compute_path_length(path)
    perimeter = cum[-1]
    if perimeter <= 0:
        return [path]

    spacing = perimeter / num_tabs
    if tab_width >= spacing:
        return [path]

    segments = []
    for k in range(num_tabs):
        start_dist = k * spacing + tab_width
        end_dist = (k + 1) * spacing

        pts = [interpolate_point(path, cum, start_dist)]
        for i in range(1, len(cum) - 1):
            if start_dist < cum[i] < end_dist:
                pts.append(path[i])
        pts.append(interpolate_point(path, cum, end_dist))
        segments.append(pts)

    return segments


def extract_cutout_tab_bridges(path, num_tabs, tab_width):
    """
    Extract the bridge segments (holding tabs) along a cutout path for visual previewing.
    Returns list of [pt_start, ..., pt_end] for each tab bridge.
    """
    if num_tabs <= 0 or len(path) < 2:
        return []
    cum = compute_path_length(path)
    perimeter = cum[-1]
    if perimeter <= 0:
        return []
    spacing = perimeter / num_tabs
    if tab_width >= spacing:
        return []

    bridges = []
    for k in range(num_tabs):
        start_dist = k * spacing
        end_dist = k * spacing + tab_width
        pts = [interpolate_point(path, cum, start_dist)]
        for i in range(1, len(cum) - 1):
            if start_dist < cum[i] < end_dist:
                pts.append(path[i])
        pts.append(interpolate_point(path, cum, end_dist))
        bridges.append(pts)
    return bridges


def _build_raw_copper_poly_set(board, layer_id, extra_margin_mm=0.0):
    """
    Build a unified SHAPE_POLY_SET of all pads, tracks, vias, and zones on layer_id.
    """
    poly_set = pcbnew.SHAPE_POLY_SET()
    error_loc = pcbnew.ERROR_INSIDE if hasattr(pcbnew, "ERROR_INSIDE") else 0
    max_err = pcbnew.FromMM(0.015)

    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.IsOnLayer(layer_id):
                try:
                    pad.TransformShapeToPolygon(poly_set, layer_id, 0, max_err, error_loc)
                except Exception:
                    pass

    for track in board.GetTracks():
        if track.IsOnLayer(layer_id):
            try:
                track.TransformShapeToPolygon(poly_set, layer_id, 0, max_err, error_loc)
            except Exception:
                pass

    try:
        for zone in board.Zones():
            if zone.IsOnLayer(layer_id):
                filled = zone.GetFilledPolysList(layer_id)
                poly_set.Append(filled)
    except Exception:
        pass

    if poly_set.OutlineCount() == 0:
        return poly_set

    try:
        poly_set.Simplify()
    except Exception:
        pass

    if extra_margin_mm > 1e-4:
        try:
            poly_set.Inflate(
                pcbnew.FromMM(extra_margin_mm),
                pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                pcbnew.FromMM(0.02),
            )
        except Exception:
            pass

    return poly_set


def extract_copper_polygons_cnc(board, board_info, layer_id, origin_mode="bottom_left", mirror_x=False, extra_margin_mm=0.0):
    """
    Extract unified copper regions (outer contours + holes) in CNC coordinates for 2D preview rendering.
    Returns list of (outer_pts, [hole_pts, ...]).
    """
    poly_set = _build_raw_copper_poly_set(board, layer_id, extra_margin_mm=extra_margin_mm)
    regions = []
    for i in range(poly_set.OutlineCount()):
        outline = poly_set.Outline(i)
        outer_pts = []
        for j in range(outline.PointCount()):
            pt = outline.CPoint(j)
            cx, cy = kicad_to_cnc(pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y), board_info, origin_mode, mirror_x=mirror_x)
            outer_pts.append((cx, cy))
        if not outer_pts:
            continue
        if outer_pts[0] != outer_pts[-1]:
            outer_pts.append(outer_pts[0])

        holes = []
        for h in range(poly_set.HoleCount(i)):
            hole = poly_set.Hole(i, h)
            h_pts = []
            for j in range(hole.PointCount()):
                pt = hole.CPoint(j)
                cx, cy = kicad_to_cnc(pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y), board_info, origin_mode, mirror_x=mirror_x)
                h_pts.append((cx, cy))
            if h_pts:
                if h_pts[0] != h_pts[-1]:
                    h_pts.append(h_pts[0])
                holes.append(h_pts)

        regions.append((outer_pts, holes))
    return regions


def calculate_isolation_passes(tool_diameter, clearance_mm=0.0, min_passes=1, overlap_ratio=0.5):
    """
    Compute the number of isolation passes, stepover in mm, and resulting total clearance width in mm.
    """
    tool_dia = max(0.02, float(tool_diameter))
    overlap = min(0.85, max(0.05, float(overlap_ratio)))
    step_mm = tool_dia * (1.0 - overlap)

    needed_for_mm = 1
    if clearance_mm > tool_dia + 1e-5:
        needed_for_mm = 1 + math.ceil((clearance_mm - tool_dia - 1e-6) / step_mm)

    num_passes = max(1, int(min_passes), needed_for_mm)
    effective_width_mm = tool_dia + (num_passes - 1) * step_mm
    return num_passes, round(step_mm, 4), round(effective_width_mm, 4)


def _poly_set_to_cnc_loops(poly_set, board_info, origin_mode, mirror_x, reverse_dir=False):
    """Convert all outlines and holes in a SHAPE_POLY_SET to closed CNC point loops."""
    loops = []
    for i in range(poly_set.OutlineCount()):
        outline = poly_set.Outline(i)
        pts = []
        for j in range(outline.PointCount()):
            pt = outline.CPoint(j)
            cx, cy = kicad_to_cnc(pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y), board_info, origin_mode, mirror_x=mirror_x)
            pts.append((cx, cy))
        if len(pts) >= 2:
            if reverse_dir:
                pts.reverse()
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            loops.append(pts)

        for h in range(poly_set.HoleCount(i)):
            hole = poly_set.Hole(i, h)
            h_pts = []
            for j in range(hole.PointCount()):
                pt = hole.CPoint(j)
                cx, cy = kicad_to_cnc(pcbnew.ToMM(pt.x), pcbnew.ToMM(pt.y), board_info, origin_mode, mirror_x=mirror_x)
                h_pts.append((cx, cy))
            if len(h_pts) >= 2:
                if reverse_dir:
                    h_pts.reverse()
                if h_pts[0] != h_pts[-1]:
                    h_pts.append(h_pts[0])
                loops.append(h_pts)
    return loops


def _optimize_loop_order(loops, start_pos=(0.0, 0.0)):
    """Order closed loops using nearest-neighbor to minimize rapid travel."""
    if not loops:
        return []
    ordered = []
    current_pos = start_pos
    remaining = list(loops)
    while remaining:
        best_idx = min(
            range(len(remaining)),
            key=lambda idx: (remaining[idx][0][0] - current_pos[0]) ** 2 + (remaining[idx][0][1] - current_pos[1]) ** 2
        )
        loop = remaining.pop(best_idx)
        ordered.append(loop)
        current_pos = loop[-1]
    return ordered


def extract_copper_toolpaths(board, board_info, layer_id, settings=None, origin_mode=None, mirror_x=None):
    """
    Extract both trace isolation loops and (optionally) full excess copper clearing loops.

    Supports 3 modes via settings['iso_mode']:
      - 'single':     1 isolation pass at tool_diameter / 2
      - 'multipass':  Multi-pass isolation to achieve target spacing in mm (iso_clearance_mm / iso_passes)
      - 'full_clear': Complete removal of all remaining copper on the board ("Leave Only Lines")

    Returns:
      (isolation_loops, clearing_loops)
    """
    if settings is None:
        settings = {}

    origin = origin_mode if origin_mode is not None else settings.get("origin_mode", "bottom_left")
    if mirror_x is None:
        mirror_x = (layer_id == pcbnew.B_Cu) and bool(settings.get("iso_mirror_bottom", True))

    iso_mode = settings.get("iso_mode", "single")
    tool_dia = max(0.02, float(settings.get("iso_tool_diameter", 0.2)))
    clearance_mm = float(settings.get("iso_clearance_mm", tool_dia))
    min_passes = int(settings.get("iso_passes", 1))
    overlap = float(settings.get("iso_pass_overlap", 0.5))
    extra_pad_margin = float(settings.get("iso_pad_extra_offset_mm", 0.0))
    clip_to_board = bool(settings.get("iso_clip_to_board", True))
    climb = bool(settings.get("iso_climb_milling", False))

    base_copper = _build_raw_copper_poly_set(board, layer_id, extra_margin_mm=extra_pad_margin)
    if base_copper.OutlineCount() == 0:
        return [], []

    board_poly = _get_board_outline_poly_set(board, board_info)
    has_board_poly = board_poly.OutlineCount() > 0

    if iso_mode == "single":
        num_passes = 1
        step_mm = tool_dia * (1.0 - overlap)
    elif iso_mode == "multipass":
        num_passes, step_mm, _ = calculate_isolation_passes(tool_dia, clearance_mm, min_passes, overlap)
    else:
        num_passes, step_mm, _ = calculate_isolation_passes(
            tool_dia, max(tool_dia, min(clearance_mm, tool_dia * 2.5)), max(1, min(min_passes, 3)), overlap
        )

    raw_iso_loops = []
    last_inflated_copper = None
    last_offset_mm = tool_dia / 2.0

    for p_idx in range(num_passes):
        offset_mm = (tool_dia / 2.0) + p_idx * step_mm
        last_offset_mm = offset_mm
        pass_poly = pcbnew.SHAPE_POLY_SET(base_copper)
        try:
            pass_poly.Inflate(
                pcbnew.FromMM(offset_mm),
                pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                pcbnew.FromMM(0.02),
            )
            if clip_to_board and has_board_poly and p_idx > 0:
                clip_bound = pcbnew.SHAPE_POLY_SET(board_poly)
                clip_bound.Deflate(
                    pcbnew.FromMM(max(0.05, tool_dia / 2.0)),
                    pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                    pcbnew.FromMM(0.02),
                )
                pass_poly.BooleanIntersection(clip_bound)
        except Exception:
            pass

        last_inflated_copper = pass_poly
        pass_loops = _poly_set_to_cnc_loops(pass_poly, board_info, origin, mirror_x, reverse_dir=climb)
        raw_iso_loops.extend(_optimize_loop_order(pass_loops))

    raw_clear_loops = []
    if iso_mode == "full_clear" and has_board_poly:
        use_sep_tool = bool(settings.get("iso_use_separate_clear_tool", False))
        clear_tool_dia = max(0.05, float(settings.get("iso_clear_tool_diameter", 0.8))) if use_sep_tool else tool_dia
        clear_stepover_ratio = min(0.9, max(0.2, float(settings.get("iso_clear_stepover", 0.6))))
        clear_step_mm = clear_tool_dia * clear_stepover_ratio
        board_margin_mm = max(0.0, float(settings.get("iso_board_margin_mm", 0.3)))

        max_err_clear = pcbnew.FromMM(0.04)

        base_rem = pcbnew.SHAPE_POLY_SET(board_poly)
        try:
            inset_mm = board_margin_mm + (clear_tool_dia / 2.0)
            if inset_mm > 0:
                base_rem.Deflate(
                    pcbnew.FromMM(inset_mm),
                    pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                    max_err_clear,
                )

            protect_offset_mm = max(
                (tool_dia / 2.0) + (clear_tool_dia / 2.0),
                last_offset_mm + (clear_tool_dia / 2.0) - (tool_dia * 0.35),
            )
            protected = pcbnew.SHAPE_POLY_SET(base_copper)
            protected.Inflate(
                pcbnew.FromMM(protect_offset_mm),
                pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                max_err_clear,
            )

            base_rem.BooleanSubtract(protected)
        except Exception:
            pass

        for k in range(0, 200):
            if k == 0:
                rem = pcbnew.SHAPE_POLY_SET(base_rem)
            else:
                rem = pcbnew.SHAPE_POLY_SET(base_rem)
                try:
                    rem.Deflate(
                        pcbnew.FromMM(k * clear_step_mm),
                        pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                        max_err_clear,
                    )
                except Exception:
                    break

            if rem.IsEmpty() or rem.OutlineCount() == 0:
                break

            k_loops = _poly_set_to_cnc_loops(rem, board_info, origin, mirror_x, reverse_dir=climb)
            if not k_loops:
                break
            raw_clear_loops.extend(_optimize_loop_order(k_loops))

    return raw_iso_loops, raw_clear_loops


def extract_copper_isolation_loops(
    board,
    board_info,
    layer_id,
    tool_diameter,
    origin_mode="bottom_left",
    mirror_x=False,
    settings=None,
):
    """
    Extract closed isolation milling loops for tracks, pads, and zones on a copper layer.
    Backward-compatible wrapper that also supports multi-pass spacing and full copper clearing.
    """
    eff_settings = dict(settings) if settings else {}
    eff_settings["iso_tool_diameter"] = tool_diameter
    eff_settings["origin_mode"] = origin_mode
    if "iso_mode" not in eff_settings:
        eff_settings["iso_mode"] = "single"

    iso_loops, clear_loops = extract_copper_toolpaths(
        board,
        board_info,
        layer_id,
        settings=eff_settings,
        origin_mode=origin_mode,
        mirror_x=mirror_x,
    )
    if clear_loops and not eff_settings.get("iso_use_separate_clear_tool", False):
        return iso_loops + clear_loops
    return iso_loops


def estimate_job_statistics(
    drill_groups,
    cutout_outer,
    cutout_inner,
    f_iso_loops,
    f_clear_loops,
    b_iso_loops,
    b_clear_loops,
    settings,
):
    """
    Compute total cutting distance, rapid travel distance, contour counts, and estimated CNC run time.
    """
    stats = {
        "hole_count": 0,
        "tool_count": len(drill_groups),
        "iso_contour_count": len(f_iso_loops) + len(b_iso_loops),
        "clear_contour_count": len(f_clear_loops) + len(b_clear_loops),
        "cut_distance_mm": 0.0,
        "rapid_distance_mm": 0.0,
        "estimated_seconds": 0.0,
    }

    rapid_rate = 1500.0

    drill_depth = abs(float(settings.get("drill_depth", -1.8)))
    safe_z = max(0.5, float(settings.get("drill_safe_z", 3.0)))
    drill_feed = max(10.0, float(settings.get("drill_feed_z", 200.0)))
    peck = bool(settings.get("drill_peck_enabled", False))
    peck_step = max(0.1, float(settings.get("drill_peck_depth", 0.6)))

    cur = (0.0, 0.0)
    for _, pts in drill_groups:
        stats["hole_count"] += len(pts)
        for pt in pts:
            d_xy = math.hypot(pt[0] - cur[0], pt[1] - cur[1])
            stats["rapid_distance_mm"] += d_xy
            cur = pt
            if peck:
                pecks = max(1, math.ceil(drill_depth / peck_step))
                plunge_dist = drill_depth + pecks * safe_z
            else:
                plunge_dist = drill_depth + safe_z
            stats["cut_distance_mm"] += drill_depth
            stats["estimated_seconds"] += (plunge_dist / drill_feed) * 60.0

    iso_feed = max(10.0, float(settings.get("iso_feed_xy", 300.0)))
    clear_feed = max(10.0, float(settings.get("iso_clear_feed_xy", 450.0))) if settings.get("iso_use_separate_clear_tool") else iso_feed

    for loop_list, feed in [
        (f_iso_loops, iso_feed),
        (b_iso_loops, iso_feed),
        (f_clear_loops, clear_feed),
        (b_clear_loops, clear_feed),
    ]:
        cur = (0.0, 0.0)
        for loop in loop_list:
            if not loop:
                continue
            stats["rapid_distance_mm"] += math.hypot(loop[0][0] - cur[0], loop[0][1] - cur[1])
            length = compute_path_length(loop)[-1]
            stats["cut_distance_mm"] += length
            stats["estimated_seconds"] += (length / feed) * 60.0 + 0.35
            cur = loop[-1]

    cut_depth = abs(float(settings.get("cutout_depth", -1.8)))
    pass_depth = max(0.1, float(settings.get("cutout_pass_depth", 0.5)))
    cut_passes = max(1, math.ceil(cut_depth / pass_depth))
    cut_feed = max(10.0, float(settings.get("cutout_feed_xy", 400.0)))

    for loop in (cutout_outer + cutout_inner):
        if not loop:
            continue
        length = compute_path_length(loop)[-1] * cut_passes
        stats["cut_distance_mm"] += length
        stats["estimated_seconds"] += (length / cut_feed) * 60.0 + cut_passes * 0.5

    stats["estimated_seconds"] += (stats["rapid_distance_mm"] / rapid_rate) * 60.0
    return stats
