"""ActionPlugin entry point for KiCad."""

import os
import pcbnew
import wx

from .dialog import GCodeExportDialog, execute_export

PLUGIN_NAME = "Export PCB to G-Code (.nc)"


class PcbToGCodePlugin(pcbnew.ActionPlugin):
    """KiCad ActionPlugin providing top menu bar and toolbar access."""

    def defaults(self):
        self.name = PLUGIN_NAME
        self.category = "Manufacturing"
        self.description = "Export drill holes, board cutout outline, and copper isolation to CNC G-code (.nc)"
        self.show_toolbar_button = True
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        self.icon_file_name = icon_path if os.path.isfile(icon_path) else ""

    def Run(self):
        try:
            board = pcbnew.GetBoard()
            if not board:
                wx.MessageBox("No active PCB board found in KiCad.", "Error", wx.OK | wx.ICON_ERROR)
                return

            dlg = GCodeExportDialog(None, board)
            try:
                if dlg.ShowModal() == wx.ID_OK:
                    execute_export(board, dlg)
            finally:
                dlg.Destroy()

        except Exception as e:
            wx.MessageBox(
                f"An unexpected error occurred in {PLUGIN_NAME}:\n\n{e}",
                f"{PLUGIN_NAME} — Error",
                wx.OK | wx.ICON_ERROR,
            )
