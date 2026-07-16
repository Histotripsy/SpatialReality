"""
SRD unit / magnification ruler test.

Draws a measurable millimeter ruler (+ tick marks and a 10 mm reference
square) so you can verify that ``units`` / ``display_magnification`` map to
the expected size on the Spatial Reality Display.

Run::

    python examples/ruler_test.py
    python examples/ruler_test.py --magnification 1          # true physical scale
    python examples/ruler_test.py --magnification 10         # 1 mm -> 1 cm on SRD
    python examples/ruler_test.py --units mm --length 20

What to measure on the SRD
--------------------------
With ``units='mm'`` and ``display_magnification=M``:

    physical_cm_on_SRD = (ruler_mm / 10) * M

Examples (default ruler length = 10 mm):

| magnification | 10 mm ruler appears as |
|---------------|------------------------|
| 1             | 1.0 cm                 |
| 10            | 10.0 cm                |
| 15            | 15.0 cm                |

Hold a real ruler / calipers up to the stereo image (best along the screen
horizontal) and compare.  Keys: ``1``/``2``/``3`` set mag to 1 / 10 / 15,
``+/-`` nudge mag, ``R`` reset camera, ``Esc`` quit.
"""

from __future__ import annotations

import argparse
import signal

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PyQt5 import QtCore, QtWidgets

from pathlib import Path
import sys
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from spatial_reality.gl import resolve_world_scale
from spatial_reality.gl import SRDAppAbstract


def build_ruler_mm(
    length_mm: float = 10.0,
    major_every_mm: float = 5.0,
    minor_every_mm: float = 1.0,
    axis: str = "x",
) -> list:
    """
    Build GL line items for a ruler along +axis from 0 to length_mm.

    Tick heights: minor=0.4 mm, mid(5)=0.8 mm, major(10)=1.2 mm (in scene mm).
    Also draws a 10 mm reference square in the XY plane and a filled end-cap
    scatter at 0 and length for easy stereo aiming.
    """
    items = []
    length_mm = float(length_mm)
    axis = axis.lower()
    if axis not in ("x", "y", "z"):
        raise ValueError("axis must be x, y, or z")

    def _pt(a, b=0.0, c=0.0):
        if axis == "x":
            return (a, b, c)
        if axis == "y":
            return (b, a, c)
        return (b, c, a)

    # Baseline
    base = [_pt(0.0), _pt(length_mm)]
    # GLLinePlotItem mode='lines' wants pairs; use line_strip via consecutive pts
    items.append(
        gl.GLLinePlotItem(
            pos=np.asarray(base, dtype=np.float32),
            color=(1.0, 1.0, 1.0, 1.0),
            width=3.0,
            antialias=True,
            mode="line_strip",
        )
    )

    # Tick marks (pairs for mode='lines')
    tick_pairs = []
    tick_colors = []
    n = int(round(length_mm / minor_every_mm))
    for i in range(n + 1):
        t = i * minor_every_mm
        if abs(t - round(t / major_every_mm) * major_every_mm) < 1e-6 and t > 0:
            h = 1.2
            col = (1.0, 0.85, 0.2, 1.0)  # major — yellow
        elif abs(t - round(t / 5.0) * 5.0) < 1e-6 and t > 0:
            h = 0.8
            col = (0.4, 0.9, 1.0, 1.0)  # 5 mm — cyan
        else:
            h = 0.4
            col = (0.75, 0.75, 0.75, 1.0)
        tick_pairs.extend([_pt(t, 0.0, 0.0), _pt(t, h, 0.0)])
        tick_colors.extend([col, col])

    items.append(
        gl.GLLinePlotItem(
            pos=np.asarray(tick_pairs, dtype=np.float32),
            color=np.asarray(tick_colors, dtype=np.float32),
            width=2.0,
            antialias=True,
            mode="lines",
        )
    )

    # 10 mm reference square in XY (or plane spanned by axis + Y-like)
    sq = 10.0
    if axis == "x":
        square = [(0, 0, 0), (sq, 0, 0), (sq, sq, 0), (0, sq, 0), (0, 0, 0)]
    elif axis == "y":
        square = [(0, 0, 0), (0, sq, 0), (sq, sq, 0), (sq, 0, 0), (0, 0, 0)]
    else:
        square = [(0, 0, 0), (0, 0, sq), (0, sq, sq), (0, sq, 0), (0, 0, 0)]
    items.append(
        gl.GLLinePlotItem(
            pos=np.asarray(square, dtype=np.float32),
            color=(0.2, 1.0, 0.4, 1.0),
            width=2.5,
            antialias=True,
            mode="line_strip",
        )
    )

    # End markers as world-space spheres (pxMode=False) — diameter 0.6 mm
    ends = np.asarray([_pt(0.0), _pt(length_mm)], dtype=np.float32)
    cols = np.asarray([[1, 0.2, 0.2, 1], [0.2, 0.4, 1, 1]], dtype=np.float32)
    items.append(
        gl.GLScatterPlotItem(pos=ends, color=cols, size=0.6, pxMode=False)
    )
    return items


class RulerTest(SRDAppAbstract):
    def __init__(self, length_mm=10.0, *args, **kwargs):
        kwargs.setdefault("units", "mm")
        kwargs.setdefault("display_magnification", 10.0)
        kwargs.setdefault("render_scale", 0.5)
        kwargs.setdefault("show_preview", True)
        super().__init__(*args, **kwargs)
        self.length_mm = float(length_mm)
        self._timer = None

    def _setupWindow(self):
        for item in build_ruler_mm(self.length_mm):
            self.win.addItem(item)

        # Light grid for depth reference (1 mm cells, 20 mm extent)
        grid = gl.GLGridItem()
        grid.setSize(20, 20)
        grid.setSpacing(1, 1)
        grid.translate(self.length_mm * 0.5, 0, -0.01)
        grid.setColor((0.25, 0.25, 0.25, 0.6))
        self.win.addItem(grid)

        self.win.setCameraPosition(distance=40, elevation=25, azimuth=45)
        self.win.opts["center"] = pg.Vector(self.length_mm * 0.5, 0, 0)
        self.win.opts["fov"] = 30
        self._print_scale_help()

        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _expected_cm(self, mm: float) -> float:
        # units mm → cm factor 0.1, then * magnification
        return (mm * 0.1) * float(self.display_magnification)

    def _print_scale_help(self) -> None:
        ws = resolve_world_scale(self.units, self.display_magnification)
        print()
        print("=" * 60)
        print("SRD ruler scale check")
        print("=" * 60)
        print(f"  units                 = {self.units!r}")
        print(f"  display_magnification = {self.display_magnification}")
        print(f"  world_scale           = {ws}  (model → SRD cm)")
        print(f"  ruler length          = {self.length_mm:g} mm")
        print(
            f"  => full ruler should measure "
            f"{self._expected_cm(self.length_mm):.2f} cm on the SRD"
        )
        print(
            f"  => green 10 mm square should measure "
            f"{self._expected_cm(10.0):.2f} cm on a side"
        )
        print(
            f"  => major yellow ticks every 5 mm → "
            f"{self._expected_cm(5.0):.2f} cm apart"
        )
        print("  Keys: 1/2/3 = mag 1/10/15,  +/- = nudge mag,  R = reset cam")
        print("=" * 60)
        print()

    def _tick(self):
        self.present_to_srd()

    def keyPressEvent(self, ev):
        key = ev.key()
        changed = False
        if key == QtCore.Qt.Key_1:
            self.set_world_transform(display_magnification=1.0)
            changed = True
        elif key == QtCore.Qt.Key_2:
            self.set_world_transform(display_magnification=10.0)
            changed = True
        elif key == QtCore.Qt.Key_3:
            self.set_world_transform(display_magnification=15.0)
            changed = True
        elif key in (QtCore.Qt.Key_Plus, QtCore.Qt.Key_Equal):
            self.set_world_transform(
                display_magnification=float(self.display_magnification) + 1.0
            )
            changed = True
        elif key == QtCore.Qt.Key_Minus:
            self.set_world_transform(
                display_magnification=max(0.5, float(self.display_magnification) - 1.0)
            )
            changed = True
        elif key == QtCore.Qt.Key_R:
            self.win.setCameraPosition(distance=40, elevation=25, azimuth=45)
            self.win.opts["center"] = pg.Vector(self.length_mm * 0.5, 0, 0)
        elif key == QtCore.Qt.Key_Escape:
            QtWidgets.QApplication.instance().quit()
            return
        if changed:
            self._print_scale_help()
            self.present_to_srd()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--units", default="mm", choices=("mm", "cm", "m"))
    p.add_argument("--magnification", "-m", type=float, default=10.0)
    p.add_argument("--length", type=float, default=10.0, help="Ruler length in scene mm")
    p.add_argument(
        "--render-scale",
        default="0.5",
        help="Stereo FBO scale vs eye res (e.g. 0.5). Use 'none' for fullscreen "
        "desktop preview (same as --fullscreen).",
    )
    p.add_argument(
        "--fullscreen",
        action="store_true",
        help="Fullscreen Qt preview on a desktop monitor (not the SRD)",
    )
    p.add_argument("--no-preview", action="store_true")
    args = p.parse_args(argv)

    rs = str(args.render_scale).strip().lower()
    if args.fullscreen or rs in ("none", "full", "fullscreen"):
        render_scale = None
    else:
        render_scale = float(args.render_scale)

    app = QtWidgets.QApplication([])

    signal.signal(signal.SIGINT, lambda *args: app.quit())
    _sigint_timer = QtCore.QTimer()
    _sigint_timer.timeout.connect(lambda: None)
    _sigint_timer.start(200)

    demo = RulerTest(
        length_mm=args.length,
        units=args.units,
        display_magnification=args.magnification,
        render_scale=render_scale,
        show_preview=not args.no_preview,
    )
    demo.onStart()
    if demo.show_preview:
        demo.win.setWindowTitle(
            f"SRD ruler — {args.length:g} mm @ mag={args.magnification:g}"
        )
        demo.win.resize(900, 700)
        demo.win.show()
    app.exec_()
    demo.onExit()


if __name__ == "__main__":
    main()
