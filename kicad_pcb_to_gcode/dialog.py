"""Interactive wxPython dialog with Presets, Copper Spacing/Clearing, and 2D Preview."""

import os
from pathlib import Path
import pcbnew
import wx

from .config import PRESETS, get_preset_by_id, load_settings, save_settings
from .geometry import (
    calculate_isolation_passes,
    estimate_job_statistics,
    extract_board_cutout_polygons,
    extract_board_outline_cnc,
    extract_copper_polygons_cnc,
    extract_copper_toolpaths,
    extract_cutout_tab_bridges,
    extract_drill_holes,
    get_board_info,
    group_and_optimize_holes,
)
from .generator import (
    generate_copper_isolation_gcode,
    generate_cutout_gcode,
    generate_drill_gcode,
)
from .preview import GCodePreviewPanel


class GCodeExportDialog(wx.Dialog):
    """Modern split-pane dialog with Quick Presets, Copper Clearing/Spacing, and Live 2D Preview."""

    def __init__(self, parent, board):
        super().__init__(
            parent,
            title="KiCad PCB to CNC G-Code Exporter (.nc)",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
            size=(1180, 790),
        )
        self.SetMinSize((940, 640))
        self.board = board
        self.settings = load_settings()
        self.board_info = get_board_info(board)

        self.all_holes = extract_drill_holes(board, self.board_info, self.settings)

        self._controls = {}
        self._updating_ui = False

        self._init_ui()
        self._sync_spacing_summary()
        self.refresh_preview(auto_fit=True)
        self.CenterOnParent()

    def _init_ui(self):
        root_sizer = wx.BoxSizer(wx.VERTICAL)

        top_box = wx.StaticBox(self, label="Quick Mode Presets (One-Click Setup)")
        top_sizer = wx.StaticBoxSizer(top_box, wx.VERTICAL)

        preset_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_preset = wx.StaticText(self, label="Select Mode Preset:")
        lbl_preset.SetFont(lbl_preset.GetFont().Bold())

        self.preset_choices = [(p["id"], p["name"]) for p in PRESETS] + [("custom", "Custom User Configuration")]
        self.preset_combo = wx.Choice(self, choices=[name for _, name in self.preset_choices])
        active_id = self.settings.get("active_preset", "good_isolation")
        preset_ids = [pid for pid, _ in self.preset_choices]
        sel_idx = preset_ids.index(active_id) if active_id in preset_ids else 0
        self.preset_combo.SetSelection(sel_idx)
        self.preset_combo.Bind(wx.EVT_CHOICE, self._on_preset_combo)

        preset_row.Add(lbl_preset, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        preset_row.Add(self.preset_combo, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        quick_buttons_bar = wx.BoxSizer(wx.HORIZONTAL)
        for p in PRESETS[:5]:
            btn = wx.Button(self, label=p["short_label"], style=wx.BU_EXACTFIT)
            btn.SetToolTip(p["description"])
            pid = p["id"]
            btn.Bind(wx.EVT_BUTTON, lambda evt, preset_id=pid: self.apply_preset(preset_id))
            quick_buttons_bar.Add(btn, 0, wx.RIGHT, 4)

        preset_row.Add(quick_buttons_bar, 0, wx.ALIGN_CENTER_VERTICAL)
        top_sizer.Add(preset_row, 0, wx.EXPAND | wx.ALL, 4)

        self.preset_desc_lbl = wx.StaticText(self, label="")
        self._style_subtext(self.preset_desc_lbl)
        self._update_preset_description(active_id)
        top_sizer.Add(self.preset_desc_lbl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        root_sizer.Add(top_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        split_sizer = wx.BoxSizer(wx.HORIZONTAL)

        left_panel = wx.Panel(self)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        self.notebook = wx.Notebook(left_panel)
        self.notebook.AddPage(self._create_layers_tab(self.notebook), "1. Layers & Setup")
        self.notebook.AddPage(self._create_isolation_tab(self.notebook), "2. Copper & Spacing")
        self.notebook.AddPage(self._create_drill_tab(self.notebook), "3. Drill Holes")
        self.notebook.AddPage(self._create_cutout_tab(self.notebook), "4. Board Cutout")
        self.notebook.AddPage(self._create_machine_tab(self.notebook), "5. Machine / Probe")

        left_sizer.Add(self.notebook, 1, wx.EXPAND)
        left_panel.SetSizer(left_sizer)

        right_box = wx.StaticBox(self, label="Live 2D CNC Toolpath & Board Preview")
        right_sizer = wx.StaticBoxSizer(right_box, wx.VERTICAL)

        self.preview_panel = GCodePreviewPanel(self)
        self.preview_panel.set_side_change_callback(lambda: self.refresh_preview(auto_fit=False))
        right_sizer.Add(self.preview_panel, 1, wx.EXPAND | wx.ALL, 4)

        stats_row = wx.BoxSizer(wx.HORIZONTAL)
        self.job_stats_lbl = wx.StaticText(
            self,
            label="Board: -- × -- mm | Holes: 0 | Contours: 0 | Est. Time: --",
        )
        self.job_stats_lbl.SetFont(self.job_stats_lbl.GetFont().Bold())

        refresh_btn = wx.Button(self, label="Update Preview")
        refresh_btn.SetToolTip("Recalculate toolpaths from current settings and update the 2D preview")
        refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self.refresh_preview(auto_fit=False))

        stats_row.Add(self.job_stats_lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        stats_row.Add(refresh_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        right_sizer.Add(stats_row, 0, wx.EXPAND | wx.ALL, 6)

        split_sizer.Add(left_panel, 5, wx.EXPAND | wx.RIGHT, 8)
        split_sizer.Add(right_sizer, 6, wx.EXPAND)
        root_sizer.Add(split_sizer, 1, wx.EXPAND | wx.ALL, 10)

        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.save_defaults_chk = wx.CheckBox(self, label="Save current settings as default for future boards")
        self.save_defaults_chk.SetValue(True)
        bottom_sizer.Add(self.save_defaults_chk, 0, wx.ALIGN_CENTER_VERTICAL)

        bottom_sizer.AddStretchSpacer(1)

        cancel_btn = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        export_btn = wx.Button(self, wx.ID_OK, label="Export G-Code (.nc)")
        export_btn.SetDefault()
        export_btn.SetFont(export_btn.GetFont().Bold())

        bottom_sizer.Add(cancel_btn, 0, wx.RIGHT, 8)
        bottom_sizer.Add(export_btn, 0)
        root_sizer.Add(bottom_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(root_sizer)

    def _add_field(self, parent, grid, key, label, unit, tooltip, description, on_change=None):
        """Create labeled numeric text control with unit and tiny description."""
        val = self.settings.get(key, "")
        lbl = wx.StaticText(parent, label=label)
        ctrl = wx.TextCtrl(parent, value=str(val), size=(90, -1))
        ctrl.SetToolTip(tooltip)
        unit_lbl = wx.StaticText(parent, label=unit)

        if on_change:
            ctrl.Bind(wx.EVT_TEXT, on_change)

        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(ctrl, 1, wx.EXPAND)
        grid.Add(unit_lbl, 0, wx.ALIGN_CENTER_VERTICAL)

        grid.AddSpacer(1)
        desc_lbl = wx.StaticText(parent, label=description)
        desc_font = desc_lbl.GetFont()
        desc_font.SetPointSize(max(7, desc_font.GetPointSize() - 2))
        desc_lbl.SetFont(desc_font)
        desc_lbl.SetForegroundColour(wx.Colour(110, 120, 130))
        grid.Add(desc_lbl, 1, wx.EXPAND)
        grid.AddSpacer(1)

        self._controls[key] = ctrl
        return ctrl

    def _create_layers_tab(self, parent):
        panel = wx.ScrolledWindow(parent)
        panel.SetScrollRate(5, 5)
        sizer = wx.BoxSizer(wx.VERTICAL)

        out_box = wx.StaticBox(panel, label="Output Destination")
        out_sizer = wx.StaticBoxSizer(out_box, wx.VERTICAL)
        out_grid = wx.FlexGridSizer(cols=3, vgap=6, hgap=8)
        out_grid.AddGrowableCol(1)

        out_grid.Add(wx.StaticText(panel, label="Export Folder:"), 0, wx.ALIGN_CENTER_VERTICAL)
        board_path = self.board.GetFileName()
        default_dir = os.path.dirname(board_path) if board_path else os.path.expanduser("~")
        self.folder_ctrl = wx.TextCtrl(panel, value=default_dir)
        out_grid.Add(self.folder_ctrl, 1, wx.EXPAND)
        browse_btn = wx.Button(panel, label="Browse...", style=wx.BU_EXACTFIT)
        browse_btn.Bind(wx.EVT_BUTTON, self._on_browse_folder)
        out_grid.Add(browse_btn, 0)

        out_grid.Add(wx.StaticText(panel, label="File Prefix:"), 0, wx.ALIGN_CENTER_VERTICAL)
        default_prefix = Path(board_path).stem if board_path else "pcb"
        self.prefix_ctrl = wx.TextCtrl(panel, value=default_prefix)
        out_grid.Add(self.prefix_ctrl, 1, wx.EXPAND)
        out_grid.Add(wx.StaticText(panel, label="(<prefix>_drill.nc, etc.)"), 0, wx.ALIGN_CENTER_VERTICAL)

        out_sizer.Add(out_grid, 0, wx.ALL | wx.EXPAND, 6)
        sizer.Add(out_sizer, 0, wx.ALL | wx.EXPAND, 6)

        box = wx.StaticBox(panel, label="Layers to Export")
        b_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        self.chk_f_cu = wx.CheckBox(panel, label="Front Copper (F.Cu) -> <prefix>_copper_front.nc")
        self.chk_f_cu.SetValue(self.settings.get("export_front_copper", False))
        self.chk_f_cu.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_preview(auto_fit=False))

        self.chk_b_cu = wx.CheckBox(panel, label="Back Copper (B.Cu) -> <prefix>_copper_back.nc")
        self.chk_b_cu.SetValue(self.settings.get("export_back_copper", True))
        self.chk_b_cu.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_preview(auto_fit=False))

        self.chk_drill = wx.CheckBox(panel, label="Drill Holes (PTH, NPTH, Vias) -> <prefix>_drill.nc")
        self.chk_drill.SetValue(self.settings.get("export_drill", True))
        self.chk_drill.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_preview(auto_fit=False))

        self.chk_cutout = wx.CheckBox(panel, label="Board Cutout Outline (Edge.Cuts) -> <prefix>_cutout.nc")
        self.chk_cutout.SetValue(self.settings.get("export_cutout", True))
        self.chk_cutout.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_preview(auto_fit=False))

        for chk in (self.chk_f_cu, self.chk_b_cu, self.chk_drill, self.chk_cutout):
            b_sizer.Add(chk, 0, wx.ALL, 4)

        sizer.Add(b_sizer, 0, wx.ALL | wx.EXPAND, 6)

        cu_quick_box = wx.StaticBox(panel, label="Copper Removal Mode & Spacing (Quick Access)")
        cu_quick_sizer = wx.StaticBoxSizer(cu_quick_box, wx.VERTICAL)

        self.iso_mode_choices = [
            ("single", "Single-Pass Trace Outline (Fastest — 1 cut around lines)"),
            ("multipass", "Custom Spacing in mm / Multi-Pass Isolation (Wider gap around lines)"),
            ("full_clear", "Remove 100% Rest Copper / Leave Only Lines (Full board copper rubout)"),
        ]
        self.quick_iso_mode_combo = wx.Choice(panel, choices=[desc for _, desc in self.iso_mode_choices])
        cur_iso_mode = self.settings.get("iso_mode", "multipass")
        iso_keys = [k for k, _ in self.iso_mode_choices]
        self.quick_iso_mode_combo.SetSelection(iso_keys.index(cur_iso_mode) if cur_iso_mode in iso_keys else 1)
        self.quick_iso_mode_combo.Bind(wx.EVT_CHOICE, self._on_quick_iso_mode_changed)

        cu_quick_sizer.Add(wx.StaticText(panel, label="What should happen to copper around your lines?"), 0, wx.ALL, 4)
        cu_quick_sizer.Add(self.quick_iso_mode_combo, 0, wx.EXPAND | wx.ALL, 4)

        sp_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        sp_btn_row.Add(wx.StaticText(panel, label="Quick Spacing:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        for mm_val, lbl in [
            (0.2, "0.2 mm (1p)"),
            (0.4, "0.4 mm"),
            (0.6, "0.6 mm"),
            (1.0, "1.0 mm"),
            (1.5, "1.5 mm"),
        ]:
            b_sp = wx.Button(panel, label=lbl, style=wx.BU_EXACTFIT)
            b_sp.Bind(wx.EVT_BUTTON, lambda evt, val=mm_val: self._set_quick_spacing_mm(val))
            sp_btn_row.Add(b_sp, 0, wx.RIGHT, 4)

        btn_full_clear = wx.Button(panel, label="Remove All Copper", style=wx.BU_EXACTFIT)
        btn_full_clear.Bind(wx.EVT_BUTTON, lambda evt: self._set_quick_full_clear())
        sp_btn_row.Add(btn_full_clear, 0)

        cu_quick_sizer.Add(sp_btn_row, 0, wx.ALL, 4)
        sizer.Add(cu_quick_sizer, 0, wx.ALL | wx.EXPAND, 6)

        orig_box = wx.StaticBox(panel, label="CNC Origin Reference (X=0, Y=0)")
        orig_sizer = wx.StaticBoxSizer(orig_box, wx.VERTICAL)

        self.origin_choices = [
            ("bottom_left", "Board Bottom-Left Corner (Recommended — board sits in +X, +Y)"),
            ("aux_origin", "KiCad Auxiliary / Drill Origin (User origin mark in PCB Editor)"),
            ("center", "Board Center (X=0, Y=0 at middle of PCB)"),
            ("top_left", "KiCad Top-Left Screen Origin"),
        ]
        self.origin_combo = wx.Choice(panel, choices=[desc for _, desc in self.origin_choices])
        current_mode = self.settings.get("origin_mode", "bottom_left")
        mode_keys = [k for k, _ in self.origin_choices]
        sel_idx = mode_keys.index(current_mode) if current_mode in mode_keys else 0
        self.origin_combo.SetSelection(sel_idx)
        self.origin_combo.Bind(wx.EVT_CHOICE, lambda e: self.refresh_preview(auto_fit=True))

        orig_sizer.Add(self.origin_combo, 0, wx.ALL | wx.EXPAND, 4)
        sizer.Add(orig_sizer, 0, wx.ALL | wx.EXPAND, 6)

        panel.SetSizer(sizer)
        return panel

    def _create_isolation_tab(self, parent):
        panel = wx.ScrolledWindow(parent)
        panel.SetScrollRate(5, 5)
        sizer = wx.BoxSizer(wx.VERTICAL)

        mode_box = wx.StaticBox(panel, label="Copper Milling Strategy")
        mode_sizer = wx.StaticBoxSizer(mode_box, wx.VERTICAL)

        self.iso_mode_combo = wx.Choice(panel, choices=[desc for _, desc in self.iso_mode_choices])
        cur_iso_mode = self.settings.get("iso_mode", "multipass")
        iso_keys = [k for k, _ in self.iso_mode_choices]
        self.iso_mode_combo.SetSelection(iso_keys.index(cur_iso_mode) if cur_iso_mode in iso_keys else 1)
        self.iso_mode_combo.Bind(wx.EVT_CHOICE, self._on_iso_mode_changed)

        mode_sizer.Add(self.iso_mode_combo, 0, wx.EXPAND | wx.ALL, 4)

        self.spacing_calc_lbl = wx.StaticText(panel, label="")
        self.spacing_calc_lbl.SetForegroundColour(wx.Colour(30, 130, 75))
        self.spacing_calc_lbl.SetFont(self.spacing_calc_lbl.GetFont().Bold())
        mode_sizer.Add(self.spacing_calc_lbl, 0, wx.ALL, 4)
        sizer.Add(mode_sizer, 0, wx.ALL | wx.EXPAND, 6)

        grid = wx.FlexGridSizer(cols=3, vgap=4, hgap=10)
        grid.AddGrowableCol(1)

        self._add_field(
            panel, grid, "iso_clearance_mm", "Target Copper Spacing:", "mm",
            "Desired copper-free isolation gap width around traces and pads in millimeters.",
            "Total gap width in mm around lines (automatically calculates required passes!).",
            on_change=self._on_spacing_param_edited,
        )
        self._add_field(
            panel, grid, "iso_tool_diameter", "V-Bit / Tool Tip Width:", "mm",
            "Effective cut width of engraving V-bit or micro-endmill at cutting depth.",
            "Width of a single tool cut (e.g. 0.2mm for standard V-bit, 0.1mm for fine SMD).",
            on_change=self._on_spacing_param_edited,
        )
        self._add_field(
            panel, grid, "iso_passes", "Minimum Passes:", "passes",
            "Minimum concentric isolation passes around traces.",
            "Number of passes (auto-increases if Target Copper Spacing in mm requires more).",
            on_change=self._on_spacing_param_edited,
        )
        self._add_field(
            panel, grid, "iso_pass_overlap", "Pass Overlap Ratio:", "0.1–0.85",
            "Overlap fraction between adjacent passes (0.5 = 50% overlap).",
            "Overlap between passes so no thin copper slivers remain (0.5 = 50%).",
            on_change=self._on_spacing_param_edited,
        )
        self._add_field(
            panel, grid, "iso_pad_extra_offset_mm", "Extra Trace/Pad Margin:", "mm",
            "Extra outward margin to preserve thicker copper traces/pads.",
            "Adds extra width to copper lines/pads before milling (0.0mm = exact KiCad size).",
        )
        self._add_field(
            panel, grid, "iso_depth", "Isolation Cut Depth:", "mm",
            "Engraving depth into copper layer (negative).",
            "Shallow cut through 35µm copper (typically -0.04 to -0.07 mm).",
        )
        self._add_field(
            panel, grid, "iso_z_step_mm", "Z Stepdown per Pass:", "mm",
            "Set to 0 for single Z pass, or >0 (e.g. 0.03) for multi-depth copper passes.",
            "0.0 = cut full copper depth at once; >0 splits depth into multiple Z passes.",
        )
        self._add_field(
            panel, grid, "iso_feed_xy", "Milling Feedrate XY:", "mm/min",
            "Horizontal engraving speed.",
            "Milling speed along tracks (typically 250 - 450 mm/min).",
        )
        self._add_field(
            panel, grid, "iso_feed_z", "Plunge Feedrate Z:", "mm/min",
            "Vertical plunge rate into copper.",
            "Gentle entry feedrate into copper (typically 80 - 150 mm/min).",
        )
        self._add_field(
            panel, grid, "iso_spindle_rpm", "Spindle Speed:", "RPM",
            "Spindle rotational speed for engraving.",
            "High RPM for clean, burr-free copper cuts (12000 - 20000 RPM).",
        )

        sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 6)

        clear_box = wx.StaticBox(panel, label="Full Copper Removal ('Leave Only Lines' / Rubout Options)")
        clear_sizer = wx.StaticBoxSizer(clear_box, wx.VERTICAL)

        self.chk_sep_clear_tool = wx.CheckBox(
            panel,
            label="Use a separate larger flat endmill for fast bulk copper clearing (2-Tool Rubout)",
        )
        self.chk_sep_clear_tool.SetValue(self.settings.get("iso_use_separate_clear_tool", False))
        self.chk_sep_clear_tool.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_preview(auto_fit=False))

        self.chk_sep_clear_file = wx.CheckBox(
            panel,
            label="Export bulk copper clearing to a separate file (<prefix>_copper_clear_*.nc) instead of M0 pause",
        )
        self.chk_sep_clear_file.SetValue(self.settings.get("iso_clear_separate_file", False))

        c_grid = wx.FlexGridSizer(cols=3, vgap=4, hgap=10)
        c_grid.AddGrowableCol(1)
        self._add_field(
            panel, c_grid, "iso_clear_tool_diameter", "Clearing Bit Diameter:", "mm",
            "Diameter of flat endmill used when 'Use separate larger flat endmill' is checked.",
            "Endmill size for bulk copper removal (e.g. 0.8mm or 1.0mm clears 4x faster!).",
        )
        self._add_field(
            panel, c_grid, "iso_clear_stepover", "Clearing Stepover Ratio:", "0.3–0.9",
            "Stepover fraction of tool diameter during full copper rubout (0.6 = 60% step).",
            "Stepover per clearing ring (0.6 = 60% of tool diameter).",
        )
        self._add_field(
            panel, c_grid, "iso_board_margin_mm", "Board Edge Margin:", "mm",
            "Safety inset from Edge.Cuts outline when clearing copper.",
            "Keeps copper clearing inside the board edge by this distance (e.g. 0.3mm).",
        )
        self._add_field(
            panel, c_grid, "iso_clear_feed_xy", "Clearing Feedrate XY:", "mm/min",
            "Horizontal feedrate during bulk copper clearing.",
            "Feedrate for pocket rubout passes (e.g. 400 - 600 mm/min).",
        )

        clear_sizer.Add(self.chk_sep_clear_tool, 0, wx.ALL, 4)
        clear_sizer.Add(self.chk_sep_clear_file, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        clear_sizer.Add(c_grid, 0, wx.ALL | wx.EXPAND, 4)
        sizer.Add(clear_sizer, 0, wx.ALL | wx.EXPAND, 6)

        m_box = wx.StaticBox(panel, label="Copper Orientation & Boundaries")
        m_sizer = wx.StaticBoxSizer(m_box, wx.VERTICAL)
        self.chk_mirror_b = wx.CheckBox(panel, label="Mirror Bottom Copper (B.Cu) horizontally across X axis")
        self.chk_mirror_b.SetValue(self.settings.get("iso_mirror_bottom", True))
        self.chk_mirror_b.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_preview(auto_fit=False))

        self.chk_clip_board = wx.CheckBox(panel, label="Clip multi-pass isolation offsets to stay inside Edge.Cuts board outline")
        self.chk_clip_board.SetValue(self.settings.get("iso_clip_to_board", True))
        self.chk_clip_board.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_preview(auto_fit=False))

        self.chk_climb = wx.CheckBox(panel, label="Reverse contour direction (Climb Milling)")
        self.chk_climb.SetValue(self.settings.get("iso_climb_milling", False))

        m_sizer.Add(self.chk_mirror_b, 0, wx.ALL, 3)
        m_sizer.Add(self.chk_clip_board, 0, wx.ALL, 3)
        m_sizer.Add(self.chk_climb, 0, wx.ALL, 3)
        sizer.Add(m_sizer, 0, wx.ALL | wx.EXPAND, 6)

        panel.SetSizer(sizer)
        return panel

    def _create_drill_tab(self, parent):
        panel = wx.ScrolledWindow(parent)
        panel.SetScrollRate(5, 5)
        sizer = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=3, vgap=4, hgap=10)
        grid.AddGrowableCol(1)

        self._add_field(
            panel, grid, "drill_safe_z", "Safe Z Height:", "mm",
            "Clearance height for rapid travel between holes.",
            "Z height above workpiece for rapid G0 moves (prevents clamp/surface collisions).",
        )
        self._add_field(
            panel, grid, "drill_depth", "Drill Depth:", "mm",
            "Total penetration depth through board (must be negative).",
            "Target depth through PCB into spoilboard (e.g. -1.8mm for 1.6mm FR4).",
        )
        self._add_field(
            panel, grid, "drill_feed_z", "Plunge Feedrate:", "mm/min",
            "Downward drilling speed into material.",
            "Feedrate entering PCB (typically 150-300 mm/min for carbide drill bits).",
        )
        self._add_field(
            panel, grid, "drill_spindle_rpm", "Spindle Speed:", "RPM",
            "Spindle rotational speed for drilling.",
            "High RPM recommended for small PCB bits (10000 - 15000 RPM).",
        )
        self._add_field(
            panel, grid, "drill_dwell", "Spindle Dwell:", "seconds",
            "Delay after M3 before drilling to let spindle spin up.",
            "Spin-up pause before the first plunge.",
        )

        sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 6)

        peck_box = wx.StaticBox(panel, label="Peck Drilling & Oblong Slot Pads")
        peck_sizer = wx.StaticBoxSizer(peck_box, wx.VERTICAL)
        self.chk_peck = wx.CheckBox(panel, label="Enable Peck Drilling Cycle (Chip-Clearing Retracts)")
        self.chk_peck.SetValue(self.settings.get("drill_peck_enabled", False))

        self.chk_mill_slots = wx.CheckBox(panel, label="Mill oblong/oval pad slots along their slot axis")
        self.chk_mill_slots.SetValue(self.settings.get("drill_mill_slots", True))
        self.chk_mill_slots.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_preview(auto_fit=False))

        peck_grid = wx.FlexGridSizer(cols=3, vgap=4, hgap=10)
        peck_grid.AddGrowableCol(1)
        self._add_field(
            panel, peck_grid, "drill_peck_depth", "Peck Increment:", "mm",
            "Step down depth per peck.",
            "Bit pecks down in steps and retracts to clear fiberglass swarf.",
        )
        peck_sizer.Add(self.chk_peck, 0, wx.ALL, 4)
        peck_sizer.Add(self.chk_mill_slots, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        peck_sizer.Add(peck_grid, 0, wx.ALL | wx.EXPAND, 4)
        sizer.Add(peck_sizer, 0, wx.ALL | wx.EXPAND, 6)

        mode_box = wx.StaticBox(panel, label="Multi-Tool Drill Handling")
        mode_sizer = wx.StaticBoxSizer(mode_box, wx.VERTICAL)

        self.tool_mode_radio_pause = wx.RadioButton(
            panel, label="Single combined .nc file with M0 pauses for bit changes", style=wx.RB_GROUP
        )
        self.tool_mode_radio_files = wx.RadioButton(
            panel, label="Export separate .nc file for each drill diameter (<prefix>_drill_0.8mm.nc, etc.)"
        )
        self.tool_mode_radio_single = wx.RadioButton(
            panel, label="Single tool for all holes (drill all with selected diameter)"
        )

        saved_tool_mode = self.settings.get("drill_tool_mode", "combined_pause")
        if saved_tool_mode == "separate_files":
            self.tool_mode_radio_files.SetValue(True)
        elif saved_tool_mode == "single_tool":
            self.tool_mode_radio_single.SetValue(True)
        else:
            self.tool_mode_radio_pause.SetValue(True)

        mode_sizer.Add(self.tool_mode_radio_pause, 0, wx.ALL, 3)
        mode_sizer.Add(self.tool_mode_radio_files, 0, wx.ALL, 3)
        mode_sizer.Add(self.tool_mode_radio_single, 0, wx.ALL, 3)

        mode_grid = wx.FlexGridSizer(cols=3, vgap=4, hgap=10)
        mode_grid.AddGrowableCol(1)
        self._add_field(
            panel, mode_grid, "drill_toolchange_z", "Tool Change Z Height:", "mm",
            "Retract height during M0 pause to allow swapping bits.",
            "High clearance height for manual drill bit changes.",
        )
        self._add_field(
            panel, mode_grid, "drill_single_diameter", "Single Tool Override:", "mm",
            "Used only when 'Single tool for all holes' is selected.",
            "Drill size to use if forcing all holes to a single bit.",
        )
        mode_sizer.Add(mode_grid, 0, wx.ALL | wx.EXPAND, 4)
        sizer.Add(mode_sizer, 0, wx.ALL | wx.EXPAND, 6)

        elem_box = wx.StaticBox(panel, label="Hole Types to Include")
        elem_sizer = wx.StaticBoxSizer(elem_box, wx.HORIZONTAL)
        self.chk_pth = wx.CheckBox(panel, label="Pads (PTH)")
        self.chk_pth.SetValue(self.settings.get("drill_include_pth", True))
        self.chk_npth = wx.CheckBox(panel, label="Mounting Holes (NPTH)")
        self.chk_npth.SetValue(self.settings.get("drill_include_npth", True))
        self.chk_vias = wx.CheckBox(panel, label="Vias")
        self.chk_vias.SetValue(self.settings.get("drill_include_vias", True))

        for chk in (self.chk_pth, self.chk_npth, self.chk_vias):
            chk.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_preview(auto_fit=False))
            elem_sizer.Add(chk, 0, wx.ALL, 6)

        sizer.Add(elem_sizer, 0, wx.ALL | wx.EXPAND, 6)

        panel.SetSizer(sizer)
        return panel

    def _create_cutout_tab(self, parent):
        panel = wx.ScrolledWindow(parent)
        panel.SetScrollRate(5, 5)
        sizer = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=3, vgap=4, hgap=10)
        grid.AddGrowableCol(1)

        self._add_field(
            panel, grid, "cutout_tool_diameter", "Endmill Diameter:", "mm",
            "Diameter of routing cutter bit.",
            "Toolpath is offset outwards by tool radius.",
        )
        self._add_field(
            panel, grid, "cutout_depth", "Total Cut Depth:", "mm",
            "Final cutout depth through board thickness (negative value).",
            "Through-cut depth (e.g. -1.8mm for 1.6mm board).",
        )
        self._add_field(
            panel, grid, "cutout_pass_depth", "Depth per Pass:", "mm",
            "Maximum stepdown per pass.",
            "Cut is split into multiple passes (e.g. 0.5mm).",
        )
        self._add_field(
            panel, grid, "cutout_feed_xy", "Cutting Feedrate XY:", "mm/min",
            "Horizontal cutting speed along board perimeter.",
            "Perimeter feedrate (typically 300 - 500 mm/min).",
        )
        self._add_field(
            panel, grid, "cutout_feed_z", "Plunge Feedrate Z:", "mm/min",
            "Vertical entry speed for each pass.",
            "Downfeed entering each depth level (100 - 200 mm/min).",
        )
        self._add_field(
            panel, grid, "cutout_spindle_rpm", "Spindle Speed:", "RPM",
            "Spindle rotational speed for routing.",
            "RPM for cutout (10000 - 15000 RPM).",
        )

        sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 6)

        tab_box = wx.StaticBox(panel, label="Holding Tabs / Bridges")
        tab_sizer = wx.StaticBoxSizer(tab_box, wx.VERTICAL)

        self.chk_tabs = wx.CheckBox(panel, label="Generate Holding Tabs (Shown in yellow in the 2D Preview)")
        self.chk_tabs.SetValue(self.settings.get("cutout_tabs_enabled", True))
        self.chk_tabs.Bind(wx.EVT_CHECKBOX, lambda e: self.refresh_preview(auto_fit=False))

        t_grid = wx.FlexGridSizer(cols=3, vgap=4, hgap=10)
        t_grid.AddGrowableCol(1)

        self._add_field(
            panel, t_grid, "cutout_tab_count", "Number of Tabs:", "tabs",
            "Total holding tabs spaced around perimeter.",
            "Evenly spaces tabs around the outer contour (e.g. 4 tabs).",
        )
        self._add_field(
            panel, t_grid, "cutout_tab_width", "Tab Width:", "mm",
            "Width of each holding tab bridge.",
            "Length of bridge along edge (typically 2.0 - 3.0 mm).",
        )
        self._add_field(
            panel, t_grid, "cutout_tab_height", "Tab Thickness:", "mm",
            "Height of bridge remaining at bottom.",
            "Bridge thickness remaining to hold board (e.g. 0.5 - 0.8 mm).",
        )

        tab_sizer.Add(self.chk_tabs, 0, wx.ALL, 4)
        tab_sizer.Add(t_grid, 0, wx.ALL | wx.EXPAND, 4)
        sizer.Add(tab_sizer, 0, wx.ALL | wx.EXPAND, 6)

        panel.SetSizer(sizer)
        return panel

    def _create_machine_tab(self, parent):
        panel = wx.ScrolledWindow(parent)
        panel.SetScrollRate(5, 5)
        sizer = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=3, vgap=4, hgap=10)
        grid.AddGrowableCol(1)

        self._add_field(
            panel, grid, "gcode_end_z", "Final Park Z Height:", "mm",
            "Z height the machine raises to after job completion.",
            "Safe parking clearance height upon M2 program end.",
        )
        sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 6)

        probe_box = wx.StaticBox(panel, label="Automatic Z-Zero Touch Probe (G38.2)")
        probe_sizer = wx.StaticBoxSizer(probe_box, wx.VERTICAL)
        self.chk_z_probe = wx.CheckBox(
            panel,
            label="Insert G38.2 Z-Probe touch sequence before copper milling",
        )
        self.chk_z_probe.SetValue(self.settings.get("gcode_z_probe", False))

        p_grid = wx.FlexGridSizer(cols=3, vgap=4, hgap=10)
        p_grid.AddGrowableCol(1)
        self._add_field(
            panel, p_grid, "gcode_probe_feed", "Probe Search Feed:", "mm/min",
            "Downward feedrate during G38.2 Z touch probing.",
            "Slow downward feedrate until bit touches copper surface (e.g. 50 mm/min).",
        )
        self._add_field(
            panel, p_grid, "gcode_probe_offset", "Probe Plate Offset:", "mm",
            "Z height set by G92 upon contact (0.0 if probing directly onto bare copper).",
            "0.0mm when alligator clip is on bit & copper clad; or plate thickness in mm.",
        )

        probe_sizer.Add(self.chk_z_probe, 0, wx.ALL, 4)
        probe_sizer.Add(p_grid, 0, wx.ALL | wx.EXPAND, 4)
        sizer.Add(probe_sizer, 0, wx.ALL | wx.EXPAND, 6)

        g_box = wx.StaticBox(panel, label="G-Code Compatibility")
        g_sizer = wx.StaticBoxSizer(g_box, wx.VERTICAL)
        compat_text = wx.StaticText(
            panel,
            label=(
                "Output files (.nc) work out-of-the-box with:\n"
                "  • GRBL 1.1 / Candle / OpenBuilds / Universal Gcode Sender (UGS)\n"
                "  • LinuxCNC & Mach3 / Mach4\n"
                "  • FluidNC / Marlin / Duet\n"
                "Coordinates are absolute (G90) in millimeters (G21) on the XY plane (G17)."
            ),
        )
        self._style_subtext(compat_text)
        g_sizer.Add(compat_text, 0, wx.ALL, 6)
        sizer.Add(g_sizer, 0, wx.ALL | wx.EXPAND, 6)

        panel.SetSizer(sizer)
        return panel

    def _style_subtext(self, text_ctrl):
        font = text_ctrl.GetFont()
        font.SetPointSize(max(7, font.GetPointSize() - 1))
        text_ctrl.SetFont(font)
        text_ctrl.SetForegroundColour(wx.Colour(105, 115, 125))

    def _update_preset_description(self, preset_id):
        preset = get_preset_by_id(preset_id)
        if preset:
            self.preset_desc_lbl.SetLabel(f"Preset Info: {preset['description']}")
        else:
            self.preset_desc_lbl.SetLabel(
                "Custom Mode: You have customized individual parameters. Click any preset above to load a standard profile."
            )

    def _on_preset_combo(self, event):
        idx = self.preset_combo.GetSelection()
        if idx < 0:
            return
        preset_id = self.preset_choices[idx][0]
        if preset_id != "custom":
            self.apply_preset(preset_id)
        else:
            self._update_preset_description("custom")

    def apply_preset(self, preset_id):
        """Apply all settings from a preset into the UI controls and refresh preview."""
        preset = get_preset_by_id(preset_id)
        if not preset:
            return

        self._updating_ui = True
        try:
            self.settings["active_preset"] = preset_id
            for k, v in preset["settings"].items():
                self.settings[k] = v

            preset_ids = [pid for pid, _ in self.preset_choices]
            if preset_id in preset_ids:
                self.preset_combo.SetSelection(preset_ids.index(preset_id))
            self._update_preset_description(preset_id)

            self.chk_f_cu.SetValue(bool(self.settings.get("export_front_copper", False)))
            self.chk_b_cu.SetValue(bool(self.settings.get("export_back_copper", True)))
            self.chk_drill.SetValue(bool(self.settings.get("export_drill", True)))
            self.chk_cutout.SetValue(bool(self.settings.get("export_cutout", True)))
            self.chk_peck.SetValue(bool(self.settings.get("drill_peck_enabled", False)))
            self.chk_tabs.SetValue(bool(self.settings.get("cutout_tabs_enabled", True)))
            self.chk_sep_clear_tool.SetValue(bool(self.settings.get("iso_use_separate_clear_tool", False)))
            self.chk_sep_clear_file.SetValue(bool(self.settings.get("iso_clear_separate_file", False)))

            iso_mode = self.settings.get("iso_mode", "multipass")
            iso_keys = [k for k, _ in self.iso_mode_choices]
            mode_idx = iso_keys.index(iso_mode) if iso_mode in iso_keys else 1
            self.iso_mode_combo.SetSelection(mode_idx)
            self.quick_iso_mode_combo.SetSelection(mode_idx)

            for key, ctrl in self._controls.items():
                if key in self.settings:
                    ctrl.ChangeValue(str(self.settings[key]))
        finally:
            self._updating_ui = False

        self._sync_spacing_summary()
        self.refresh_preview(auto_fit=False)

    def _on_quick_iso_mode_changed(self, event):
        idx = self.quick_iso_mode_combo.GetSelection()
        self.iso_mode_combo.SetSelection(idx)
        self._sync_spacing_summary()
        self.refresh_preview(auto_fit=False)

    def _on_iso_mode_changed(self, event):
        idx = self.iso_mode_combo.GetSelection()
        self.quick_iso_mode_combo.SetSelection(idx)
        self._sync_spacing_summary()
        self.refresh_preview(auto_fit=False)

    def _set_quick_spacing_mm(self, spacing_mm):
        """Quick button handler to set target isolation spacing in mm."""
        self._updating_ui = True
        try:
            mode = "single" if spacing_mm <= 0.21 else "multipass"
            iso_keys = [k for k, _ in self.iso_mode_choices]
            idx = iso_keys.index(mode)
            self.iso_mode_combo.SetSelection(idx)
            self.quick_iso_mode_combo.SetSelection(idx)
            self._controls["iso_clearance_mm"].ChangeValue(f"{spacing_mm:.2f}")
            try:
                tool_dia = float(self._controls["iso_tool_diameter"].GetValue().replace(",", "."))
                overlap = float(self._controls["iso_pass_overlap"].GetValue().replace(",", "."))
            except ValueError:
                tool_dia, overlap = 0.2, 0.5
            n_passes, _, _ = calculate_isolation_passes(tool_dia, spacing_mm, 1, overlap)
            self._controls["iso_passes"].ChangeValue(str(n_passes))
        finally:
            self._updating_ui = False
        self._sync_spacing_summary()
        self.refresh_preview(auto_fit=False)

    def _set_quick_full_clear(self):
        """Quick button handler to switch to Remove 100% Rest Copper (Leave Only Lines)."""
        iso_keys = [k for k, _ in self.iso_mode_choices]
        idx = iso_keys.index("full_clear")
        self.iso_mode_combo.SetSelection(idx)
        self.quick_iso_mode_combo.SetSelection(idx)
        self._sync_spacing_summary()
        self.refresh_preview(auto_fit=False)

    def _on_spacing_param_edited(self, event):
        if self._updating_ui:
            return
        self._sync_spacing_summary()

    def _sync_spacing_summary(self):
        """Update the live summary banner explaining the exact isolation width and pass count."""
        try:
            tool_dia = float(self._controls["iso_tool_diameter"].GetValue().strip().replace(",", "."))
            clearance_mm = float(self._controls["iso_clearance_mm"].GetValue().strip().replace(",", "."))
            min_passes = int(float(self._controls["iso_passes"].GetValue().strip().replace(",", ".")))
            overlap = float(self._controls["iso_pass_overlap"].GetValue().strip().replace(",", "."))
        except Exception:
            return

        iso_mode = self.iso_mode_choices[self.iso_mode_combo.GetSelection()][0]
        if iso_mode == "single":
            self.spacing_calc_lbl.SetLabel(
                f"Active Strategy: 1 pass with {tool_dia:.2f} mm tool = {tool_dia:.2f} mm copper gap around lines."
            )
        elif iso_mode == "multipass":
            n_passes, step_mm, eff_mm = calculate_isolation_passes(tool_dia, clearance_mm, min_passes, overlap)
            self.spacing_calc_lbl.SetLabel(
                f"Active Strategy: {n_passes} concentric passes (step {step_mm:.2f} mm) = {eff_mm:.2f} mm total copper-free gap around lines."
            )
        else:
            self.spacing_calc_lbl.SetLabel(
                "Active Strategy: Leave Only Lines — 100% of remaining copper across the board will be milled away!"
            )

    def _on_browse_folder(self, event):
        dlg = wx.DirDialog(self, "Choose G-Code Output Directory", defaultPath=self.folder_ctrl.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            self.folder_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def get_form_values(self):
        """Read and validate all values from the form."""
        opts = dict(self.settings)

        preset_idx = self.preset_combo.GetSelection()
        if preset_idx >= 0:
            opts["active_preset"] = self.preset_choices[preset_idx][0]

        opts["export_drill"] = self.chk_drill.GetValue()
        opts["export_cutout"] = self.chk_cutout.GetValue()
        opts["export_front_copper"] = self.chk_f_cu.GetValue()
        opts["export_back_copper"] = self.chk_b_cu.GetValue()

        sel_idx = self.origin_combo.GetSelection()
        opts["origin_mode"] = self.origin_choices[sel_idx][0]

        iso_idx = self.iso_mode_combo.GetSelection()
        opts["iso_mode"] = self.iso_mode_choices[iso_idx][0]

        if self.tool_mode_radio_files.GetValue():
            opts["drill_tool_mode"] = "separate_files"
        elif self.tool_mode_radio_single.GetValue():
            opts["drill_tool_mode"] = "single_tool"
        else:
            opts["drill_tool_mode"] = "combined_pause"

        opts["drill_peck_enabled"] = self.chk_peck.GetValue()
        opts["drill_mill_slots"] = self.chk_mill_slots.GetValue()
        opts["drill_include_pth"] = self.chk_pth.GetValue()
        opts["drill_include_npth"] = self.chk_npth.GetValue()
        opts["drill_include_vias"] = self.chk_vias.GetValue()
        opts["cutout_tabs_enabled"] = self.chk_tabs.GetValue()
        opts["iso_mirror_bottom"] = self.chk_mirror_b.GetValue()
        opts["iso_clip_to_board"] = self.chk_clip_board.GetValue()
        opts["iso_climb_milling"] = self.chk_climb.GetValue()
        opts["iso_use_separate_clear_tool"] = self.chk_sep_clear_tool.GetValue()
        opts["iso_clear_separate_file"] = self.chk_sep_clear_file.GetValue()
        opts["gcode_z_probe"] = self.chk_z_probe.GetValue()

        int_keys = {"drill_spindle_rpm", "cutout_spindle_rpm", "iso_spindle_rpm", "cutout_tab_count", "iso_passes"}
        for key, ctrl in self._controls.items():
            text = ctrl.GetValue().strip().replace(",", ".")
            try:
                if key in int_keys:
                    opts[key] = int(float(text))
                else:
                    opts[key] = float(text)
            except ValueError:
                raise ValueError(f"Invalid numeric value for '{key}': {text!r}")

        return opts

    def refresh_preview(self, auto_fit=False):
        """Extract current toolpaths and update the interactive 2D preview and job stats."""
        try:
            opts = self.get_form_values()
        except ValueError:
            return

        origin_mode = opts["origin_mode"]
        side_mode = self.preview_panel.get_selected_side_mode()

        if side_mode == "front":
            preview_layer = pcbnew.F_Cu
            layer_label = "Front Copper (F.Cu)"
            mirror_x = False
        elif side_mode == "back":
            preview_layer = pcbnew.B_Cu
            mirror_x = bool(opts.get("iso_mirror_bottom", True))
            layer_label = "Back Copper (B.Cu - Mirrored)" if mirror_x else "Back Copper (B.Cu)"
        else:
            if opts["export_front_copper"] and not opts["export_back_copper"]:
                preview_layer = pcbnew.F_Cu
                layer_label = "Front Copper (F.Cu)"
                mirror_x = False
            else:
                preview_layer = pcbnew.B_Cu
                mirror_x = bool(opts.get("iso_mirror_bottom", True))
                layer_label = "Back Copper (B.Cu - Mirrored)" if mirror_x else "Back Copper (B.Cu)"

        board_outer, board_inner = extract_board_outline_cnc(
            self.board, self.board_info, origin_mode=origin_mode, mirror_x=mirror_x
        )

        copper_regions = extract_copper_polygons_cnc(
            self.board,
            self.board_info,
            preview_layer,
            origin_mode=origin_mode,
            mirror_x=mirror_x,
            extra_margin_mm=opts.get("iso_pad_extra_offset_mm", 0.0),
        )

        iso_loops, clear_loops = [], []
        if opts["export_front_copper"] or opts["export_back_copper"] or side_mode in ("front", "back"):
            iso_loops, clear_loops = extract_copper_toolpaths(
                self.board,
                self.board_info,
                preview_layer,
                settings=opts,
                origin_mode=origin_mode,
                mirror_x=mirror_x,
            )

        cutout_outer, cutout_inner, tab_bridges = [], [], []
        if opts["export_cutout"]:
            cutout_outer, cutout_inner = extract_board_cutout_polygons(
                self.board, self.board_info, opts["cutout_tool_diameter"], origin_mode=origin_mode
            )
            if opts["cutout_tabs_enabled"] and opts["cutout_tab_count"] > 0:
                for loop in cutout_outer:
                    tab_bridges.extend(
                        extract_cutout_tab_bridges(loop, opts["cutout_tab_count"], opts["cutout_tab_width"])
                    )

        holes = []
        drill_groups = []
        if opts["export_drill"]:
            holes = extract_drill_holes(self.board, self.board_info, opts)
            single_d = opts["drill_single_diameter"] if opts["drill_tool_mode"] == "single_tool" else None
            drill_groups = group_and_optimize_holes(holes, start_pos=(0.0, 0.0), single_diameter=single_d)

        clear_dia = opts["iso_clear_tool_diameter"] if opts.get("iso_use_separate_clear_tool") else opts["iso_tool_diameter"]

        self.preview_panel.update_preview_data(
            {
                "board_outer": board_outer,
                "board_inner": board_inner,
                "copper_regions": copper_regions,
                "iso_loops": iso_loops,
                "clear_loops": clear_loops,
                "cutout_outer": cutout_outer,
                "cutout_inner": cutout_inner,
                "tab_bridges": tab_bridges,
                "drill_groups": drill_groups,
                "all_holes": holes,
                "iso_tool_dia": opts["iso_tool_diameter"],
                "clear_tool_dia": clear_dia,
                "cutout_tool_dia": opts["cutout_tool_diameter"],
                "layer_label": layer_label,
                "iso_mode": opts["iso_mode"],
            },
            auto_fit=auto_fit,
        )

        stats = estimate_job_statistics(
            drill_groups=drill_groups,
            cutout_outer=cutout_outer,
            cutout_inner=cutout_inner,
            f_iso_loops=iso_loops if preview_layer == pcbnew.F_Cu else [],
            f_clear_loops=clear_loops if preview_layer == pcbnew.F_Cu else [],
            b_iso_loops=iso_loops if preview_layer == pcbnew.B_Cu else [],
            b_clear_loops=clear_loops if preview_layer == pcbnew.B_Cu else [],
            settings=opts,
        )
        est_min = int(stats["estimated_seconds"] // 60)
        est_sec = int(stats["estimated_seconds"] % 60)
        w = self.board_info["width"]
        h = self.board_info["height"]
        total_contours = stats["iso_contour_count"] + stats["clear_contour_count"]
        self.job_stats_lbl.SetLabel(
            f"Board: {w:.1f}×{h:.1f} mm  |  Holes: {stats['hole_count']}  |  "
            f"Copper Contours: {total_contours}  |  Cut Path: {stats['cut_distance_mm']:.0f} mm  |  "
            f"Est. Time: ~{est_min}m {est_sec:02d}s"
        )


def _export_copper_layer(board, board_info, layer_id, layer_title, file_tag, prefix, out_dir, origin_desc, opts, mirror_x):
    """Helper to export front or back copper isolation and optional separate clearing file."""
    iso_loops, clear_loops = extract_copper_toolpaths(
        board,
        board_info,
        layer_id,
        settings=opts,
        origin_mode=opts["origin_mode"],
        mirror_x=mirror_x,
    )
    if not iso_loops and not clear_loops:
        return [], f"• {layer_title}: No copper elements found."

    exported = []
    ext = opts.get("gcode_file_extension", ".nc")
    use_sep_file = bool(opts.get("iso_use_separate_clear_tool", False)) and bool(opts.get("iso_clear_separate_file", False))

    if use_sep_file and clear_loops:
        iso_file = out_dir / f"{prefix}_copper_{file_tag}{ext}"
        iso_gcode = generate_copper_isolation_gcode(iso_loops, layer_title, origin_desc, opts, clearing_loops=None)
        iso_file.write_text(iso_gcode, encoding="utf-8")
        exported.append(str(iso_file))

        clear_file = out_dir / f"{prefix}_copper_clear_{file_tag}{ext}"
        clear_gcode = generate_copper_isolation_gcode([], f"{layer_title} — Bulk Rubout", origin_desc, opts, clearing_loops=clear_loops)
        clear_file.write_text(clear_gcode, encoding="utf-8")
        exported.append(str(clear_file))

        summary = (
            f"• {layer_title}: {len(iso_loops)} isolation contours + {len(clear_loops)} clearing passes "
            f"-> {iso_file.name}, {clear_file.name}"
        )
    else:
        out_file = out_dir / f"{prefix}_copper_{file_tag}{ext}"
        gcode = generate_copper_isolation_gcode(iso_loops, layer_title, origin_desc, opts, clearing_loops=clear_loops)
        out_file.write_text(gcode, encoding="utf-8")
        exported.append(str(out_file))

        extra_info = f" + {len(clear_loops)} rubout passes" if clear_loops else ""
        mirror_str = " (Mirrored X)" if mirror_x else ""
        summary = f"• {layer_title}: {len(iso_loops)} isolation contours{extra_info}{mirror_str} -> {out_file.name}"

    return exported, summary


def execute_export(board, dialog):
    """Run export pipeline based on dialog options."""
    try:
        opts = dialog.get_form_values()
    except ValueError as e:
        wx.MessageBox(str(e), "Input Error", wx.OK | wx.ICON_ERROR)
        return False

    if not any([opts["export_drill"], opts["export_cutout"], opts["export_front_copper"], opts["export_back_copper"]]):
        wx.MessageBox(
            "Please select at least one layer to export (Drill, Cutout, or Copper).",
            "No Layers Selected",
            wx.OK | wx.ICON_WARNING,
        )
        return False

    out_dir = Path(dialog.folder_ctrl.GetValue().strip())
    if not out_dir.exists():
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            wx.MessageBox(f"Failed to create output directory:\n{e}", "File Error", wx.OK | wx.ICON_ERROR)
            return False

    prefix = dialog.prefix_ctrl.GetValue().strip() or "pcb"
    ext = opts.get("gcode_file_extension", ".nc")
    board_info = get_board_info(board)
    origin_desc = [desc for k, desc in dialog.origin_choices if k == opts["origin_mode"]][0]

    exported_files = []
    stats_lines = []

    if opts["export_drill"]:
        holes = extract_drill_holes(board, board_info, opts)
        if not holes:
            stats_lines.append("• Drill: No matching holes found on board.")
        else:
            single_d = opts["drill_single_diameter"] if opts["drill_tool_mode"] == "single_tool" else None
            groups = group_and_optimize_holes(holes, start_pos=(0.0, 0.0), single_diameter=single_d)

            if opts["drill_tool_mode"] == "separate_files":
                for dia, pts in groups:
                    dia_str = f"{dia:.2f}".replace(".", "_")
                    filename = f"{prefix}_drill_{dia_str}mm{ext}"
                    filepath = out_dir / filename
                    gcode = generate_drill_gcode([(dia, pts)], origin_desc, opts, is_single_group_file=True, all_holes=holes)
                    filepath.write_text(gcode, encoding="utf-8")
                    exported_files.append(str(filepath))
                stats_lines.append(f"• Drill: {len(holes)} holes across {len(groups)} separate {ext} files.")
            else:
                filename = f"{prefix}_drill{ext}"
                filepath = out_dir / filename
                gcode = generate_drill_gcode(groups, origin_desc, opts, is_single_group_file=False, all_holes=holes)
                filepath.write_text(gcode, encoding="utf-8")
                exported_files.append(str(filepath))
                summary_str = ", ".join(f"{len(pts)}x {d:.2f}mm" for d, pts in groups)
                stats_lines.append(f"• Drill: {len(holes)} holes ({summary_str}) -> {filename}")

    if opts["export_cutout"]:
        outer_loops, inner_loops = extract_board_cutout_polygons(
            board, board_info, opts["cutout_tool_diameter"], opts["origin_mode"]
        )
        if not outer_loops:
            stats_lines.append("• Cutout: Could not extract board outline from Edge.Cuts.")
        else:
            filename = f"{prefix}_cutout{ext}"
            filepath = out_dir / filename
            gcode = generate_cutout_gcode(outer_loops, inner_loops, origin_desc, opts)
            filepath.write_text(gcode, encoding="utf-8")
            exported_files.append(str(filepath))
            tabs_info = f"with {opts['cutout_tab_count']} tabs" if opts["cutout_tabs_enabled"] else "no tabs"
            stats_lines.append(
                f"• Cutout: {len(outer_loops)} outer loop(s), {len(inner_loops)} slot(s) ({tabs_info}) -> {filename}"
            )

    if opts["export_front_copper"]:
        files, summary = _export_copper_layer(
            board, board_info, pcbnew.F_Cu, "Front Copper (F.Cu)", "front", prefix, out_dir, origin_desc, opts, mirror_x=False
        )
        exported_files.extend(files)
        stats_lines.append(summary)

    if opts["export_back_copper"]:
        mirror = bool(opts.get("iso_mirror_bottom", True))
        files, summary = _export_copper_layer(
            board, board_info, pcbnew.B_Cu, "Back Copper (B.Cu)", "back", prefix, out_dir, origin_desc, opts, mirror_x=mirror
        )
        exported_files.extend(files)
        stats_lines.append(summary)

    if dialog.save_defaults_chk.GetValue():
        save_settings(opts)

    msg = (
        "G-Code export completed successfully!\n\n"
        + "\n".join(stats_lines)
        + f"\n\nFiles saved in:\n{out_dir}\n\n"
        + "Generated files:\n"
        + "\n".join(f"  • {Path(f).name}" for f in exported_files)
    )
    wx.MessageBox(msg, "Export Complete", wx.OK | wx.ICON_INFORMATION)
    return True
