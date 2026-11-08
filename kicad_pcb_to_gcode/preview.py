"""Interactive 2D CNC Toolpath & PCB Preview Canvas for KiCad PCB to G-Code Exporter."""

import math
import wx


class GCodePreviewPanel(wx.Panel):
    """
    Interactive 2D preview widget with pan, zoom, layer toggles, and live coordinate readout.
    Renders:
      - Millimeter grid & CNC (0,0) origin axes
      - PCB board outline & FR4 substrate
      - Copper tracks, pads, and zones
      - Multi-pass copper isolation toolpaths
      - Full copper clearing ("Leave Only Lines" rubout) toolpaths
      - Board cutout path with highlighted holding tabs/bridges
      - Drill holes (true diameter) & oblong slots + rapid G0 travel moves
    """

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.parent_panel = parent

        self.data = {
            "board_outer": [],
            "board_inner": [],
            "copper_regions": [],
            "iso_loops": [],
            "clear_loops": [],
            "cutout_outer": [],
            "cutout_inner": [],
            "tab_bridges": [],
            "drill_groups": [],
            "all_holes": [],
            "iso_tool_dia": 0.2,
            "clear_tool_dia": 0.2,
            "cutout_tool_dia": 2.0,
            "layer_label": "Back Copper (B.Cu)",
            "iso_mode": "multipass",
        }

        self.show_copper = True
        self.show_iso = True
        self.show_clear = True
        self.show_drill = True
        self.show_cutout = True
        self.show_rapid = False

        self.scale = 8.0
        self.offset_x = 60.0
        self.offset_y = 320.0
        self._dragging = False
        self._last_mouse = (0, 0)
        self._cursor_mm = (0.0, 0.0)
        self._needs_initial_fit = True

        self._init_layout()

    def _init_layout(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        ctrl_bar = wx.BoxSizer(wx.HORIZONTAL)

        lbl_side = wx.StaticText(self, label="Preview Layer:")
        self.side_choice = wx.Choice(
            self,
            choices=["Auto (Active Copper)", "Back Copper (B.Cu)", "Front Copper (F.Cu)"],
        )
        self.side_choice.SetSelection(0)
        self.side_choice.Bind(wx.EVT_CHOICE, self._on_side_changed)

        btn_fit = wx.Button(self, label="Fit Board", style=wx.BU_EXACTFIT)
        btn_fit.SetToolTip("Reset zoom and center board in preview (or double-click canvas)")
        btn_fit.Bind(wx.EVT_BUTTON, lambda e: self.fit_to_board())

        btn_zin = wx.Button(self, label=" + ", style=wx.BU_EXACTFIT)
        btn_zin.Bind(wx.EVT_BUTTON, lambda e: self._zoom_by(1.25))
        btn_zout = wx.Button(self, label=" - ", style=wx.BU_EXACTFIT)
        btn_zout.Bind(wx.EVT_BUTTON, lambda e: self._zoom_by(0.8))

        ctrl_bar.Add(lbl_side, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        ctrl_bar.Add(self.side_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        ctrl_bar.AddStretchSpacer(1)
        ctrl_bar.Add(btn_zout, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        ctrl_bar.Add(btn_zin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        ctrl_bar.Add(btn_fit, 0, wx.ALIGN_CENTER_VERTICAL)

        main_sizer.Add(ctrl_bar, 0, wx.EXPAND | wx.BOTTOM, 4)

        toggle_bar = wx.WrapSizer(wx.HORIZONTAL)
        self.chk_vis_copper = wx.CheckBox(self, label="Copper")
        self.chk_vis_copper.SetValue(True)
        self.chk_vis_iso = wx.CheckBox(self, label="Isolation")
        self.chk_vis_iso.SetValue(True)
        self.chk_vis_clear = wx.CheckBox(self, label="Rubout/Clear")
        self.chk_vis_clear.SetValue(True)
        self.chk_vis_drill = wx.CheckBox(self, label="Drills")
        self.chk_vis_drill.SetValue(True)
        self.chk_vis_cutout = wx.CheckBox(self, label="Cutout & Tabs")
        self.chk_vis_cutout.SetValue(True)
        self.chk_vis_rapid = wx.CheckBox(self, label="Rapid G0")
        self.chk_vis_rapid.SetValue(False)

        for chk in (
            self.chk_vis_copper,
            self.chk_vis_iso,
            self.chk_vis_clear,
            self.chk_vis_drill,
            self.chk_vis_cutout,
            self.chk_vis_rapid,
        ):
            chk.Bind(wx.EVT_CHECKBOX, self._on_toggle_visibility)
            toggle_bar.Add(chk, 0, wx.RIGHT | wx.BOTTOM, 6)

        main_sizer.Add(toggle_bar, 0, wx.EXPAND | wx.BOTTOM, 2)

        self.canvas = wx.Panel(self, style=wx.BORDER_SIMPLE | wx.FULL_REPAINT_ON_RESIZE)
        self.canvas.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.canvas.SetMinSize((420, 340))

        self.canvas.Bind(wx.EVT_PAINT, self._on_paint)
        self.canvas.Bind(wx.EVT_SIZE, self._on_size)
        self.canvas.Bind(wx.EVT_LEFT_DOWN, self._on_mouse_down)
        self.canvas.Bind(wx.EVT_MIDDLE_DOWN, self._on_mouse_down)
        self.canvas.Bind(wx.EVT_LEFT_UP, self._on_mouse_up)
        self.canvas.Bind(wx.EVT_MIDDLE_UP, self._on_mouse_up)
        self.canvas.Bind(wx.EVT_MOTION, self._on_mouse_move)
        self.canvas.Bind(wx.EVT_MOUSEWHEEL, self._on_mouse_wheel)
        self.canvas.Bind(wx.EVT_LEFT_DCLICK, lambda e: self.fit_to_board())

        main_sizer.Add(self.canvas, 1, wx.EXPAND)

        footer_bar = wx.BoxSizer(wx.HORIZONTAL)
        self.status_lbl = wx.StaticText(
            self,
            label="Scroll: Zoom | Drag: Pan | Dbl-Click: Fit   |   X: 0.00  Y: 0.00 mm",
        )
        font = self.status_lbl.GetFont()
        font.SetPointSize(max(7, font.GetPointSize() - 1))
        self.status_lbl.SetFont(font)
        self.status_lbl.SetForegroundColour(wx.Colour(100, 110, 120))
        footer_bar.Add(self.status_lbl, 1, wx.EXPAND | wx.TOP, 3)

        main_sizer.Add(footer_bar, 0, wx.EXPAND)
        self.SetSizer(main_sizer)

        self._on_side_changed_callback = None

    def set_side_change_callback(self, callback):
        self._on_side_changed_callback = callback

    def get_selected_side_mode(self):
        idx = self.side_choice.GetSelection()
        if idx == 1:
            return "back"
        if idx == 2:
            return "front"
        return "auto"

    def _on_side_changed(self, event):
        if self._on_side_changed_callback:
            self._on_side_changed_callback()

    def _on_toggle_visibility(self, event):
        self.show_copper = self.chk_vis_copper.GetValue()
        self.show_iso = self.chk_vis_iso.GetValue()
        self.show_clear = self.chk_vis_clear.GetValue()
        self.show_drill = self.chk_vis_drill.GetValue()
        self.show_cutout = self.chk_vis_cutout.GetValue()
        self.show_rapid = self.chk_vis_rapid.GetValue()
        self.canvas.Refresh()

    def update_preview_data(self, preview_data, auto_fit=False):
        """Update stored geometry and repaint canvas."""
        self.data.update(preview_data)
        if auto_fit or self._needs_initial_fit:
            self.fit_to_board()
            self._needs_initial_fit = False
        else:
            self.canvas.Refresh()

    def _cnc_to_screen(self, x_mm, y_mm):
        sx = self.offset_x + x_mm * self.scale
        sy = self.offset_y - y_mm * self.scale
        return sx, sy

    def _screen_to_cnc(self, sx, sy):
        if abs(self.scale) < 1e-6:
            return 0.0, 0.0
        x_mm = (sx - self.offset_x) / self.scale
        y_mm = (self.offset_y - sy) / self.scale
        return x_mm, y_mm

    def _compute_bounds(self):
        xs = []
        ys = []
        for key in ("board_outer", "cutout_outer", "iso_loops", "clear_loops"):
            for loop in self.data.get(key, []):
                for pt in loop:
                    xs.append(pt[0])
                    ys.append(pt[1])
        for outer, _ in self.data.get("copper_regions", []):
            for pt in outer:
                xs.append(pt[0])
                ys.append(pt[1])
        for _, pts in self.data.get("drill_groups", []):
            for pt in pts:
                xs.append(pt[0])
                ys.append(pt[1])

        if not xs or not ys:
            return -5.0, 55.0, -5.0, 45.0
        return min(xs), max(xs), min(ys), max(ys)

    def fit_to_board(self):
        cw, ch = self.canvas.GetClientSize()
        if cw < 40 or ch < 40:
            cw, ch = 460, 360

        min_x, max_x, min_y, max_y = self._compute_bounds()
        min_x = min(min_x, 0.0)
        max_x = max(max_x, 0.0)
        min_y = min(min_y, 0.0)
        max_y = max(max_y, 0.0)

        span_x = max(5.0, max_x - min_x)
        span_y = max(5.0, max_y - min_y)

        margin = 44.0
        avail_w = max(50.0, cw - 2 * margin)
        avail_h = max(50.0, ch - 2 * margin)

        self.scale = min(avail_w / span_x, avail_h / span_y)
        cx_mm = (min_x + max_x) / 2.0
        cy_mm = (min_y + max_y) / 2.0

        self.offset_x = (cw / 2.0) - cx_mm * self.scale
        self.offset_y = (ch / 2.0) + cy_mm * self.scale
        self.canvas.Refresh()

    def _zoom_by(self, factor, pivot_px=None):
        cw, ch = self.canvas.GetClientSize()
        if pivot_px is None:
            pivot_px = (cw / 2.0, ch / 2.0)
        px, py = pivot_px
        mm_x, mm_y = self._screen_to_cnc(px, py)
        new_scale = max(0.5, min(250.0, self.scale * factor))
        self.scale = new_scale
        self.offset_x = px - mm_x * self.scale
        self.offset_y = py + mm_y * self.scale
        self.canvas.Refresh()

    def _on_size(self, event):
        if self._needs_initial_fit:
            self.fit_to_board()
        else:
            self.canvas.Refresh()
        event.Skip()

    def _on_mouse_down(self, event):
        self._dragging = True
        self._last_mouse = event.GetPosition()
        self.canvas.SetFocus()

    def _on_mouse_up(self, event):
        self._dragging = False

    def _on_mouse_move(self, event):
        pos = event.GetPosition()
        if self._dragging and (event.LeftIsDown() or event.MiddleIsDown()):
            dx = pos.x - self._last_mouse[0]
            dy = pos.y - self._last_mouse[1]
            self.offset_x += dx
            self.offset_y += dy
            self._last_mouse = pos
            self.canvas.Refresh()

        self._cursor_mm = self._screen_to_cnc(pos.x, pos.y)
        self.status_lbl.SetLabel(
            f"Scroll: Zoom | Drag: Pan | Dbl-Click: Fit   |   Cursor: X={self._cursor_mm[0]:.2f} mm, Y={self._cursor_mm[1]:.2f} mm"
        )

    def _on_mouse_wheel(self, event):
        rot = event.GetWheelRotation()
        if rot == 0:
            return
        factor = 1.18 if rot > 0 else (1.0 / 1.18)
        pos = event.GetPosition()
        self._zoom_by(factor, pivot_px=(pos.x, pos.y))

    def _on_paint(self, event):
        dc = wx.BufferedPaintDC(self.canvas)
        cw, ch = self.canvas.GetClientSize()

        dc.SetBackground(wx.Brush(wx.Colour(22, 26, 33)))
        dc.Clear()

        gc = wx.GraphicsContext.Create(dc)
        if not gc:
            return

        self._draw_grid_and_origin(dc, cw, ch)
        self._draw_board_substrate(gc)

        if self.show_copper:
            self._draw_copper_regions(gc)

        if self.show_clear:
            self._draw_clearing_loops(gc)

        if self.show_iso:
            self._draw_isolation_loops(gc)

        if self.show_cutout:
            self._draw_cutout_and_tabs(gc)

        if self.show_drill:
            self._draw_drill_holes(gc)

        self._draw_overlay_hud(dc, cw, ch)

    def _draw_grid_and_origin(self, dc, cw, ch):
        min_x, max_y = self._screen_to_cnc(0, 0)
        max_x, min_y = self._screen_to_cnc(cw, ch)

        if self.scale >= 6.0:
            dc.SetPen(wx.Pen(wx.Colour(32, 38, 48), 1))
            gx = math.floor(min_x)
            while gx <= max_x:
                sx, _ = self._cnc_to_screen(gx, 0)
                dc.DrawLine(int(sx), 0, int(sx), ch)
                gx += 1.0
            gy = math.floor(min_y)
            while gy <= max_y:
                _, sy = self._cnc_to_screen(0, gy)
                dc.DrawLine(0, int(sy), cw, int(sy))
                gy += 1.0

        dc.SetPen(wx.Pen(wx.Colour(45, 53, 66), 1))
        gx = math.floor(min_x / 10.0) * 10.0
        while gx <= max_x:
            sx, _ = self._cnc_to_screen(gx, 0)
            dc.DrawLine(int(sx), 0, int(sx), ch)
            gx += 10.0
        gy = math.floor(min_y / 10.0) * 10.0
        while gy <= max_y:
            _, sy = self._cnc_to_screen(0, gy)
            dc.DrawLine(0, int(sy), cw, int(sy))
            gy += 10.0

        ox, oy = self._cnc_to_screen(0.0, 0.0)
        dc.SetPen(wx.Pen(wx.Colour(220, 65, 65), 2))
        dc.DrawLine(int(ox), int(oy), int(ox + 34), int(oy))
        dc.SetPen(wx.Pen(wx.Colour(65, 210, 95), 2))
        dc.DrawLine(int(ox), int(oy), int(ox), int(oy - 34))

        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 1))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawCircle(int(ox), int(oy), 5)
        dc.SetTextForeground(wx.Colour(210, 220, 230))
        dc.DrawText("(0,0)", int(ox + 6), int(oy + 4))

    def _draw_board_substrate(self, gc):
        outer_loops = self.data.get("board_outer", [])
        inner_loops = self.data.get("board_inner", [])
        if not outer_loops:
            return

        iso_mode = self.data.get("iso_mode", "multipass")
        if iso_mode == "full_clear":
            fill_color = wx.Colour(28, 52, 38, 220)
        else:
            fill_color = wx.Colour(34, 58, 42, 215)

        gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(90, 140, 105)).Width(1.5)))
        gc.SetBrush(gc.CreateBrush(wx.Brush(fill_color)))

        path = gc.CreatePath()
        for loop in outer_loops:
            if len(loop) < 2:
                continue
            sx0, sy0 = self._cnc_to_screen(loop[0][0], loop[0][1])
            path.MoveToPoint(sx0, sy0)
            for pt in loop[1:]:
                sx, sy = self._cnc_to_screen(pt[0], pt[1])
                path.AddLineToPoint(sx, sy)
            path.CloseSubpath()

        for hole in inner_loops:
            if len(hole) < 2:
                continue
            sx0, sy0 = self._cnc_to_screen(hole[0][0], hole[0][1])
            path.MoveToPoint(sx0, sy0)
            for pt in hole[1:]:
                sx, sy = self._cnc_to_screen(pt[0], pt[1])
                path.AddLineToPoint(sx, sy)
            path.CloseSubpath()

        gc.DrawPath(path, wx.ODDEVEN_RULE)

    def _draw_copper_regions(self, gc):
        regions = self.data.get("copper_regions", [])
        if not regions:
            return

        gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(230, 155, 75, 230)).Width(1.0)))
        gc.SetBrush(gc.CreateBrush(wx.Brush(wx.Colour(205, 125, 50, 195))))

        path = gc.CreatePath()
        for outer, holes in regions:
            if len(outer) < 2:
                continue
            sx0, sy0 = self._cnc_to_screen(outer[0][0], outer[0][1])
            path.MoveToPoint(sx0, sy0)
            for pt in outer[1:]:
                sx, sy = self._cnc_to_screen(pt[0], pt[1])
                path.AddLineToPoint(sx, sy)
            path.CloseSubpath()

            for h in holes:
                if len(h) < 2:
                    continue
                hx0, hy0 = self._cnc_to_screen(h[0][0], h[0][1])
                path.MoveToPoint(hx0, hy0)
                for pt in h[1:]:
                    hx, hy = self._cnc_to_screen(pt[0], pt[1])
                    path.AddLineToPoint(hx, hy)
                path.CloseSubpath()

        gc.DrawPath(path, wx.ODDEVEN_RULE)

    def _draw_clearing_loops(self, gc):
        clear_loops = self.data.get("clear_loops", [])
        if not clear_loops:
            return

        clear_dia = float(self.data.get("clear_tool_dia", 0.2))
        stroke_px = max(1.0, min(8.0, clear_dia * self.scale * 0.65))
        gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(120, 235, 90, 175)).Width(stroke_px)))

        path = gc.CreatePath()
        for loop in clear_loops:
            if len(loop) < 2:
                continue
            sx0, sy0 = self._cnc_to_screen(loop[0][0], loop[0][1])
            path.MoveToPoint(sx0, sy0)
            for pt in loop[1:]:
                sx, sy = self._cnc_to_screen(pt[0], pt[1])
                path.AddLineToPoint(sx, sy)
        gc.StrokePath(path)

    def _draw_isolation_loops(self, gc):
        iso_loops = self.data.get("iso_loops", [])
        if not iso_loops:
            return

        tool_dia = float(self.data.get("iso_tool_dia", 0.2))
        stroke_px = max(1.2, min(6.0, tool_dia * self.scale * 0.7))
        gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(0, 225, 255, 230)).Width(stroke_px)))

        path = gc.CreatePath()
        for loop in iso_loops:
            if len(loop) < 2:
                continue
            sx0, sy0 = self._cnc_to_screen(loop[0][0], loop[0][1])
            path.MoveToPoint(sx0, sy0)
            for pt in loop[1:]:
                sx, sy = self._cnc_to_screen(pt[0], pt[1])
                path.AddLineToPoint(sx, sy)
        gc.StrokePath(path)

        if self.show_rapid and len(iso_loops) > 1:
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(140, 150, 175, 110)).Width(1.0).Style(wx.PENSTYLE_SHORT_DASH)))
            rpath = gc.CreatePath()
            cur = (0.0, 0.0)
            for loop in iso_loops:
                if not loop:
                    continue
                sx0, sy0 = self._cnc_to_screen(cur[0], cur[1])
                sx1, sy1 = self._cnc_to_screen(loop[0][0], loop[0][1])
                rpath.MoveToPoint(sx0, sy0)
                rpath.AddLineToPoint(sx1, sy1)
                cur = loop[-1]
            gc.StrokePath(rpath)

    def _draw_cutout_and_tabs(self, gc):
        cut_outer = self.data.get("cutout_outer", [])
        cut_inner = self.data.get("cutout_inner", [])
        tab_bridges = self.data.get("tab_bridges", [])

        if cut_outer or cut_inner:
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(255, 120, 40, 225)).Width(1.8)))
            path = gc.CreatePath()
            for loop in (cut_outer + cut_inner):
                if len(loop) < 2:
                    continue
                sx0, sy0 = self._cnc_to_screen(loop[0][0], loop[0][1])
                path.MoveToPoint(sx0, sy0)
                for pt in loop[1:]:
                    sx, sy = self._cnc_to_screen(pt[0], pt[1])
                    path.AddLineToPoint(sx, sy)
            gc.StrokePath(path)

        if tab_bridges:
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(255, 230, 0, 255)).Width(4.5)))
            tpath = gc.CreatePath()
            for bridge in tab_bridges:
                if len(bridge) < 2:
                    continue
                sx0, sy0 = self._cnc_to_screen(bridge[0][0], bridge[0][1])
                tpath.MoveToPoint(sx0, sy0)
                for pt in bridge[1:]:
                    sx, sy = self._cnc_to_screen(pt[0], pt[1])
                    tpath.AddLineToPoint(sx, sy)
            gc.StrokePath(tpath)

    def _draw_drill_holes(self, gc):
        drill_groups = self.data.get("drill_groups", [])
        all_holes = self.data.get("all_holes", [])

        if self.show_rapid and drill_groups:
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(255, 90, 140, 140)).Width(1.0).Style(wx.PENSTYLE_SHORT_DASH)))
            rpath = gc.CreatePath()
            cur = (0.0, 0.0)
            for _, pts in drill_groups:
                for pt in pts:
                    sx0, sy0 = self._cnc_to_screen(cur[0], cur[1])
                    sx1, sy1 = self._cnc_to_screen(pt[0], pt[1])
                    rpath.MoveToPoint(sx0, sy0)
                    rpath.AddLineToPoint(sx1, sy1)
                    cur = pt
            gc.StrokePath(rpath)

        for h in all_holes:
            if h.get("is_slot") and h.get("slot_start") != h.get("slot_end"):
                (x1, y1), (x2, y2) = h["slot_start"], h["slot_end"]
                sx1, sy1 = self._cnc_to_screen(x1, y1)
                sx2, sy2 = self._cnc_to_screen(x2, y2)
                w_px = max(3.0, h["diameter"] * self.scale)
                gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(255, 80, 120, 230)).Width(w_px)))
                spath = gc.CreatePath()
                spath.MoveToPoint(sx1, sy1)
                spath.AddLineToPoint(sx2, sy2)
                gc.StrokePath(spath)

        palette = [
            wx.Colour(255, 95, 135),
            wx.Colour(80, 200, 255),
            wx.Colour(255, 210, 75),
            wx.Colour(175, 115, 255),
            wx.Colour(95, 240, 165),
        ]
        for g_idx, (dia, pts) in enumerate(drill_groups):
            col = palette[g_idx % len(palette)]
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(col).Width(1.5)))
            gc.SetBrush(gc.CreateBrush(wx.Brush(wx.Colour(16, 20, 26, 240))))
            r_px = max(2.2, (dia / 2.0) * self.scale)
            for x, y in pts:
                sx, sy = self._cnc_to_screen(x, y)
                gc.DrawEllipse(sx - r_px, sy - r_px, r_px * 2.0, r_px * 2.0)

    def _draw_overlay_hud(self, dc, cw, ch):
        layer_lbl = self.data.get("layer_label", "")
        mode_map = {
            "single": "Mode: Single-Pass Outline",
            "multipass": "Mode: Multi-Pass Spacing",
            "full_clear": "Mode: Leave Only Lines (100% Rubout)",
        }
        mode_str = mode_map.get(self.data.get("iso_mode", "multipass"), "")
        hud_text = f"{layer_lbl}  |  {mode_str}"

        dc.SetFont(self.GetFont().Bold())
        dc.SetTextForeground(wx.Colour(235, 240, 245))
        dc.DrawText(hud_text, 10, 8)

        legend_items = [
            (wx.Colour(205, 125, 50), "Remaining Copper"),
            (wx.Colour(0, 225, 255), "Isolation Cut"),
            (wx.Colour(120, 235, 90), "Copper Rubout"),
            (wx.Colour(255, 120, 40), "Cutout"),
            (wx.Colour(255, 230, 0), "Holding Tabs"),
            (wx.Colour(255, 95, 135), "Drill Holes"),
        ]
        lx = 10
        ly = ch - 22
        small_font = self.GetFont()
        small_font.SetPointSize(max(7, small_font.GetPointSize() - 2))
        dc.SetFont(small_font)

        for color, label in legend_items:
            dc.SetPen(wx.Pen(color, 1))
            dc.SetBrush(wx.Brush(color))
            dc.DrawRectangle(lx, ly + 3, 10, 10)
            dc.SetTextForeground(wx.Colour(200, 210, 220))
            dc.DrawText(label, lx + 14, ly + 1)
            tw, _ = dc.GetTextExtent(label)
            lx += tw + 26
            if lx > cw - 80:
                break
