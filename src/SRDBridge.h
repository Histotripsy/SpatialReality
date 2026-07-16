#pragma once

#include <stdint.h>

#ifdef _WIN32
  #ifdef SRDBRIDGE_EXPORTS
    #define XR_API __declspec(dllexport)
  #else
    #define XR_API __declspec(dllimport)
  #endif
#else
  #define XR_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/** Eye / camera selector for pose and projection queries. */
enum SRDEye {
    SRD_EYE_LEFT  = 0,
    SRD_EYE_RIGHT = 1,
    SRD_EYE_HEAD  = 2
};

/** Rigid pose: position in meters, orientation as xyzw quaternion. */
struct SRDPose {
    float position[3];
    float orientation[4];
};

/**
 * Physical display description (matches SonyOzDisplaySpec, SI units).
 * width_m / height_m are screen dimensions in meters.
 * tilt_rad is the panel tilt from horizontal.
 */
struct SRDDisplayInfo {
    int   width_px;
    int   height_px;
    float width_m;
    float height_m;
    float tilt_rad;
    int   monitor_left;
    int   monitor_top;
    int   monitor_right;
    int   monitor_bottom;
};

/**
 * Create the SRD session, place a borderless GLFW window on the SR Display,
 * and allocate internal side-by-side + composite GL textures.
 *
 * Must be called once from the thread that will call submit / poll.
 * Returns false on failure; call SRD_GetLastError() for details.
 *
 * By default installs a quiet SDK log callback (level OFF). Call
 * SRD_SetLogLevel to re-enable runtime logs. Native CRT prints such as
 * "fail: send, there is no receiver" cannot be redirected without breaking
 * Python's stdout — they are harmless startup noise.
 */
XR_API int SRD_Init(void);

/**
 * Control XR runtime logging via SetDebugLogCallback.
 * Levels match SonyOzLogSettings_LogLevels:
 *   0=TRACE 1=DEBUG 2=INFO 3=WARN 4=ERR 5=CRITICAL 6=OFF
 * Default after Init is OFF.
 */
XR_API void SRD_SetLogLevel(int level);

/**
 * freopen CRT stdout/stderr to NUL.
 * Call only AFTER Python has rebound sys.stdout/sys.stderr onto duplicated
 * console file descriptors (see spatial_reality.bridge.silence_client_stdio).
 * Silences native "[client] …" / "fail: send…" printf spam.
 */
XR_API void SRD_MuteCrtStdio(void);

/** Tear down GL resources, end the XR session, and destroy the window. */
XR_API void SRD_Shutdown(void);

/** Non-zero if Init succeeded and Shutdown has not been called. */
XR_API int SRD_IsInitialized(void);

/**
 * Pump GLFW events and keep the window alive.
 * Returns 0 if the user closed the window (caller should Shutdown).
 */
XR_API int SRD_PollEvents(void);

/** Fill display size / placement. Safe after successful Init. */
XR_API int SRD_GetDisplayInfo(SRDDisplayInfo* out_info);

/** Convenience: eye render target size in pixels (one eye). */
XR_API int SRD_GetEyeResolution(int* out_width, int* out_height);

/**
 * Refresh tracked poses from the runtime. Call once per frame before
 * GetEyePose / GetViewMatrix / GetProjectionMatrix.
 */
XR_API int SRD_UpdateTracking(void);

/**
 * Read a cached eye/head pose.
 * @param eye  SRD_EYE_LEFT / RIGHT / HEAD
 */
XR_API int SRD_GetEyePose(int eye, SRDPose* out_pose);

/**
 * Column-major 4x4 view matrix in centimeters (same convention as the
 * NativeAPI sample MakeViewMatrix). Suitable for OpenGL cameras.
 */
XR_API int SRD_GetViewMatrix(int eye, float* out_matrix16);

/**
 * Column-major 4x4 projection matrix built from the runtime half-angles
 * via a right-handed frustum (same as the NativeAPI sample).
 */
XR_API int SRD_GetProjectionMatrix(
    int eye,
    float near_z,
    float far_z,
    float* out_matrix16
);

/**
 * Raw projection half-angles in radians (asymmetric frustum).
 * Useful for matching pyqtgraph scatter sizing to the SRD FOV.
 */
XR_API int SRD_GetProjectionHalfAngles(
    int eye,
    float* out_left,
    float* out_right,
    float* out_top,
    float* out_bottom
);

/**
 * Upload a side-by-side RGBA8 frame and present it on the SR Display.
 *
 * @param rgba    tightly packed RGBA8 pixels, row-major, top-left origin
 *                unless flip_y is non-zero
 * @param width   full SBS width in pixels (typically 2 * eye_width)
 * @param height  frame height in pixels
 * @param flip_y  non-zero if the buffer origin is bottom-left (OpenGL style)
 */
XR_API int SRD_SubmitRGBA(
    const uint8_t* rgba,
    int width,
    int height,
    int flip_y
);

/**
 * Upload separate left/right RGBA8 eye buffers, pack them side-by-side,
 * and present. Each buffer is eye_width * eye_height * 4 bytes.
 */
XR_API int SRD_SubmitStereoRGBA(
    const uint8_t* left_rgba,
    const uint8_t* right_rgba,
    int eye_width,
    int eye_height,
    int flip_y
);

/**
 * Advanced: submit an existing GL texture that already lives in the
 * bridge's GL context as a side-by-side image.
 * Prefer SubmitRGBA / SubmitStereoRGBA from Python.
 */
XR_API int SRD_SubmitTexture(
    unsigned int side_by_side_texture,
    int flip_y
);

/** Make the bridge GLFW/GL context current on the calling thread. */
XR_API int SRD_MakeCurrent(void);

/** Null-terminated last error string (valid until next API call). */
XR_API const char* SRD_GetLastError(void);

#ifdef __cplusplus
}
#endif
