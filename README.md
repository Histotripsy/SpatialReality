# Spatial Reality Display Bridge

MIT-licensed Python + C bridge for presenting frames on a Sony Spatial Reality Display (SRD).

This repository does **not** include Sony's Native API. Download it separately and drop it into `XR_API/` before building.

## Layout

| Path | Purpose |
|---|---|
| `spatial_reality/` | Python package (`pip install sony-spatial-reality-python`) |
| `spatial_reality/bridge.py` | ctypes API — RGBA submit, poses, matrices (no Qt) |
| `spatial_reality/gl.py` | `SRDGLViewWidget` + `StereoPresenter` + `SRDAppAbstract` for PyQt / pyqtgraph |
| `src/` | `SRDBridge` native library sources |
| `CMakeLists.txt` | Single CMake project (builds `SRDBridge.dll`) |
| `XR_API/` | **You provide this** — Sony Native API (see below) |
| `third_party/` | GLFW, glm, gl3w |
| `examples/` | Demos (run after `pip install -e ".[gl]"`) |
| `scripts/build_dll.py` | Configure + build the DLL if missing |

## 1. Get the Sony Native API

1. Download **Native API** from Sony:  
   https://xyn.sony.net/en/developer/setup/spatial-reality-display/download-info
2. Extract the zip. Find the `XR_API` folder (headers + `xr_api.lib`), usually under something like:

   ```text
   XR_API_XX/XR_API/
   ```

3. Copy that folder to the **repo root** so you have:

   ```text
   SpatialReality/
     XR_API/
       include/
         xr_api_wrapper.h
         …
       lib/
         Release/xr_api.lib
         Debug/xr_api.lib
   ```

   Details: [`XR_API/README.md`](XR_API/README.md). Sony materials remain under Sony's license; this repo only ships our wrapper (see [`NOTICE`](NOTICE)).

Also install the Spatial Reality Display Settings / driver from the same download page if you have not already.

## 2. Build `SRDBridge.dll`

Windows (Visual Studio 2022 + CMake on `PATH`):

```bat
python scripts/build_dll.py
```

or:

```bat
scripts\build_dll.bat
cmake -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
```

Output: `build/Release/SRDBridge.dll`.

Optional overrides:

| Variable | Meaning |
|---|---|
| `SRD_BRIDGE_DLL` | Explicit path to `SRDBridge.dll` |
| `SRD_AUTO_BUILD=0` | Disable automatic CMake build when the DLL is missing |

When developing from a source checkout on Windows, `spatial_reality.bridge` will try `scripts/build_dll.py` once if the DLL is not found.

## 3. Install the Python package

```bat
pip install -e .
pip install -e ".[gl]"
```

This installs **`sony-spatial-reality-python`**; import it as ``spatial_reality``:

```python
from spatial_reality import bridge
from spatial_reality.gl import SRDGLViewWidget, StereoPresenter, SRDAppAbstract
```

Examples assume the package is installed (or the repo root is on `PYTHONPATH`):

```bat
python examples/gl_view_demo.py
python examples/stereo_buffers.py
```

## Python API

### Buffer API (no Qt)

```python
import numpy as np
from spatial_reality import bridge as srd

if not srd.init():
    raise RuntimeError(srd.last_error())

w, h = srd.eye_resolution()
try:
    while srd.poll_events():
        srd.update_tracking()
        left = np.zeros((h, w, 4), np.uint8)
        right = np.zeros((h, w, 4), np.uint8)
        left[..., 1] = 180
        left[..., 3] = 255
        right[..., 2] = 180
        right[..., 3] = 255
        srd.submit_stereo(left, right)
finally:
    srd.shutdown()
```

### PyQt / pyqtgraph (recommended for 3D scenes)

```python
from PyQt5 import QtWidgets
import pyqtgraph.opengl as gl
from spatial_reality.gl import SRDGLViewWidget, StereoPresenter, configure_surface_format

configure_surface_format()
app = QtWidgets.QApplication([])

win = SRDGLViewWidget()
win.addItem(gl.GLScatterPlotItem(pos=..., size=1.0, pxMode=False))
win.show()

presenter = StereoPresenter(win, units="mm", display_magnification=10, init_session=True)
presenter.present()  # after each scene update
```

## Releases / packaging (important)

**Do not** put Sony’s `NativeAPI-*.zip`, `XR_API` headers/libs, Settings installer, or Sony runtime DLLs in GitHub Releases, CI artifacts, or pip wheels — including by having an agent download them from Sony and re-upload. Headers are marked `Sony CONFIDENTIAL` / do not redistribute; Sony’s EULAs generally forbid sharing or redistributing the software. Automating the download does not change that.

**Recommended public release contents**

| Ship | Do not ship |
|---|---|
| This repo’s MIT sources (`spatial_reality/`, `src/SRDBridge.*`, examples, scripts) | `XR_API/**` headers, `.lib`, Sony `.dll` |
| `LICENSE`, `NOTICE`, docs | `NativeAPI-*.zip` / installer MSIs |
| Optionally: a **source** tag / sdist on PyPI | Bundled Sony runtimes “for convenience” |

Prebuilding **only** our `SRDBridge.dll` (without Sony libs) is still legally murky because it is compiled against Sony’s proprietary headers and linked with `xr_api.lib`. Prefer **source-only** releases unless Sony confirms redistribution of that binary is allowed. Each user should download the Native API themselves and run `python scripts/build_dll.py`.

## Troubleshooting head tracking

Head-tracked content should stay **world-locked** in the display volume (parallax only; no screen-plane sliding). Rebuild the DLL after pulling:

```bat
python scripts/build_dll.py --force
```

Presentation uses OpenGL-native framebuffer orientation with ``flip_y=True`` on submit (same idea as the OpenXR demo rendering straight into a GL swapchain — no CPU ``flipud``). Projection half-angles are applied as signed frustum edges, matching OpenXR ``CreateProjectionFov(GRAPHICS_OPENGL)``.

``mirror_x`` defaults to **True** so SRD left/right matches the Qt preview. Pass ``mirror_x=False`` / ``--no-mirror-x`` only if L/R is already correct.

By default ``follow_preview_camera=True``: the SRD shows the same orbit
**rotation** / **pan** as the Qt preview (absolute WYSIWYG; wheel zoom does
not change SRD scale). Head tracking still adds stereo parallax. Use
``examples/pose_orbit_test.py`` to verify (expect blue up, red left, green
right, yellow front on both).

## License

- **This repository:** [MIT](LICENSE) (see also [NOTICE](NOTICE))
- **Sony Native API / runtime:** Sony's terms — not redistributed here
- Commercial apps built with Sony's SDK may require a separate Sony commercial license (see their download page)
