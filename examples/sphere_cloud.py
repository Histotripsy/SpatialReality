"""
Cavitation-style demo for the SRD: outer wireframe sphere filled with
moving colored ``GLScatterPlotItem`` bubbles, plus a small wireframe marker
that tracks the "current" bubble.

Uses ``SRDAppAbstract`` to keep the boilerplate (window setup, key-event
forwarding, present loop) out of the demo class itself.

(``_makeSphereWireframe``, scatter ``pxMode=False``, ``present_to_srd``).

Run::

    python examples/sphere_cloud.py
    python examples/sphere_cloud.py --radius 12 --n 80 --magnification 10

Keys: ``Space`` pause/resume, ``R`` reseed, ``Esc`` quit.
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


def make_sphere_wireframe(center, radii, color=(1, 1, 1, 0.25), lw=1.0, n=16):
    """Latitude / longitude wireframe sphere as ``GLLinePlotItem`` (mm)."""
    cx, cy, cz = center
    if np.isscalar(radii):
        rx = ry = rz = float(radii)
    else:
        rx, ry, rz = radii
    lines = []
    for i in range(1, n):
        lat = np.pi * i / n - np.pi / 2
        cos_lat = np.cos(lat)
        sin_lat = np.sin(lat)
        lon = np.linspace(0, 2 * np.pi, n + 1)
        ring = np.column_stack(
            [
                cx + rx * cos_lat * np.cos(lon),
                cy + ry * cos_lat * np.sin(lon),
                cz + rz * np.full_like(lon, sin_lat),
            ]
        ).astype(np.float32)
        pairs = np.empty((2 * n, 3), dtype=np.float32)
        pairs[0::2] = ring[:-1]
        pairs[1::2] = ring[1:]
        lines.append(pairs)
    for i in range(n):
        lon = 2 * np.pi * i / n
        lat = np.linspace(-np.pi / 2, np.pi / 2, n + 1)
        meridian = np.column_stack(
            [
                cx + rx * np.cos(lat) * np.cos(lon),
                cy + ry * np.cos(lat) * np.sin(lon),
                cz + rz * np.sin(lat),
            ]
        ).astype(np.float32)
        pairs = np.empty((2 * n, 3), dtype=np.float32)
        pairs[0::2] = meridian[:-1]
        pairs[1::2] = meridian[1:]
        lines.append(pairs)
    pts = np.concatenate(lines, axis=0)
    return gl.GLLinePlotItem(pos=pts, color=color, width=lw, mode="lines", antialias=True)


def random_points_in_sphere(n: int, radius: float, rng: np.random.Generator) -> np.ndarray:
    """Uniform samples inside a ball of the given radius (mm)."""
    u = rng.normal(size=(n, 3))
    u /= np.linalg.norm(u, axis=1, keepdims=True).clip(1e-9)
    r = radius * (rng.random(n) ** (1.0 / 3.0))
    return (u * r[:, None]).astype(np.float32)


class SphereCloudDemo(SRDAppAbstract):
    """
    Outer wireframe bounds a cloud of colored scatter bubbles that drift
    inside it.  A small wireframe marker follows one bubble (like
    ``cur_sphere`` in the cavitation plotter).
    """

    def __init__(
        self,
        radius_mm: float = 10.0,
        n_bubbles: int = 64,
        bubble_rmax: float = 1.0,
        *args,
        **kwargs,
    ):
        kwargs.setdefault("units", "mm")
        kwargs.setdefault("display_magnification", 10.0)
        kwargs.setdefault("mirror_x", True)
        kwargs.setdefault("render_scale", 0.5)
        kwargs.setdefault("show_preview", True)
        super().__init__(*args, **kwargs)

        self.radius_mm = float(radius_mm)
        self.n_bubbles = int(n_bubbles)
        self.bubble_rmax = float(bubble_rmax)
        self.rng = np.random.default_rng(7)
        self.paused = False
        self.cur_idx = 0

        self.pos = None
        self.vel = None
        self.colors = None
        self.scatter = None
        self.outer_sphere = None
        self.cur_sphere = None
        self._timer = None
        self._t0 = None

    def _setupWindow(self):
        # Outer containment sphere (wireframe)
        self.outer_sphere = make_sphere_wireframe(
            center=(0, 0, 0),
            radii=self.radius_mm,
            color=(1.0, 1.0, 1.0, 0.35),
            lw=1.5,
            n=20,
        )
        self.win.addItem(self.outer_sphere)

        # Moving "current location" marker wireframe (slightly larger than bubble)
        r = 1.05 * self.bubble_rmax
        self.cur_sphere = make_sphere_wireframe(
            center=(0, 0, 0),
            radii=(r, r, 1.4 * r),
            color=(0.9, 0.9, 0.9, 1.0),
            lw=2.0,
            n=8,
        )
        self.cur_sphere.setGLOptions("opaque")
        self.win.addItem(self.cur_sphere)

        # Inner colored bubbles
        self.pos = random_points_in_sphere(self.n_bubbles, self.radius_mm * 0.92, self.rng)
        self.vel = self.rng.normal(size=self.pos.shape).astype(np.float32)
        self.vel *= 0.8  # mm / frame at ~30 Hz ≈ slow drift
        self.colors = np.ones((self.n_bubbles, 4), dtype=np.float32)
        self.colors[:, 0] = self.rng.uniform(0.3, 1.0, self.n_bubbles)
        self.colors[:, 1] = self.rng.uniform(0.2, 0.9, self.n_bubbles)
        self.colors[:, 2] = self.rng.uniform(0.2, 1.0, self.n_bubbles)
        self.colors[:, 3] = 0.95

        self.scatter = gl.GLScatterPlotItem()
        self.win.addItem(self.scatter)
        # size in mm (same as pos) — matches wireframe marker scale
        self.scatter.setData(
            pos=self.pos,
            color=self.colors,
            size=self.bubble_rmax,
            pxMode=False,
        )

        self.win.setCameraPosition(distance=50, elevation=20, azimuth=55)
        self.win.opts["center"] = pg.Vector(0, 0, 0)
        self.win.opts["fov"] = 28

        print(
            f"Sphere cloud: R={self.radius_mm:g} mm, N={self.n_bubbles}, "
            f"bubble={self.bubble_rmax:g} mm, mag={self.display_magnification:g} "
            f"(outer sphere ≈ {self.radius_mm * 0.1 * self.display_magnification:.1f} cm "
            f"radius on SRD)"
        )

        self._t0 = QtCore.QElapsedTimer()
        self._t0.start()
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _reseed(self):
        self.pos = random_points_in_sphere(self.n_bubbles, self.radius_mm * 0.92, self.rng)
        self.vel = self.rng.normal(size=self.pos.shape).astype(np.float32) * 0.8
        self.cur_idx = 0

    def _step_physics(self, dt: float):
        # Integrate and bounce inside the outer sphere.
        self.pos = self.pos + self.vel * dt
        r = np.linalg.norm(self.pos, axis=1)
        limit = self.radius_mm - self.bubble_rmax
        hit = r > limit
        if np.any(hit):
            # Reflect velocity along radial normal and pull back inside.
            nrm = self.pos[hit] / r[hit, None].clip(1e-9)
            v_rad = np.sum(self.vel[hit] * nrm, axis=1, keepdims=True)
            self.vel[hit] = self.vel[hit] - 2.0 * v_rad * nrm
            self.pos[hit] = nrm * (limit * 0.98)

        # Mild random steering so the cloud keeps mixing
        self.vel += self.rng.normal(scale=0.15, size=self.vel.shape).astype(np.float32)
        speed = np.linalg.norm(self.vel, axis=1, keepdims=True).clip(1e-6)
        max_speed = 4.0
        too_fast = speed > max_speed
        self.vel = np.where(too_fast, self.vel / speed * max_speed, self.vel)

        # Pulse colors
        t = self._t0.elapsed() / 1000.0
        self.colors[:, 3] = 0.75 + 0.2 * np.sin(t * 2.0 + np.linspace(0, 3, self.n_bubbles))

    def _tick(self):
        if not self.paused:
            self._step_physics(dt=0.35)
            # Advance "current" marker slowly through the cloud
            if self._t0.elapsed() % 400 < 40:
                self.cur_idx = (self.cur_idx + 1) % self.n_bubbles

            self.scatter.setData(pos=self.pos, color=self.colors)
            self.cur_sphere.resetTransform()
            self.cur_sphere.translate(*self.pos[self.cur_idx])

        self.present_to_srd()

    def keyPressEvent(self, ev):
        key = ev.key()
        if key == QtCore.Qt.Key_Space:
            self.paused = not self.paused
            print("paused" if self.paused else "running")
        elif key == QtCore.Qt.Key_R:
            self._reseed()
            self.scatter.setData(pos=self.pos, color=self.colors)
            print("reseeded")
        elif key == QtCore.Qt.Key_Escape:
            QtWidgets.QApplication.instance().quit()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--radius", type=float, default=10.0, help="Outer sphere radius in mm")
    p.add_argument("--n", type=int, default=64, help="Number of scatter bubbles")
    p.add_argument("--bubble", type=float, default=1.0, help="Scatter size (mm diameter)")
    p.add_argument("--magnification", "-m", type=float, default=10.0)
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
    p.add_argument(
        "--mirror-x",
        action="store_true",
        default=True,
        help="Mirror world X on SRD cameras (default; matches Qt L/R)",
    )
    p.add_argument(
        "--no-mirror-x",
        action="store_false",
        dest="mirror_x",
        help="Disable X mirror if SRD L/R already matches the preview",
    )
    args = p.parse_args(argv)

    rs = str(args.render_scale).strip().lower()
    if args.fullscreen or rs in ("none", "full", "fullscreen"):
        render_scale = None
    else:
        render_scale = float(args.render_scale)

    app = QtWidgets.QApplication([])

    # Let Ctrl-C quit the app instead of being swallowed by Qt's event loop.
    signal.signal(signal.SIGINT, lambda *args: app.quit())
    # Qt's C++ event loop never hands control back to the Python interpreter
    # (which is where signal handlers actually run) unless something wakes
    # it up periodically -- this no-op timer does that.
    _sigint_timer = QtCore.QTimer()
    _sigint_timer.timeout.connect(lambda: None)
    _sigint_timer.start(200)

    demo = SphereCloudDemo(
        radius_mm=args.radius,
        n_bubbles=args.n,
        bubble_rmax=args.bubble,
        units="mm",
        display_magnification=args.magnification,
        render_scale=render_scale,
        show_preview=not args.no_preview,
        mirror_x=args.mirror_x,
    )
    demo.onStart()
    if demo.show_preview:
        demo.win.setWindowTitle(
            f"SRD sphere cloud — R={args.radius:g} mm, N={args.n}, mag={args.magnification:g}"
        )
        demo.win.resize(900, 700)
        demo.win.show()

    app.exec_()
    demo.onExit()


if __name__ == "__main__":
    main()