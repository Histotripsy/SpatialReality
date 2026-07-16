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

| File | Notes |
|---|---|
| `stereo_buffers.py` | Raw left/right RGBA submit (no Qt) |
| `gl_view_demo.py` | Minimal `StereoPresenter` scatter scene |
| `pose_orbit_test.py` | RGB axes + cube; Qt orbit drives SRD pose |
| `ruler_test.py` | Scale / magnification check |
| `sphere_cloud.py` | Animated scatter cloud + wireframes |
