# KiCad PCB to CNC G-Code Exporter (.nc) — v2.0

A high-precision KiCad Action Plugin that exports your PCB directly to CNC G-code (`.nc`) for **copper isolation**, **full excess copper removal ("Leave Only Lines")**, **multi-pass custom spacing in `mm`**, **drilling (including oblong slots)**, and **board cutout with holding tabs**—complete with an **Interactive Live 2D Preview** and **One-Click Mode Presets**.

Integrated directly into the **KiCad Top Menu Bar** and **Top Toolbar**.

---

## What's New & Key Features

- **7 Built-In One-Click Mode Presets**:
  1. **Leave Only Lines (Remove 100% Rest Copper)** — Completely mills away all unused copper across the entire board so only your tracks and pads remain on bare FR4.
  2. **Good Isolation (0.6 mm Easy-Solder Spacing)** — Multi-pass isolation creating a wide `0.6 mm` copper-free trench around every trace and pad to prevent solder bridges.
  3. **Extra-Wide Isolation (1.2 mm High-Clearance Moat)** — Wide `1.2 mm` copper-free moat for power electronics, mains/high-voltage clearance, or effortless beginner soldering.
  4. **Fast Standard Isolation (Single 0.2 mm Pass)** — Fastest machining time with 1 crisp pass around traces.
  5. **Fast 2-Tool Full Rubout (0.2 mm V-Bit + 0.8 mm Flat Endmill)** — Uses a fine `0.2 mm` V-bit for crisp trace details and a `0.8 mm` flat endmill to clear all remaining copper 4× faster.
  6. **Fine-Pitch SMD Precision (0.1 mm V-Bit + Peck Drill)** — Tuned for dense SMD ICs, thin traces, shallow `-0.04 mm` depth, and peck drilling.
  7. **Drill & Cutout Only** — Skips copper milling and exports optimized drill holes and board cutout with holding tabs.

- **Interactive Live 2D CNC & PCB Preview**:
  - **Real-Time Canvas**: Zoom with the mouse wheel, pan by dragging, and double-click to fit the board.
  - **Visual Layers**: Inspect remaining metallic copper pads/traces, cyan isolation passes, green bulk copper clearing (rubout) paths, orange cutout paths, yellow holding tab bridges, true-scale drill holes, rapid `G0` moves, and the `(0,0)` origin crosshair.
  - **Live Job Estimator**: Displays board dimensions, hole & contour counts, total cutting distance in `mm`, and estimated CNC run time (`~Xm Ys`).

- **Complete Copper Control**:
  - **Target Copper Spacing in `mm`**: Enter your desired gap width in millimeters (e.g. `0.4 mm`, `0.6 mm`, `1.0 mm`, `1.5 mm`) and the plugin automatically computes the exact number of concentric passes needed for your tool diameter and overlap ratio.
  - **Remove 100% Rest Copper ("Leave Only Lines")**: Full pocket clearing inside `Edge.Cuts` with configurable board edge margin, stepover ratio, and single-tool or 2-tool rubout support.
  - **Extra Trace/Pad Margin (`mm`)**: Optional outward offset to keep traces/annular rings thicker if desired.
  - **Multi-Pass Z Stepdown & Climb Milling**: Optional Z stepdown per copper pass and climb/conventional milling toggle.

- **High-Precision Drilling & Board Cutout**:
  - **Oblong / Oval Slot Pad Milling**: Automatically detects oblong/slot pads and mills along their slot axis.
  - **Nearest-Neighbor TSP Optimization**: Minimizes rapid non-cutting travel distance.
  - **Peck Drilling Cycle**: Chip-clearing retracts to protect fragile carbide bits (`0.4 mm – 1.0 mm`).
  - **Holding Tabs (Bridges)**: Configurable tab count, width, and thickness, highlighted directly in the 2D preview.
  - **Automatic Z-Zero Touch Probe (`G38.2`)**: Optional Z-probe sequence before copper milling.

---

## Quick Installation

### Linux & macOS

```bash
./install.sh
```

Or run directly with Python:

```bash
python3 install.py
```

Options:
- `./install.sh --symlink` : Creates symbolic links (updates automatically as you edit files).
- `./install.sh --all`     : Installs into all detected KiCad versions.
- `./install.sh --uninstall`: Cleanly removes the plugin.

### Windows

```bat
python install.py
```

---

## Automated Testing

Run the verification suite (tests all 7 presets, multi-pass spacing in `mm`, full copper rubout, oblong slots, cutout tab bridges, and the wxPython 2D Preview UI):

```bash
python3 test_exporter.py
```

---

## License

MIT License.
