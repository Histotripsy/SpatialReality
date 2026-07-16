"""Submit raw left/right RGBA buffers to the SRD (no Qt / pyqtgraph)."""

from __future__ import annotations


import numpy as np
from pathlib import Path
import sys
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from spatial_reality import bridge as srd


def main():
    if not srd.init():
        raise RuntimeError(srd.last_error())

    w, h = srd.eye_resolution()
    print(f"SRD eye resolution: {w}x{h}")
    try:
        frame = 0
        while srd.poll_events():
            srd.update_tracking()
            left = np.zeros((h, w, 4), dtype=np.uint8)
            right = np.zeros((h, w, 4), dtype=np.uint8)
            left[..., 0] = (frame * 3) & 255
            left[..., 3] = 255
            right[..., 2] = (frame * 5) & 255
            right[..., 3] = 255
            srd.submit_stereo(left, right)
            frame += 1
    finally:
        srd.shutdown()


if __name__ == "__main__":
    main()
