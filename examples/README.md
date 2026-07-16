# Examples

Install the package first (from the repo root):

```bat
pip install -e ".[gl]"
python scripts/build_dll.py
```

Then run:

```bat
python examples/stereo_buffers.py
python examples/gl_view_demo.py
python examples/pose_orbit_test.py
python examples/ruler_test.py --magnification 10
python examples/sphere_cloud.py --radius 10 --n 64
```

| File | Dependency | Notes |
|---|---|---|
| `stereo_buffers.py` | `spatial_reality.bridge` | Flashing L/R color fields |
| `gl_view_demo.py` | `spatial_reality.gl` | Preferred lightweight pyqtgraph path |
| `pose_orbit_test.py` | `spatial_reality.gl` | RGB axes + cube; Qt orbit drives SRD pose |
| `ruler_test.py` | `spatial_reality.gl` | Scale / magnification check |
| `sphere_cloud.py` | `spatial_reality.gl` | Moving scatter + wireframes |
