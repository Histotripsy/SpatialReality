"""
Lightweight pyqtgraph / PyQt helpers for the Sony Spatial Reality Display.

Use ``SRDGLViewWidget`` like a normal ``GLViewWidget``, then push stereo frames
with ``StereoPresenter``::

    from PyQt5 import QtWidgets
    import pyqtgraph.opengl as gl
    from spatial_reality import bridge as srd
    from spatial_reality.gl import SRDGLViewWidget, StereoPresenter, configure_surface_format

    configure_surface_format()
    app = QtWidgets.QApplication([])
    if not srd.init():
        raise RuntimeError(srd.last_error())

    win = SRDGLViewWidget()
    win.addItem(gl.GLScatterPlotItem(pos=..., size=1.0, pxMode=False))
    win.show()

    presenter = StereoPresenter(win, units="mm", display_magnification=10)
    # call presenter.present() whenever the scene should refresh on the SRD
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

import numpy as np

from spatial_reality import bridge as srd

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
    import OpenGL.GL as GL
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "spatial_reality.gl requires PyQt5, pyqtgraph, and PyOpenGL"
    ) from exc


# ---------------------------------------------------------------------------
# Matrix / transform helpers
# ---------------------------------------------------------------------------
def np_to_qmatrix(mat4: np.ndarray) -> QtGui.QMatrix4x4:
    """Convert a mathematical 4x4 numpy matrix (row, col) to QMatrix4x4."""
    m = np.asarray(mat4, dtype=np.float32).reshape(4, 4)
    return QtGui.QMatrix4x4(*m.reshape(16).tolist())


def make_world_matrix(
    scale: float = 1.0,
    translation: Sequence[float] = (0.0, 0.0, 0.0),
) -> np.ndarray:
    """
    Model/world -> SRD centimeters.

    ``p_srd = scale * p_world + translation``
    """
    m = np.eye(4, dtype=np.float32)
    m[0, 0] = m[1, 1] = m[2, 2] = float(scale)
    m[0, 3], m[1, 3], m[2, 3] = map(float, translation)
    return m


def resolve_world_scale(
    units: str = "cm",
    display_magnification: float = 1.0,
    world_scale: Optional[float] = None,
) -> float:
    """
    Map plot coordinates into SRD centimeters.

    SRD view/projection matrices are in **centimeters**.

    - ``units='cm'``: scale = 1 * magnification
    - ``units='mm'``: scale = 0.1 * magnification  (1mm -> 0.1cm at mag=1)
    """
    if world_scale is not None:
        return float(world_scale)
    u = (units or "cm").strip().lower()
    if u in ("mm", "millimeter", "millimetre"):
        unit_scale = 0.1
    elif u in ("cm", "centimeter", "centimetre"):
        unit_scale = 1.0
    elif u in ("m", "meter", "metre"):
        unit_scale = 100.0
    else:
        raise ValueError(f"Unknown units {units!r}; use 'mm', 'cm', or 'm'")
    return unit_scale * float(display_magnification)


def default_scene_translation_cm() -> Tuple[float, float, float]:
    """Place the model origin at the center of the SRD viewing volume."""
    info = srd.display_info()
    screen_h_cm = info["height_m"] * 100.0
    tilt = float(info["tilt_rad"])
    height_cm = screen_h_cm * float(np.sin(tilt))
    depth_cm = screen_h_cm * float(np.cos(tilt))
    return (0.0, 0.5 * height_cm, -0.5 * depth_cm)


def resolve_scene_translation_cm(
    scene_translation: Optional[Sequence[float]] = None,
    *,
    center_scene: bool = True,
) -> Tuple[float, float, float]:
    """
    Resolve the model→SRD translation.

    - ``center_scene=True`` (default): put model ``(0,0,0)`` at the viewing
      volume center, then add ``scene_translation`` as an extra offset (cm).
    - ``center_scene=False``: use ``scene_translation`` as an absolute SRD-cm
      translation (``None`` → ``(0,0,0)``).
    """
    extra = (0.0, 0.0, 0.0)
    if scene_translation is not None:
        extra = tuple(map(float, scene_translation))
        if len(extra) != 3:
            raise ValueError("scene_translation must be a length-3 sequence")
    if center_scene:
        cx, cy, cz = default_scene_translation_cm()
        return (cx + extra[0], cy + extra[1], cz + extra[2])
    return extra


def eye_pos_cm_from_view(view: np.ndarray) -> Tuple[float, float, float]:
    """World-space camera position (cm) encoded by an OpenGL view matrix."""
    inv = np.linalg.inv(np.asarray(view, dtype=np.float64).reshape(4, 4))
    return float(inv[0, 3]), float(inv[1, 3]), float(inv[2, 3])


def configure_surface_format() -> None:
    """
    Request a Compatibility profile so pyqtgraph's legacy matrix path
    (glMatrixMode) is valid. Must run before the first GLViewWidget exists.
    """
    fmt = QtGui.QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setVersion(2, 1)
    try:
        fmt.setProfile(QtGui.QSurfaceFormat.CompatibilityProfile)
    except AttributeError:
        pass
    QtGui.QSurfaceFormat.setDefaultFormat(fmt)

def qimage_to_rgba(qimg: QtGui.QImage) -> np.ndarray:
    qimg = qimg.convertToFormat(QtGui.QImage.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.bits()
    ptr.setsize(w * h * 4)
    return np.frombuffer(ptr, dtype=np.uint8).reshape(h, w, 4).copy()


def read_rgba_from_gl(width: int, height: int) -> np.ndarray:
    """
    Read the current GL framebuffer as RGBA uint8 in OpenGL row order
    (row 0 = bottom of the image).

    Do **not** CPU-``flipud`` here.  The OpenXR / NativeAPI present path
    expects GL-native orientation; pass ``flip_y=True`` to
    ``submit_stereo`` / ``SubmitOpengl`` so the compositor treats the
    buffer as bottom-left origin.  CPU-flipping while submitting with
    ``flip_y=False`` made the SBS image upright on a 2D blit but inverted
    head-tracked vertical parallax; submitting upside-down with
    ``flip_y=False`` made content mirrored/flipped and slide on-screen.
    """
    GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
    raw = GL.glReadPixels(0, 0, width, height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4).copy()


# ---------------------------------------------------------------------------
# GL widget with injectable SRD cameras
# ---------------------------------------------------------------------------
class SRDGLViewWidget(gl.GLViewWidget):
    """
    ``GLViewWidget`` that can temporarily use SRD eye view/projection matrices
    instead of the interactive orbit camera.

    Use it exactly like ``pyqtgraph.opengl.GLViewWidget`` for the desktop
    preview.  While an SRD eye is being rendered, ``viewMatrix`` /
    ``projectionMatrix`` / ``cameraPosition`` / ``pixelSize`` follow the SRD
    eye, and ``width``/``height`` report the fixed eye render size.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._override_view: Optional[QtGui.QMatrix4x4] = None
        self._override_proj: Optional[QtGui.QMatrix4x4] = None
        self._srd_pixel_size: Optional[Tuple[int, int]] = None
        self._srd_eye_pos_cm: Optional[Tuple[float, float, float]] = None

    def width(self) -> int:
        if self._srd_pixel_size is not None:
            return int(self._srd_pixel_size[0])
        return int(super().width())

    def height(self) -> int:
        if self._srd_pixel_size is not None:
            return int(self._srd_pixel_size[1])
        return int(super().height())

    def deviceWidth(self) -> int:
        if self._srd_pixel_size is not None:
            return int(self._srd_pixel_size[0])
        if hasattr(super(), "deviceWidth"):
            return int(super().deviceWidth())
        dpr = (
            float(self.devicePixelRatioF())
            if hasattr(self, "devicePixelRatioF")
            else float(self.devicePixelRatio())
        )
        return max(1, int(super().width() * dpr))

    def deviceHeight(self) -> int:
        if self._srd_pixel_size is not None:
            return int(self._srd_pixel_size[1])
        if hasattr(super(), "deviceHeight"):
            return int(super().deviceHeight())
        dpr = (
            float(self.devicePixelRatioF())
            if hasattr(self, "devicePixelRatioF")
            else float(self.devicePixelRatio())
        )
        return max(1, int(super().height() * dpr))

    def getViewport(self):
        if self._srd_pixel_size is not None:
            w, h = self._srd_pixel_size
            return (0, 0, int(w), int(h))
        return super().getViewport()

    def cameraPosition(self):
        if self._srd_eye_pos_cm is not None:
            return pg.Vector(
                self._srd_eye_pos_cm[0],
                self._srd_eye_pos_cm[1],
                self._srd_eye_pos_cm[2],
            )
        return super().cameraPosition()

    def pixelSize(self, pos):
        if self._srd_eye_pos_cm is None:
            return super().pixelSize(pos)

        cam = np.asarray(self._srd_eye_pos_cm, dtype=np.float64)
        if isinstance(pos, np.ndarray):
            p = np.asarray(pos, dtype=np.float64)
            cam_b = cam.reshape((1,) * (p.ndim - 1) + (3,))
            dist = np.sqrt(((p - cam_b) ** 2).sum(axis=-1))
            dist = np.maximum(dist, 1e-3)
        else:
            try:
                dist = float((pos - pg.Vector(*self._srd_eye_pos_cm)).length())
            except Exception:
                dist = float(np.linalg.norm(cam))
            dist = max(dist, 1e-3)

        fov = float(self.opts.get("fov", 40.0))
        x_dist = dist * 2.0 * math.tan(math.radians(0.5 * fov))
        return x_dist / float(max(1, self.width()))

    def viewMatrix(self):
        if self._override_view is not None:
            return QtGui.QMatrix4x4(self._override_view)
        return super().viewMatrix()

    def projectionMatrix(self, region=None, viewport=None, *args, **kwargs):
        if self._override_proj is not None:
            return QtGui.QMatrix4x4(self._override_proj)

        if viewport is None and not args:
            try:
                return super().projectionMatrix(region)
            except TypeError:
                vp = region if region is not None else self.getViewport()
                return super().projectionMatrix(region, vp)

        if viewport is None and args:
            viewport = args[0]

        try:
            return super().projectionMatrix(region, viewport)
        except TypeError:
            return super().projectionMatrix(region)

    def set_srd_cameras(
        self,
        view: Optional[np.ndarray],
        proj: Optional[np.ndarray],
        eye_pos_cm: Optional[Sequence[float]] = None,
    ) -> None:
        self._override_view = None if view is None else np_to_qmatrix(view)
        self._override_proj = None if proj is None else np_to_qmatrix(proj)
        if eye_pos_cm is None:
            self._srd_eye_pos_cm = None
        else:
            self._srd_eye_pos_cm = (
                float(eye_pos_cm[0]),
                float(eye_pos_cm[1]),
                float(eye_pos_cm[2]),
            )

    def clear_srd_cameras(self) -> None:
        self._override_view = None
        self._override_proj = None
        self._srd_eye_pos_cm = None

    def paint_frame(self, region, viewport=None):
        """Call paint() / paintGL() across pyqtgraph versions."""
        if viewport is None:
            viewport = region
        paint = getattr(self, "paint", None)
        if callable(paint):
            try:
                paint(region=region, viewport=viewport)
                return
            except TypeError:
                try:
                    paint(region=region)
                    return
                except TypeError:
                    pass
        try:
            self.paintGL(region=region, viewport=viewport)
        except TypeError:
            try:
                self.paintGL(region=region)
            except TypeError:
                self.paintGL()


# ---------------------------------------------------------------------------
# Stereo presenter
# ---------------------------------------------------------------------------
class StereoPresenter:
    """
    Render an ``SRDGLViewWidget`` scene for both SRD eyes and submit RGBA.

    The Qt widget remains a normal interactive orbit preview.  Scale,
    translation, and optional X-mirror are applied only while presenting.
    ``mirror_x`` defaults to True so SRD left/right matches the Qt preview
    (NativeAPI tracking already reflects X/Z; this undoes the L/R swap on
    the display).  Pass ``False`` only if your content already matches.
    """

    def __init__(
        self,
        view: SRDGLViewWidget,
        *,
        units: str = "mm",
        display_magnification: float = 15.0,
        world_scale: Optional[float] = None,
        scene_translation: Optional[Sequence[float]] = None,
        center_scene: bool = True,
        mirror_x: bool = True,
        near_z: float = 1.0,
        far_z: float = 1000.0,
        render_scale: Optional[float] = 0.5,
        show_preview: bool = True,
        dll_path: Optional[Union[str, Path]] = None,
        init_session: bool = False,
    ):
        self.view = view
        self.dll_path = dll_path
        self.units = units
        self.display_magnification = float(display_magnification)
        self.world_scale = resolve_world_scale(
            units=units,
            display_magnification=display_magnification,
            world_scale=world_scale,
        )
        self._scene_translation_arg = scene_translation
        self.center_scene = bool(center_scene)
        self.mirror_x = bool(mirror_x)
        self.near_z = float(near_z)
        self.far_z = float(far_z)
        self.render_scale = render_scale
        self.show_preview = bool(show_preview)

        self.eye_w = 0
        self.eye_h = 0
        self.render_w = 0
        self.render_h = 0
        self.scene_translation = (0.0, 0.0, 0.0)
        self._world_matrix = np.eye(4, dtype=np.float32)
        self._srd_ready = False
        self._gl_ready = False
        self._scatter_size_backup = []
        self._saved_fov = None
        self._srd_fbo = None
        self._srd_fbo_size = (0, 0)

        if init_session:
            self.start_session()
        elif srd.is_initialized():
            self._bind_to_session()

    def start_session(self) -> None:
        """Load the DLL and start the SRD session if needed."""
        srd.load(self.dll_path)
        srd.silence_client_stdio()
        if not srd.is_initialized():
            if not srd.init(self.dll_path, mute_native_prints=True):
                raise RuntimeError(f"SRD unavailable: {srd.last_error()}")
        try:
            srd.set_log_level("off")
        except Exception:
            pass
        self._bind_to_session()

    def _bind_to_session(self) -> None:
        self.eye_w, self.eye_h = srd.eye_resolution()
        if self.render_scale is None:
            scale = 1.0
        else:
            scale = max(0.05, min(float(self.render_scale), 1.0))
        self.render_w = max(64, int(self.eye_w * scale))
        self.render_h = max(64, int(self.eye_h * scale))
        self.scene_translation = resolve_scene_translation_cm(
            self._scene_translation_arg,
            center_scene=self.center_scene,
        )
        self._world_matrix = make_world_matrix(
            abs(float(self.world_scale)), self.scene_translation
        )
        self._srd_ready = True
        self._gl_ready = False

    def shutdown(self) -> None:
        self._srd_ready = False
        self._gl_ready = False
        self._srd_fbo = None
        self._srd_fbo_size = (0, 0)
        if srd.is_initialized():
            srd.shutdown()

    def set_world_transform(
        self,
        scale: Optional[float] = None,
        translation: Optional[Sequence[float]] = None,
        units: Optional[str] = None,
        display_magnification: Optional[float] = None,
        mirror_x: Optional[bool] = None,
        center_scene: Optional[bool] = None,
    ) -> None:
        if units is not None:
            self.units = units
        if display_magnification is not None:
            self.display_magnification = float(display_magnification)
        if scale is not None:
            self.world_scale = float(scale)
        elif units is not None or display_magnification is not None:
            self.world_scale = resolve_world_scale(
                units=self.units,
                display_magnification=self.display_magnification,
                world_scale=None,
            )
        if center_scene is not None:
            self.center_scene = bool(center_scene)
        if translation is not None:
            self._scene_translation_arg = tuple(map(float, translation))
        if translation is not None or center_scene is not None:
            self.scene_translation = resolve_scene_translation_cm(
                self._scene_translation_arg,
                center_scene=self.center_scene,
            )
        if mirror_x is not None:
            self.mirror_x = bool(mirror_x)
        self._world_matrix = make_world_matrix(
            abs(float(self.world_scale)), self.scene_translation
        )

    def _ensure_gl_ready(self) -> bool:
        if self.view is None:
            return False
        if self._gl_ready and self.view.isValid():
            self.view.makeCurrent()
            return True
        try:
            _ = self.view.winId()
        except Exception:
            pass
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents()
        self.view.makeCurrent()
        if not self.view.isValid():
            return False
        try:
            self.view.makeCurrent()
            if hasattr(self.view, "defaultFramebufferObject"):
                _ = self.view.defaultFramebufferObject()
        except Exception:
            return False
        self._gl_ready = True
        return True

    def _iter_graphics_items(self):
        def walk(item):
            yield item
            for child in item.childItems():
                yield from walk(child)

        for top in list(getattr(self.view, "items", [])):
            yield from walk(top)

    def _ensure_srd_fbo(self):
        w, h = int(self.render_w), int(self.render_h)
        if (
            self._srd_fbo is not None
            and self._srd_fbo_size == (w, h)
            and self._srd_fbo.isValid()
        ):
            return self._srd_fbo

        fmt = QtGui.QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QtGui.QOpenGLFramebufferObject.CombinedDepthStencil)
        fmt.setSamples(0)
        self._srd_fbo = QtGui.QOpenGLFramebufferObject(w, h, fmt)
        if not self._srd_fbo.isValid():
            raise RuntimeError("Failed to create SRD offscreen framebuffer")
        self._srd_fbo_size = (w, h)
        return self._srd_fbo

    def _scatter_pixel_sizes(
        self,
        item: "gl.GLScatterPlotItem",
        eye_pos_cm: Sequence[float],
        fov_deg: float,
        width_px: int,
    ) -> np.ndarray:
        pos = getattr(item, "pos", None)
        if pos is None:
            return np.asarray([1.0], dtype=np.float32)

        pos = np.asarray(pos, dtype=np.float64)
        if pos.ndim != 2 or pos.shape[1] != 3:
            pos = pos.reshape(-1, 3)

        s = abs(float(self.world_scale))
        t = np.asarray(self.scene_translation, dtype=np.float64).reshape(1, 3)
        p_cm = pos * s + t
        eye = np.asarray(eye_pos_cm, dtype=np.float64).reshape(1, 3)
        dist = np.linalg.norm(p_cm - eye, axis=1)
        dist = np.maximum(dist, 1e-3)

        px_world = dist * 2.0 * math.tan(math.radians(0.5 * float(fov_deg))) / float(
            max(1, width_px)
        )

        size = item.size
        if isinstance(size, np.ndarray):
            size_cm = np.asarray(size, dtype=np.float64).reshape(-1) * s
            if size_cm.size == 1:
                size_cm = np.full(pos.shape[0], float(size_cm[0]), dtype=np.float64)
            elif size_cm.size != pos.shape[0]:
                size_cm = np.full(pos.shape[0], float(size_cm[0]), dtype=np.float64)
        else:
            size_cm = np.full(pos.shape[0], float(size) * s, dtype=np.float64)

        pix = size_cm / np.maximum(px_world, 1e-12)
        return np.clip(pix, 0.5, float(max(1, width_px))).astype(np.float32)

    def _begin_srd_scatter_fix(
        self,
        eye: int,
        eye_pos_cm: Sequence[float],
        width_px: int,
    ) -> None:
        self._saved_fov = self.view.opts.get("fov")
        try:
            fov = float(srd.projection_fov_deg(eye))
        except Exception:
            fov = float(self.view.opts.get("fov", 40.0))
        self.view.opts["fov"] = fov

        self._scatter_size_backup = []
        for item in self._iter_graphics_items():
            if not isinstance(item, gl.GLScatterPlotItem):
                continue
            if getattr(item, "pxMode", True):
                continue
            old_size = item.size
            old_px = bool(item.pxMode)
            try:
                pix = self._scatter_pixel_sizes(item, eye_pos_cm, fov, width_px)
            except Exception as exc:
                print(f"SRD scatter size skip: {exc}")
                continue
            self._scatter_size_backup.append((item, old_size, old_px))
            item.pxMode = True
            item.size = pix
            try:
                item.setData(size=pix, pxMode=True)
            except Exception:
                pass

    def _end_srd_scatter_fix(self) -> None:
        if self._saved_fov is not None:
            self.view.opts["fov"] = self._saved_fov
            self._saved_fov = None
        for entry in self._scatter_size_backup:
            if len(entry) == 3:
                item, size, px_mode = entry
            else:
                item, size = entry
                px_mode = False
            item.size = size
            item.pxMode = px_mode
            try:
                item.setData(size=size, pxMode=px_mode)
            except Exception:
                pass
        self._scatter_size_backup = []

    def _eye_matrices(
        self, eye: int
    ) -> Tuple[np.ndarray, np.ndarray, Tuple[float, float, float]]:
        view = srd.view_matrix(eye)
        eye_pos_cm = eye_pos_cm_from_view(view)
        world = np.asarray(self._world_matrix, dtype=np.float32).reshape(4, 4)
        if self.mirror_x:
            mirror = np.eye(4, dtype=np.float32)
            mirror[0, 0] = -1.0
            view = view @ mirror @ world
        else:
            view = view @ world
        proj = srd.projection_matrix(eye, self.near_z, self.far_z)
        return view, proj, eye_pos_cm

    def _render_eye_rgba(self, eye: int) -> np.ndarray:
        view, proj, eye_pos_cm = self._eye_matrices(eye)
        vw, vh = int(self.render_w), int(self.render_h)
        self.view.set_srd_cameras(view, proj, eye_pos_cm=eye_pos_cm)
        self.view._srd_pixel_size = (vw, vh)
        self._begin_srd_scatter_fix(eye, eye_pos_cm, vw)
        prev_fbo = None
        try:
            self.view.makeCurrent()
            fbo = self._ensure_srd_fbo()
            try:
                prev_fbo = GL.glGetIntegerv(GL.GL_FRAMEBUFFER_BINDING)
            except Exception:
                prev_fbo = None

            if not fbo.bind():
                raise RuntimeError("SRD FBO bind failed")

            GL.glViewport(0, 0, vw, vh)
            region = (0, 0, vw, vh)
            self.view.paint_frame(region, region)
            GL.glFinish()
            rgba = read_rgba_from_gl(vw, vh)
        finally:
            try:
                if self._srd_fbo is not None:
                    self._srd_fbo.release()
            except Exception:
                pass
            if prev_fbo is not None:
                try:
                    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, int(prev_fbo))
                except Exception:
                    pass
            self.view._srd_pixel_size = None
            self._end_srd_scatter_fix()
            self.view.clear_srd_cameras()
        return rgba

    def present(self) -> bool:
        """
        Render left/right eyes and submit to the SRD.

        Returns False if the SRD window was closed or the bridge is not ready.
        """
        if not self._srd_ready or self.view is None:
            return False
        if not srd.poll_events():
            self._srd_ready = False
            return False
        if not self._ensure_gl_ready():
            return False

        try:
            srd.update_tracking()
        except RuntimeError:
            pass

        try:
            left = self._render_eye_rgba(srd.EYE_LEFT)
            right = self._render_eye_rgba(srd.EYE_RIGHT)
            # GL readback is bottom-left origin; tell SubmitOpengl via flip_y.
            srd.submit_stereo(left, right, flip_y=True)
        except Exception as exc:
            print(f"StereoPresenter present skipped: {exc}")
            try:
                self.view._srd_pixel_size = None
                self.view.clear_srd_cameras()
            except Exception:
                pass
            return False

        if self.show_preview:
            self.view.update()
        return True


# ---------------------------------------------------------------------------
# Lightweight QtApp
# ---------------------------------------------------------------------------
class SRDAppAbstract(QtCore.QObject):
    """
    Minimal helper that owns an ``SRDGLViewWidget`` + ``StereoPresenter``
    pair, forwards Qt key events to the demo subclass, and gives subclasses
    a single ``_setupWindow()`` hook to build their scene in.

    Subclasses should:
      - override ``_setupWindow()`` to add items to ``self.win`` and start
        whatever ``QTimer`` drives their animation,
      - call ``self.present_to_srd()`` once per frame from that timer,
      - override ``keyPressEvent(self, ev)`` if they want key handling.
    """

    def __init__(
        self,
        *,
        units: str = "mm",
        display_magnification: float = 10.0,
        mirror_x: bool = True,
        render_scale: float | None = 0.5,
        show_preview: bool = True,
        world_scale: float | None = None,
        scene_translation=None,
        center_scene: bool = True,
        near_z: float = 1.0,
        far_z: float = 1000.0,
        dll_path=None,
    ):
        super().__init__()
        self.units = units
        self.display_magnification = float(display_magnification)
        self.mirror_x = mirror_x
        self.render_scale = render_scale
        self.show_preview = show_preview

        # The GL widget itself -- usable directly as a normal interactive
        # pyqtgraph.opengl.GLViewWidget for the desktop preview.
        self.win = SRDGLViewWidget()
        self.win.keyPressEvent = self.keyPressEvent  # forward key events to demo

        self.presenter = StereoPresenter(
            self.win,
            units=units,
            display_magnification=display_magnification,
            world_scale=world_scale,
            scene_translation=scene_translation,
            center_scene=center_scene,
            mirror_x=mirror_x,
            near_z=near_z,
            far_z=far_z,
            render_scale=render_scale,
            show_preview=show_preview,
            dll_path=dll_path,
            init_session=False,
        )

    def onStart(self) -> None:
        """Start (or bind to) the SRD session, then build the scene."""
        self.presenter.start_session()
        self._setupWindow()

    def onExit(self) -> None:
        self.presenter.shutdown()

    def present_to_srd(self) -> bool:
        return self.presenter.present()

    def _setupWindow(self) -> None:
        raise NotImplementedError

    def keyPressEvent(self, ev) -> None:  # override in subclasses
        pass
    
    def set_world_transform(
        self,
        scale: Optional[float] = None,
        translation: Optional[Sequence[float]] = None,
        units: Optional[str] = None,
        display_magnification: Optional[float] = None,
        mirror_x: Optional[bool] = None,
        center_scene: Optional[bool] = None,
    ) -> None:
        if self.presenter is None:
            return
        self.presenter.set_world_transform(
            scale=scale,
            translation=translation,
            units=units,
            display_magnification=display_magnification,
            mirror_x=mirror_x,
            center_scene=center_scene,
        )
        self.units = self.presenter.units
        self.display_magnification = self.presenter.display_magnification
        self.world_scale = self.presenter.world_scale
        self.scene_translation = self.presenter.scene_translation
        self.mirror_x = self.presenter.mirror_x
        self.center_scene = self.presenter.center_scene