"""
SRD pose / orbit test — drive SRD rotation & translation from the Qt camera.

Drag the Qt preview to orbit/pan; the Spatial Reality Display follows the same
pose.  Wheel zoom changes only the desktop preview distance — object **scale**
on the SRD stays fixed (units / magnification).

Scene
-----
RGB axes (X=red, Y=green, Z=blue), a 10 mm reference cube, corner markers,
and a ground grid.  Easy to see mirroring, flip, and world-lock while you
move your head and the orbit camera.

Run::

    python examples/pose_orbit_test.py
    python examples/pose_orbit_test.py --magnification 10

Keys
----
``R``     reset camera to the default orbit pose
``F``     toggle follow_preview_camera
``1/2/3`` magnification 1 / 10 / 15
``Esc``   quit
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

from spatial_reality.gl import SRDAppAbstract


def _axis_item(axis: str, length: float, color) -> gl.GLLinePlotItem:
    if axis == "x":
        pos = np.array([[0, 0, 0], [length, 0, 0]], dtype=np.float32)
    elif axis == "y":
        pos = np.array([[0, 0, 0], [0, length, 0]], dtype=np.float32)
    else:
        pos = np.array([[0, 0, 0], [0, 0, length]], dtype=np.float32)
    return gl.GLLinePlotItem(
        pos=pos, color=color, width=4.0, antialias=True, mode="line_strip"
    )


def _cube_edges(size: float = 10.0) -> gl.GLLinePlotItem:
    """Wire cube from (0,0,0) to (size,size,size)."""
    s = float(size)
    corners = np.array(
        [
            [0, 0, 0],
            [s, 0, 0],
            [s, s, 0],
            [0, s, 0],
            [0, 0, s],
            [s, 0, s],
            [s, s, s],
            [0, s, s],
        ],
        dtype=np.float32,
    )
    edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    pts = []
    for a, b in edges:
        pts.append(corners[a])
        pts.append(corners[b])
    return gl.GLLinePlotItem(
        pos=np.asarray(pts, dtype=np.float32),
        color=(0.85, 0.85, 0.9, 1.0),
        width=2.0,
        antialias=True,
        mode="lines",
    )


def build_pose_scene(axis_len_mm: float = 12.0, cube_mm: float = 10.0) -> list:
    items = []
    items.append(_axis_item("x", axis_len_mm, (1.0, 0.15, 0.15, 1.0)))
    items.append(_axis_item("y", axis_len_mm, (0.15, 1.0, 0.25, 1.0)))
    items.append(_axis_item("z", axis_len_mm, (0.25, 0.45, 1.0, 1.0)))
    items.append(_cube_edges(cube_mm))

    # Bright corners: origin + +X/+Y/+Z tips + far cube corner
    markers = np.array(
        [
            [0, 0, 0],
            [axis_len_mm, 0, 0],
            [0, axis_len_mm, 0],
            [0, 0, axis_len_mm],
            [cube_mm, cube_mm, cube_mm],
        ],
        dtype=np.float32,
    )
    colors = np.array(
        [
            [1.0, 1.0, 1.0, 1.0],
            [1.0, 0.2, 0.2, 1.0],
            [0.2, 1.0, 0.3, 1.0],
            [0.3, 0.5, 1.0, 1.0],
            [1.0, 0.85, 0.2, 1.0],
        ],
        dtype=np.float32,
    )
    items.append(
        gl.GLScatterPlotItem(
            pos=markers, color=colors, size=0.8, pxMode=False
        )
    )

    grid = gl.GLGridItem()
    grid.setSize(20, 20)
    grid.setSpacing(2, 2)
    grid.translate(cube_mm * 0.5, cube_mm * 0.5, -0.01)
    grid.setColor((0.3, 0.3, 0.3, 0.7))
    items.append(grid)
    return items


class PoseOrbitTest(SRDAppAbstract):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("units", "mm")
        kwargs.setdefault("display_magnification", 10.0)
        kwargs.setdefault("mirror_x", True)
        kwargs.setdefault("follow_preview_camera", True)
        kwargs.setdefault("render_scale", 0.5)
        kwargs.setdefault("show_preview", True)
        super().__init__(*args, **kwargs)
        self._timer = None
        self._status_timer = None
        self._home_cam = dict(distance=40.0, elevation=25.0, azimuth=45.0)

    def _setupWindow(self):
        for item in build_pose_scene():
            self.win.addItem(item)

        c = pg.Vector(5.0, 5.0, 5.0)
        self.win.opts["center"] = c
        self.win.setCameraPosition(
            distance=self._home_cam["distance"],
            elevation=self._home_cam["elevation"],
            azimuth=self._home_cam["azimuth"],
        )
        self.win.opts["fov"] = 35

        self.win.setWindowTitle(
            "SRD pose orbit test — SRD should match Qt orbit (wheel = preview zoom only)"
        )
        self.win.resize(960, 640)
        if self.show_preview:
            self.win.show()

        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

        self._status_timer = QtCore.QTimer()
        self._status_timer.timeout.connect(self._print_status)
        self._status_timer.start(1000)

        print(
            "Pose orbit test\n"
            "  Expect: SRD matches Qt — blue up, red left, green right, yellow front\n"
            "  LMB drag = orbit (SRD follows)\n"
            "  MMB/Ctrl+LMB drag = pan (SRD follows)\n"
            "  Wheel = preview distance only (SRD scale fixed)\n"
            "  R=reset camera  F=toggle follow  Esc=quit\n"
        )
        self._print_status()

    def _tick(self):
        self.present_to_srd()

    def _print_status(self):
        opts = self.win.opts
        c = opts.get("center")
        follow = self.presenter.follow_preview_camera
        print(
            f"  az={opts.get('azimuth', 0):6.1f}  el={opts.get('elevation', 0):6.1f}  "
            f"dist={opts.get('distance', 0):6.1f} (preview only)  "
            f"center=({float(c.x()):.2f},{float(c.y()):.2f},{float(c.z()):.2f})  "
            f"follow={'ON' if follow else 'OFF'}  "
            f"mag={self.display_magnification:g}"
        )

    def _reset_home(self):
        self.win.opts["center"] = pg.Vector(5.0, 5.0, 5.0)
        self.win.setCameraPosition(
            distance=self._home_cam["distance"],
            elevation=self._home_cam["elevation"],
            azimuth=self._home_cam["azimuth"],
        )
        print("  reset camera to default orbit pose")

    def keyPressEvent(self, ev):
        key = ev.key()
        if key == QtCore.Qt.Key_Escape:
            QtWidgets.QApplication.instance().quit()
        elif key == QtCore.Qt.Key_R:
            self._reset_home()
        elif key == QtCore.Qt.Key_F:
            self.presenter.follow_preview_camera = (
                not self.presenter.follow_preview_camera
            )
            print(
                f"  follow_preview_camera="
                f"{'ON' if self.presenter.follow_preview_camera else 'OFF'}"
            )
        elif key == QtCore.Qt.Key_1:
            self.set_world_transform(display_magnification=1.0)
            print("  magnification=1")
        elif key == QtCore.Qt.Key_2:
            self.set_world_transform(display_magnification=10.0)
            print("  magnification=10")
        elif key == QtCore.Qt.Key_3:
            self.set_world_transform(display_magnification=15.0)
            print("  magnification=15")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--magnification", type=float, default=10.0)
    p.add_argument(
        "--render-scale",
        default="0.5",
        help="SRD eye render scale, or 'none' for full eye resolution",
    )
    p.add_argument("--no-preview", action="store_true")
    p.add_argument(
        "--no-follow-camera",
        action="store_true",
        help="Do not apply Qt orbit pose on the SRD",
    )
    p.add_argument(
        "--no-mirror-x",
        action="store_true",
        help="Disable X mirror on SRD cameras",
    )
    args = p.parse_args(argv)

    rs = str(args.render_scale).strip().lower()
    render_scale = None if rs in ("none", "full", "fullscreen") else float(args.render_scale)

    app = QtWidgets.QApplication([])
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    _sigint_timer = QtCore.QTimer()
    _sigint_timer.timeout.connect(lambda: None)
    _sigint_timer.start(200)

    demo = PoseOrbitTest(
        units="mm",
        display_magnification=args.magnification,
        render_scale=render_scale,
        show_preview=not args.no_preview,
        follow_preview_camera=not args.no_follow_camera,
        mirror_x=not args.no_mirror_x,
    )
    demo.onStart()
    code = app.exec_()
    demo.onExit()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
