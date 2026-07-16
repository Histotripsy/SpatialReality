"""
Python ctypes bindings for SRDBridge.dll

The C library owns the SRD window / OpenGL context.  From Python you generate
RGBA frames (numpy arrays) and submit them each frame.

Typical loop
------------
    from spatial_reality import bridge as srd
    import numpy as np

    if not srd.init():
        raise RuntimeError(srd.last_error())

    w, h = srd.eye_resolution()
    try:
        while srd.poll_events():
            srd.update_tracking()
            view_l = srd.view_matrix(srd.EYE_LEFT)
            proj_l = srd.projection_matrix(srd.EYE_LEFT)

            # Build left/right RGBA images however you like (plots, offscreen GL, ...)
            left = np.zeros((h, w, 4), dtype=np.uint8)
            right = np.zeros((h, w, 4), dtype=np.uint8)
            left[..., 3] = 255
            right[..., 3] = 255

            srd.submit_stereo(left, right)
    finally:
        srd.shutdown()
"""

from __future__ import annotations

import ctypes
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_float,
    c_int,
    c_uint,
    c_uint8,
)
from pathlib import Path
from typing import Optional, Tuple, Union

import numpy as np

# ---------------------------------------------------------------------------
# Constants (mirror SRDBridge.h)
# ---------------------------------------------------------------------------
EYE_LEFT = 0
EYE_RIGHT = 1
EYE_HEAD = 2

ArrayLike = Union[np.ndarray, memoryview, bytes]


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------
class SRDPose(Structure):
    _fields_ = [
        ("position", c_float * 3),
        ("orientation", c_float * 4),
    ]


class SRDDisplayInfo(Structure):
    _fields_ = [
        ("width_px", c_int),
        ("height_px", c_int),
        ("width_m", c_float),
        ("height_m", c_float),
        ("tilt_rad", c_float),
        ("monitor_left", c_int),
        ("monitor_top", c_int),
        ("monitor_right", c_int),
        ("monitor_bottom", c_int),
    ]


# ---------------------------------------------------------------------------
# DLL loading
# ---------------------------------------------------------------------------
def _repo_root() -> Path:
    """Repo root when developing from a checkout; else the package parent."""
    here = Path(__file__).resolve().parent
    repo = here.parent
    if (repo / "CMakeLists.txt").is_file() and (repo / "src" / "SRDBridge.cpp").is_file():
        return repo
    return here.parent


def _candidate_dll_paths() -> list[Path]:
    import os

    names = ("SRDBridge.dll", "libSRDBridge.dll", "libSRDBridge.so")
    out: list[Path] = []

    env = os.environ.get("SRD_BRIDGE_DLL") or os.environ.get("SPATIAL_REALITY_DLL")
    if env:
        out.append(Path(env))

    repo = _repo_root()
    pkg = Path(__file__).resolve().parent
    roots = [
        repo / "build" / "Release",
        repo / "build" / "Debug",
        repo / "build",
        pkg / "bin",
        pkg,
        Path.cwd() / "build" / "Release",
        Path.cwd() / "build",
    ]
    for root in roots:
        for name in names:
            out.append(root / name)

    # de-dupe
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def _auto_build_enabled() -> bool:
    """Build the DLL via scripts/build_dll.py when missing (default: on Windows)."""
    import os
    import sys

    flag = os.environ.get("SRD_AUTO_BUILD")
    if flag is not None:
        return flag.strip().lower() not in ("0", "false", "no", "off")
    return sys.platform == "win32"


def _try_auto_build() -> None:
    if not _auto_build_enabled():
        return
    root = _repo_root()
    if not (root / "CMakeLists.txt").is_file():
        return
    script = root / "scripts" / "build_dll.py"
    if not script.is_file():
        return
    import runpy

    print("SRDBridge.dll not found — running scripts/build_dll.py …")
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code not in (0, None):
            raise


def _load_dll(dll_path: Optional[Union[str, Path]] = None) -> ctypes.CDLL:
    if dll_path is not None:
        path = Path(dll_path)
        if not path.exists():
            raise FileNotFoundError(f"SRDBridge DLL not found: {path}")
        return ctypes.CDLL(str(path))

    tried = []
    for path in _candidate_dll_paths():
        tried.append(str(path))
        if path.exists():
            return ctypes.CDLL(str(path))

    # One automatic CMake build attempt when developing from a source checkout.
    try:
        _try_auto_build()
    except SystemExit as exc:
        raise FileNotFoundError(
            "SRDBridge.dll missing and auto-build failed. "
            "Install the Sony XR_API (see XR_API/README.md), then run: "
            "python scripts/build_dll.py"
        ) from exc
    except Exception as exc:
        raise FileNotFoundError(
            "SRDBridge.dll missing and auto-build failed "
            f"({exc}). Run: python scripts/build_dll.py"
        ) from exc

    tried = []
    for path in _candidate_dll_paths():
        tried.append(str(path))
        if path.exists():
            return ctypes.CDLL(str(path))

    raise FileNotFoundError(
        "SRDBridge.dll not found. Build it with `python scripts/build_dll.py` "
        "(requires Sony XR_API — see XR_API/README.md), set SRD_BRIDGE_DLL, "
        "or pass dll_path=. Tried:\n  " + "\n  ".join(tried)
    )


_dll: Optional[ctypes.CDLL] = None


def _dll_or_raise() -> ctypes.CDLL:
    if _dll is None:
        raise RuntimeError("spatial_reality.bridge is not loaded; call load() or init() first")
    return _dll


def _bind(dll: ctypes.CDLL) -> None:
    dll.SRD_Init.restype = c_int
    dll.SRD_Init.argtypes = []

    dll.SRD_Shutdown.restype = None
    dll.SRD_Shutdown.argtypes = []

    dll.SRD_IsInitialized.restype = c_int
    dll.SRD_IsInitialized.argtypes = []

    dll.SRD_PollEvents.restype = c_int
    dll.SRD_PollEvents.argtypes = []

    dll.SRD_GetDisplayInfo.restype = c_int
    dll.SRD_GetDisplayInfo.argtypes = [POINTER(SRDDisplayInfo)]

    dll.SRD_GetEyeResolution.restype = c_int
    dll.SRD_GetEyeResolution.argtypes = [POINTER(c_int), POINTER(c_int)]

    dll.SRD_UpdateTracking.restype = c_int
    dll.SRD_UpdateTracking.argtypes = []

    dll.SRD_GetEyePose.restype = c_int
    dll.SRD_GetEyePose.argtypes = [c_int, POINTER(SRDPose)]

    dll.SRD_GetViewMatrix.restype = c_int
    dll.SRD_GetViewMatrix.argtypes = [c_int, POINTER(c_float)]

    dll.SRD_GetProjectionMatrix.restype = c_int
    dll.SRD_GetProjectionMatrix.argtypes = [c_int, c_float, c_float, POINTER(c_float)]

    if hasattr(dll, "SRD_GetProjectionHalfAngles"):
        dll.SRD_GetProjectionHalfAngles.restype = c_int
        dll.SRD_GetProjectionHalfAngles.argtypes = [
            c_int,
            POINTER(c_float),
            POINTER(c_float),
            POINTER(c_float),
            POINTER(c_float),
        ]

    dll.SRD_SubmitRGBA.restype = c_int
    dll.SRD_SubmitRGBA.argtypes = [POINTER(c_uint8), c_int, c_int, c_int]

    dll.SRD_SubmitStereoRGBA.restype = c_int
    dll.SRD_SubmitStereoRGBA.argtypes = [
        POINTER(c_uint8),
        POINTER(c_uint8),
        c_int,
        c_int,
        c_int,
    ]

    dll.SRD_SubmitTexture.restype = c_int
    dll.SRD_SubmitTexture.argtypes = [c_uint, c_int]

    dll.SRD_MakeCurrent.restype = c_int
    dll.SRD_MakeCurrent.argtypes = []

    dll.SRD_GetLastError.restype = c_char_p
    dll.SRD_GetLastError.argtypes = []

    dll.SRD_SetLogLevel.restype = None
    dll.SRD_SetLogLevel.argtypes = [c_int]

    # Optional: older DLLs may not export this yet.
    if hasattr(dll, "SRD_MuteCrtStdio"):
        dll.SRD_MuteCrtStdio.restype = None
        dll.SRD_MuteCrtStdio.argtypes = []


def load(dll_path: Optional[Union[str, Path]] = None) -> ctypes.CDLL:
    """Load (or reload) the native library. Called automatically by init()."""
    global _dll
    _dll = _load_dll(dll_path)
    _bind(_dll)
    return _dll


def last_error() -> str:
    dll = _dll
    if dll is None:
        return "spatial_reality.bridge DLL not loaded"
    msg = dll.SRD_GetLastError()
    if not msg:
        return ""
    return msg.decode("utf-8", errors="replace")


def _require(ok: int, action: str) -> None:
    if not ok:
        err = last_error()
        raise RuntimeError(f"{action} failed" + (f": {err}" if err else ""))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
_LOG_LEVELS = {
    "trace": 0,
    "debug": 1,
    "info": 2,
    "warn": 3,
    "warning": 3,
    "err": 4,
    "error": 4,
    "critical": 5,
    "off": 6,
}

_CRT_STDIO_SILENCED = False


def silence_client_stdio() -> bool:
    """
    Mute native ``[client] …`` / ``fail: send…`` prints without breaking
    Python ``print`` or multiprocessing.

    Steps (all attempted; partial success is OK):
      1. Dup console fds 1/2 and rebind ``sys.stdout`` / ``sys.stderr`` to them
      2. ``os.dup2(NUL, 1/2)`` so OS-level writes to those fds go nowhere
      3. On Windows, ``SetStdHandle`` stdout/stderr to NUL (covers MSVC CRTs
         that cache Win32 handles)
      4. ``SRD_MuteCrtStdio()`` freopen of CRT ``stdout``/``stderr`` in the DLL

    Returns True if at least one muting step succeeded.
    """
    global _CRT_STDIO_SILENCED
    if _CRT_STDIO_SILENCED:
        return True

    import os
    import sys

    muted = False

    def _rebind_from_fd(stream_name: str, fd: int) -> bool:
        stream = getattr(sys, stream_name, None)
        src_fd = fd
        if stream is not None:
            try:
                src_fd = stream.fileno()
            except Exception:
                src_fd = fd
        try:
            dup_fd = os.dup(src_fd)
        except Exception:
            return False
        encoding = getattr(stream, "encoding", None) if stream is not None else None
        errors = getattr(stream, "errors", None) if stream is not None else None
        encoding = encoding or "utf-8"
        errors = errors or "replace"
        try:
            new_stream = open(
                dup_fd,
                mode="w",
                encoding=encoding,
                errors=errors,
                buffering=1,
                closefd=True,
                newline="\n",
            )
        except Exception:
            try:
                os.close(dup_fd)
            except Exception:
                pass
            return False
        setattr(sys, stream_name, new_stream)
        setattr(sys, f"__{stream_name}__", new_stream)
        return True

    # Keep Python talking to the real console via duplicated fds FIRST.
    _rebind_from_fd("stdout", 1)
    _rebind_from_fd("stderr", 2)

    # OS fd redirect — affects writers using fileno 1/2.
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            muted = True
        finally:
            os.close(devnull)
    except Exception:
        pass

    # Win32 standard handles — many MSVC printf paths use these.
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            GENERIC_WRITE = 0x40000000
            FILE_SHARE_READ = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            OPEN_EXISTING = 3
            STD_OUTPUT_HANDLE = -11
            STD_ERROR_HANDLE = -12
            kernel32.CreateFileW.restype = ctypes.c_void_p
            nul = kernel32.CreateFileW(
                "NUL",
                GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                0,
                None,
            )
            INVALID = ctypes.c_void_p(-1).value
            if nul not in (None, 0, INVALID):
                kernel32.SetStdHandle(STD_OUTPUT_HANDLE, ctypes.c_void_p(nul))
                kernel32.SetStdHandle(STD_ERROR_HANDLE, ctypes.c_void_p(nul))
                muted = True
        except Exception:
            pass

    # CRT FILE* freopen inside SRDBridge.dll (same UCRT as /MD dependents).
    dll = _dll
    if dll is not None and hasattr(dll, "SRD_MuteCrtStdio"):
        try:
            dll.SRD_MuteCrtStdio()
            muted = True
        except Exception:
            pass

    _CRT_STDIO_SILENCED = muted
    return muted


def set_log_level(level: Union[str, int] = "off") -> None:
    """
    Filter XR runtime logs routed through SetDebugLogCallback.

    Levels: trace, debug, info, warn, err, critical, off (or 0..6).
    Default is ``off``. For ``[client]`` printf spam use ``silence_client_stdio``.
    """
    if isinstance(level, str):
        key = level.strip().lower()
        if key not in _LOG_LEVELS:
            raise ValueError(f"Unknown log level {level!r}; expected one of {list(_LOG_LEVELS)}")
        level_i = _LOG_LEVELS[key]
    else:
        level_i = int(level)
    _dll_or_raise().SRD_SetLogLevel(level_i)


def init(
    dll_path: Optional[Union[str, Path]] = None,
    log_level: Union[str, int] = "off",
    mute_native_prints: bool = True,
) -> bool:
    """Create the SRD window/session. Returns False on failure (see last_error)."""
    if _dll is None:
        load(dll_path)
    elif dll_path is not None:
        load(dll_path)
    try:
        set_log_level(log_level)
    except Exception:
        pass
    # MUST run before SRD_Init / LinkXrLibrary so session setup spam is muted.
    # (Parameter must not be named silence_client_stdio — that shadows the fn.)
    if mute_native_prints:
        silence_client_stdio()
    return bool(_dll_or_raise().SRD_Init())


def shutdown() -> None:
    """Tear down the SRD session. Safe to call when not loaded / not initialized."""
    if _dll is None:
        return
    _dll.SRD_Shutdown()


def is_initialized() -> bool:
    return bool(_dll_or_raise().SRD_IsInitialized()) if _dll else False


def poll_events() -> bool:
    """Pump window events. Returns False when the SRD window should close."""
    if not is_initialized():
        return False
    return bool(_dll_or_raise().SRD_PollEvents())


def display_info() -> dict:
    info = SRDDisplayInfo()
    _require(_dll_or_raise().SRD_GetDisplayInfo(byref(info)), "SRD_GetDisplayInfo")
    return {
        "width_px": info.width_px,
        "height_px": info.height_px,
        "width_m": info.width_m,
        "height_m": info.height_m,
        "tilt_rad": info.tilt_rad,
        "monitor": (
            info.monitor_left,
            info.monitor_top,
            info.monitor_right,
            info.monitor_bottom,
        ),
    }


def eye_resolution() -> Tuple[int, int]:
    w = c_int()
    h = c_int()
    _require(
        _dll_or_raise().SRD_GetEyeResolution(byref(w), byref(h)),
        "SRD_GetEyeResolution",
    )
    return int(w.value), int(h.value)


def update_tracking() -> None:
    _require(_dll_or_raise().SRD_UpdateTracking(), "SRD_UpdateTracking")


def get_pose(eye: int = EYE_LEFT) -> Tuple[np.ndarray, np.ndarray]:
    """Return (position[3], orientation_xyzw[4]) in meters / unit quaternion."""
    pose = SRDPose()
    ok = _dll_or_raise().SRD_GetEyePose(int(eye), byref(pose))
    if not ok:
        err = last_error()
        raise RuntimeError("SRD_GetEyePose failed" + (f": {err}" if err else ""))
    return (
        np.array(pose.position, dtype=np.float32),
        np.array(pose.orientation, dtype=np.float32),
    )


def view_matrix(eye: int = EYE_LEFT) -> np.ndarray:
    """Column-major 4x4 view matrix (cm), returned as a (4, 4) numpy array."""
    buf = (c_float * 16)()
    _require(
        _dll_or_raise().SRD_GetViewMatrix(int(eye), buf),
        "SRD_GetViewMatrix",
    )
    return np.ctypeslib.as_array(buf).reshape(4, 4, order="F").copy()


def projection_matrix(
    eye: int = EYE_LEFT,
    near_z: float = 1.0,
    far_z: float = 1000.0,
) -> np.ndarray:
    """Column-major 4x4 projection matrix as a (4, 4) numpy array."""
    buf = (c_float * 16)()
    _require(
        _dll_or_raise().SRD_GetProjectionMatrix(
            int(eye), float(near_z), float(far_z), buf
        ),
        "SRD_GetProjectionMatrix",
    )
    return np.ctypeslib.as_array(buf).reshape(4, 4, order="F").copy()


def projection_half_angles(eye: int = EYE_LEFT) -> Tuple[float, float, float, float]:
    """Return (left, right, top, bottom) half-angles in radians."""
    dll = _dll_or_raise()
    if not hasattr(dll, "SRD_GetProjectionHalfAngles"):
        raise RuntimeError("SRDBridge.dll is missing SRD_GetProjectionHalfAngles; rebuild it")
    left = c_float()
    right = c_float()
    top = c_float()
    bottom = c_float()
    _require(
        dll.SRD_GetProjectionHalfAngles(
            int(eye), byref(left), byref(right), byref(top), byref(bottom)
        ),
        "SRD_GetProjectionHalfAngles",
    )
    return float(left.value), float(right.value), float(top.value), float(bottom.value)


def projection_fov_deg(eye: int = EYE_LEFT) -> float:
    """
    Horizontal field-of-view in degrees for pyqtgraph scatter sizing.

    GLScatterPlotItem (pxMode=False) sizes points using ``view.opts['fov']`` as
    horizontal FOV — set that to this value while rendering for the SRD.
    """
    import math

    try:
        left, right, _top, _bottom = projection_half_angles(eye)
        return float(math.degrees(abs(left) + abs(right)))
    except RuntimeError:
        # Older DLL without SRD_GetProjectionHalfAngles — approximate.
        return 40.0


def _as_rgba_u8(image: ArrayLike, name: str) -> np.ndarray:
    arr = np.asarray(image)
    if arr.dtype != np.uint8:
        if np.issubdtype(arr.dtype, np.floating):
            arr = np.clip(arr * (255.0 if arr.max() <= 1.0 else 1.0), 0, 255).astype(
                np.uint8
            )
        else:
            arr = np.clip(arr, 0, 255).astype(np.uint8)

    if arr.ndim == 2:
        # grayscale -> RGBA
        rgb = np.repeat(arr[:, :, None], 3, axis=2)
        alpha = np.full(arr.shape + (1,), 255, dtype=np.uint8)
        arr = np.concatenate([rgb, alpha], axis=2)
    elif arr.ndim == 3 and arr.shape[2] == 3:
        alpha = np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)
        arr = np.concatenate([arr, alpha], axis=2)
    elif not (arr.ndim == 3 and arr.shape[2] == 4):
        raise ValueError(
            f"{name} must be HxW, HxWx3, or HxWx4; got shape {arr.shape}"
        )

    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    return arr


def submit_rgba(image: ArrayLike, flip_y: bool = False) -> None:
    """Submit a side-by-side RGBA frame (height x 2*eye_width x 4)."""
    arr = _as_rgba_u8(image, "image")
    h, w, _ = arr.shape
    ptr = arr.ctypes.data_as(POINTER(c_uint8))
    _require(
        _dll_or_raise().SRD_SubmitRGBA(ptr, int(w), int(h), int(bool(flip_y))),
        "SRD_SubmitRGBA",
    )


def submit_stereo(
    left: ArrayLike,
    right: ArrayLike,
    flip_y: bool = False,
) -> None:
    """
    Submit separate left/right eye RGBA frames of equal size.

    Pass ``flip_y=True`` when buffers come from ``glReadPixels`` (OpenGL
    bottom-left origin), matching ``SubmitOpengl`` / the OpenXR swapchain path.
    CPU-generated top-left images should keep the default ``False``.
    """
    left_a = _as_rgba_u8(left, "left")
    right_a = _as_rgba_u8(right, "right")
    if left_a.shape != right_a.shape:
        raise ValueError(
            f"left/right shape mismatch: {left_a.shape} vs {right_a.shape}"
        )
    h, w, _ = left_a.shape
    _require(
        _dll_or_raise().SRD_SubmitStereoRGBA(
            left_a.ctypes.data_as(POINTER(c_uint8)),
            right_a.ctypes.data_as(POINTER(c_uint8)),
            int(w),
            int(h),
            int(bool(flip_y)),
        ),
        "SRD_SubmitStereoRGBA",
    )


def present_stereo_frame(
    left: ArrayLike,
    right: ArrayLike,
    *,
    flip_y: bool = False,
    track: bool = True,
) -> bool:
    """
    One CPU-stereo frame: ``poll_events`` → optional tracking → ``submit_stereo``.

    Returns ``False`` when the bridge is not initialized or the SRD window
    should close (stop submitting; still call ``shutdown()`` on exit).
    """
    if not poll_events():
        return False
    if track:
        try:
            update_tracking()
        except RuntimeError:
            pass
    submit_stereo(left, right, flip_y=flip_y)
    return True


def submit_texture(texture_id: int, flip_y: bool = False) -> None:
    """Advanced: submit a GL texture that already lives in the bridge context."""
    _require(
        _dll_or_raise().SRD_SubmitTexture(c_uint(texture_id), int(bool(flip_y))),
        "SRD_SubmitTexture",
    )


def make_current() -> None:
    _require(_dll_or_raise().SRD_MakeCurrent(), "SRD_MakeCurrent")


class SRDSession:
    """Context-manager wrapper around init/shutdown."""

    def __init__(self, dll_path: Optional[Union[str, Path]] = None):
        self.dll_path = dll_path

    def __enter__(self) -> "SRDSession":
        if not init(self.dll_path):
            raise RuntimeError(f"SRD_Init failed: {last_error()}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        shutdown()

    def poll(self) -> bool:
        return poll_events()

    def present(
        self,
        left: ArrayLike,
        right: ArrayLike,
        *,
        flip_y: bool = False,
        track: bool = True,
    ) -> bool:
        """See :func:`present_stereo_frame`."""
        return present_stereo_frame(left, right, flip_y=flip_y, track=track)
