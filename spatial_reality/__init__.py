"""
Sony Spatial Reality Display (SRD) Python bindings.

Layers
------
``spatial_reality.bridge``
    ctypes wrapper around ``SRDBridge.dll`` — submit RGBA frames, read eye
    poses / view / projection matrices.  No Qt dependency.

``spatial_reality.gl``
    ``create_stereo_view`` / ``SRDGLViewWidget`` + ``StereoPresenter`` +
    ``SRDAppAbstract`` for PyQt / pyqtgraph.opengl scenes.
"""

from __future__ import annotations

__version__ = "0.2.0"

from spatial_reality.bridge import (
    EYE_HEAD,
    EYE_LEFT,
    EYE_RIGHT,
    SRDSession,
    display_info,
    eye_resolution,
    get_pose,
    init,
    is_initialized,
    last_error,
    load,
    make_current,
    poll_events,
    present_stereo_frame,
    projection_fov_deg,
    projection_half_angles,
    projection_matrix,
    set_log_level,
    shutdown,
    silence_client_stdio,
    submit_rgba,
    submit_stereo,
    submit_texture,
    update_tracking,
    view_matrix,
)

__all__ = [
    "__version__",
    "EYE_HEAD",
    "EYE_LEFT",
    "EYE_RIGHT",
    "SRDSession",
    "display_info",
    "eye_resolution",
    "get_pose",
    "init",
    "is_initialized",
    "last_error",
    "load",
    "make_current",
    "poll_events",
    "present_stereo_frame",
    "projection_fov_deg",
    "projection_half_angles",
    "projection_matrix",
    "set_log_level",
    "shutdown",
    "silence_client_stdio",
    "submit_rgba",
    "submit_stereo",
    "submit_texture",
    "update_tracking",
    "view_matrix",
]

# Optional GL exports — available when PyQt5 / pyqtgraph / PyOpenGL are installed.
try:
    from spatial_reality.gl import (  # noqa: F401
        SRDGLViewWidget,
        StereoPresenter,
        SRDAppAbstract,
        configure_surface_format,
        create_stereo_view,
        resolve_world_scale,
    )

    __all__ += [
        "SRDGLViewWidget",
        "StereoPresenter",
        "SRDAppAbstract",
        "configure_surface_format",
        "create_stereo_view",
        "resolve_world_scale",
    ]
except ImportError:
    pass
