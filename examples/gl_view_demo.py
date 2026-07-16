"""
Minimal pyqtgraph scene on the SRD using create_stereo_view.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl
from PyQt5 import QtCore, QtWidgets

from pathlib import Path
import sys
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from spatial_reality.gl import create_stereo_view


def main():
    app = QtWidgets.QApplication([])

    win, presenter = create_stereo_view(
        units="cm",
        display_magnification=1.0,
        render_scale=0.4,
        show_preview=True,
    )

    n = 800
    rng = np.random.default_rng(0)
    pts = rng.uniform(-8, 8, size=(n, 3)).astype(np.float32)
    cols = np.ones((n, 4), dtype=np.float32)
    cols[:, 0] = np.linspace(0.2, 1.0, n)
    cols[:, 1] = np.linspace(1.0, 0.2, n)
    cols[:, 2] = 0.3
    scatter = gl.GLScatterPlotItem(pos=pts, color=cols, size=0.35, pxMode=False)
    win.addItem(scatter)

    grid = gl.GLGridItem()
    grid.scale(2, 2, 1)
    win.addItem(grid)

    t0 = QtCore.QElapsedTimer()
    t0.start()

    def tick():
        t = t0.elapsed() / 1000.0
        cols[:, 2] = 0.5 + 0.5 * np.sin(t)
        scatter.setData(color=cols)
        presenter.present()

    timer = QtCore.QTimer()
    timer.timeout.connect(tick)
    timer.start(33)

    win.show()
    presenter.schedule_present(0)
    app.exec_()
    presenter.shutdown()


if __name__ == "__main__":
    main()
