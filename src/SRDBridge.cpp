#include "SRDBridge.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <iterator>

#include <GL/gl3w.h>
#include <GLFW/glfw3.h>

#if defined(_WIN32)
#define GLFW_EXPOSE_NATIVE_WIN32
#include <GLFW/glfw3native.h>
#include <Windows.h>
#endif

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <glm/gtc/type_ptr.hpp>

#include <xr_api_wrapper.h>
#include <xr_api_wrapper_utility.h>
#include <xr_basic_api_wrapper.h>

using namespace sony::oz::xr_runtime;

namespace {

constexpr const char* kPlatformId = "Spatial Reality Display";

struct FrameTarget {
    GLuint fbo = 0;
    GLuint texture = 0;
    int width = 0;
    int height = 0;

    void destroy()
    {
        if (fbo) {
            glDeleteFramebuffers(1, &fbo);
            fbo = 0;
        }
        if (texture) {
            glDeleteTextures(1, &texture);
            texture = 0;
        }
        width = height = 0;
    }

    bool create(int w, int h)
    {
        destroy();
        width = w;
        height = h;

        glGenTextures(1, &texture);
        glBindTexture(GL_TEXTURE_2D, texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glBindTexture(GL_TEXTURE_2D, 0);

        glGenFramebuffers(1, &fbo);
        glBindFramebuffer(GL_FRAMEBUFFER, fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
        const GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return status == GL_FRAMEBUFFER_COMPLETE;
    }

    bool ensureSize(int w, int h)
    {
        if (texture != 0 && width == w && height == h) {
            return true;
        }
        return create(w, h);
    }
};

struct BridgeState {
    bool initialized = false;
    GLFWwindow* window = nullptr;
    SonyOzSessionHandle session = nullptr;

    SonyOzRect monitorRect{};
    int deviceWidth = 0;
    int deviceHeight = 0;
    SonyOzDisplaySpec displaySpec{};

    FrameTarget sideBySide;
    FrameTarget composite;

    // Last valid tracked poses (LEFT=0, RIGHT=1, HEAD=2). Used when the
    // runtime briefly reports an invalid pose (no face in view yet, etc.).
    SonyOzPosef lastPose[3]{};
    bool hasLastPose[3] = {false, false, false};

    char lastError[512] = {};
};

BridgeState g;

// Default: OFF — swallow XR SDK console noise. Call SRD_SetLogLevel to raise.
static int g_logLevel = static_cast<int>(SonyOzLogSettings_LogLevels::OFF);
static bool g_logCallbackInstalled = false;
static bool g_crtStdioMuted = false;

void setError(const char* msg)
{
    if (!msg) {
        g.lastError[0] = '\0';
        return;
    }
    std::snprintf(g.lastError, sizeof(g.lastError), "%s", msg);
#if defined(_WIN32)
    // Avoid CRT stderr after SRD_MuteCrtStdio(); still visible in DebugView.
    char buf[640];
    std::snprintf(buf, sizeof(buf), "[SRDBridge] %s\n", msg);
    OutputDebugStringA(buf);
#else
    std::cerr << "[SRDBridge] " << msg << std::endl;
#endif
}

void srdLogCallback(const char* message, SonyOzLogSettings_LogLevels level)
{
    // Drop everything below the configured level (OFF drops all).
    if (static_cast<int>(level) < g_logLevel) {
        return;
    }
    if (g_logLevel >= static_cast<int>(SonyOzLogSettings_LogLevels::OFF)) {
        return;
    }
    if (!message) {
        return;
    }
#if defined(_WIN32)
    OutputDebugStringA(message);
    if (message[0] != '\0' && message[std::strlen(message) - 1] != '\n') {
        OutputDebugStringA("\n");
    }
#else
    std::cerr << message;
    if (message[0] != '\0' && message[std::strlen(message) - 1] != '\n') {
        std::cerr << '\n';
    }
#endif
}

void applyLogSettings()
{
    // Callback can only be installed after LinkXrLibrary.
    if (!g_logCallbackInstalled) {
        return;
    }
    SetDebugLogCallback(kPlatformId, &srdLogCallback);
}

int eyeIndex(int eye)
{
    switch (eye) {
    case SRD_EYE_RIGHT:
        return 1;
    case SRD_EYE_HEAD:
        return 2;
    case SRD_EYE_LEFT:
    default:
        return 0;
    }
}

SonyOzPoseId toPoseId(int eye)
{
    switch (eye) {
    case SRD_EYE_RIGHT:
        return SonyOzPoseId::RIGHT_EYE;
    case SRD_EYE_HEAD:
        return SonyOzPoseId::HEAD;
    case SRD_EYE_LEFT:
    default:
        return SonyOzPoseId::LEFT_EYE;
    }
}

SonyOzPosef defaultPoseFallback()
{
    // Neutral head pose ~50 cm in front of the display origin (meters).
    SonyOzPosef pose{};
    pose.position.x = 0.0f;
    pose.position.y = 0.15f;
    pose.position.z = 0.50f;
    pose.orientation.x = 0.0f;
    pose.orientation.y = 0.0f;
    pose.orientation.z = 0.0f;
    pose.orientation.w = 1.0f;
    return pose;
}

bool fetchPose(int eye, SonyOzPosef* out_pose)
{
    if (!out_pose || !g.session) {
        return false;
    }

    // Always refresh the cache before reading; callers may skip UpdateTracking.
    UpdateTrackingResultCache(g.session);

    SonyOzPosef pose{};
    bool valid = false;
    const SonyOzResult result =
        GetCachedPose(g.session, toPoseId(eye), &pose, &valid);
    const int idx = eyeIndex(eye);

    if (result == SonyOzResult::SUCCESS && valid) {
        g.lastPose[idx] = pose;
        g.hasLastPose[idx] = true;
        *out_pose = pose;
        return true;
    }

    // Tracking often reports invalid before a face is detected. Keep rendering
    // with the last good pose, or a sane default, instead of failing the frame.
    if (g.hasLastPose[idx]) {
        *out_pose = g.lastPose[idx];
        return true;
    }

    *out_pose = defaultPoseFallback();
    return true;
}

bool ensureSessionRunning()
{
    if (!g.session) {
        setError("SRD session is not initialized");
        return false;
    }
    SonyOzSessionState state = SonyOzSessionState::UNKNOWN;
    if (GetSessionState(g.session, &state) != SonyOzResult::SUCCESS) {
        setError("GetSessionState failed");
        return false;
    }
    if (state != SonyOzSessionState::RUNNING) {
        setError("SRD session is not RUNNING");
        return false;
    }
    return true;
}

bool placeWindowOnSrd()
{
#if defined(_WIN32)
    HWND hwnd = glfwGetWin32Window(g.window);
    if (!hwnd) {
        setError("Failed to get Win32 HWND for SRD window");
        return false;
    }
    SetWindowLong(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE);
    const int w = g.monitorRect.right - g.monitorRect.left;
    const int h = g.monitorRect.bottom - g.monitorRect.top;
    if (!MoveWindow(hwnd, g.monitorRect.left, g.monitorRect.top, w, h, TRUE)) {
        setError("MoveWindow failed for SRD monitor");
        return false;
    }
    return true;
#else
    glfwSetWindowPos(g.window, g.monitorRect.left, g.monitorRect.top);
    glfwSetWindowSize(
        g.window,
        g.monitorRect.right - g.monitorRect.left,
        g.monitorRect.bottom - g.monitorRect.top);
    return true;
#endif
}

bool createGlResources()
{
    if (!g.sideBySide.create(g.deviceWidth * 2, g.deviceHeight)) {
        setError("Failed to create side-by-side framebuffer");
        return false;
    }
    if (!g.composite.create(g.deviceWidth, g.deviceHeight)) {
        setError("Failed to create composite framebuffer");
        return false;
    }
    return true;
}

void destroyGlResources()
{
    g.sideBySide.destroy();
    g.composite.destroy();
}

glm::mat4 makeViewMatrix(const SonyOzPosef& pose)
{
    // Match NativeAPI sample: reflect through XZ (tracking → OpenGL cm space).
    const auto inv_xz = glm::mat3(
        -1, 0, 0,
        0, 1, 0,
        0, 0, -1);

    auto camRot = glm::quat(pose.orientation.w, pose.orientation.x, pose.orientation.y, pose.orientation.z);
    auto camPos = glm::vec3(pose.position.x, pose.position.y, pose.position.z);
    camPos = (glm::mat4(inv_xz) * glm::translate(glm::mat4(1), camPos) * glm::mat4(inv_xz))[3];
    camRot = glm::quat_cast(inv_xz * glm::mat3_cast(camRot) * inv_xz);
    camPos *= 100.0f;

    return glm::inverse(glm::translate(glm::mat4(1), camPos) * glm::mat4_cast(camRot));
}

glm::mat4 makeProjectionMatrix(const SonyOzProjection& proj, float nearClip, float farClip)
{
    // Match OpenXR CreateProjectionFov(GRAPHICS_OPENGL): use signed half-angles
    // as frustum edges (angleLeft/bottom typically ≤ 0, right/top ≥ 0).
    // NativeAPI GetProjection returns the same convention as XrFovf.
    const float left = nearClip * std::tan(proj.half_angles_left);
    const float right = nearClip * std::tan(proj.half_angles_right);
    const float top = nearClip * std::tan(proj.half_angles_top);
    const float bottom = nearClip * std::tan(proj.half_angles_bottom);
    return glm::frustumRH(left, right, bottom, top, nearClip, farClip);
}

void presentCompositeToWindow()
{
    glfwMakeContextCurrent(g.window);
    int winW = 0;
    int winH = 0;
    glfwGetFramebufferSize(g.window, &winW, &winH);

    glBindFramebuffer(GL_READ_FRAMEBUFFER, g.composite.fbo);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
    glBlitFramebuffer(
        0, 0, g.composite.width, g.composite.height,
        0, 0, winW, winH,
        GL_COLOR_BUFFER_BIT,
        GL_NEAREST);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    glfwSwapBuffers(g.window);
}

bool submitSideBySideTexture(GLuint sbsTexture, int flip_y)
{
    if (!ensureSessionRunning()) {
        return false;
    }
    if (!g.composite.texture) {
        setError("Composite texture is not allocated");
        return false;
    }

    glfwMakeContextCurrent(g.window);

    const SonyOzResult result = SubmitOpengl(
        g.session,
        sbsTexture,
        flip_y != 0,
        g.composite.texture);

    if (result != SonyOzResult::SUCCESS) {
        setError("SubmitOpengl failed");
        return false;
    }

    presentCompositeToWindow();
    return true;
}

bool uploadSbsRgba(const uint8_t* rgba, int width, int height)
{
    if (!rgba || width <= 0 || height <= 0) {
        setError("Invalid RGBA buffer");
        return false;
    }

    glfwMakeContextCurrent(g.window);
    if (!g.sideBySide.ensureSize(width, height)) {
        setError("Failed to resize side-by-side texture");
        return false;
    }

    glBindTexture(GL_TEXTURE_2D, g.sideBySide.texture);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexSubImage2D(
        GL_TEXTURE_2D,
        0,
        0,
        0,
        width,
        height,
        GL_RGBA,
        GL_UNSIGNED_BYTE,
        rgba);
    glBindTexture(GL_TEXTURE_2D, 0);
    return true;
}

}  // namespace


extern "C" void SRD_SetLogLevel(int level)
{
    if (level < 0) {
        level = 0;
    }
    if (level > static_cast<int>(SonyOzLogSettings_LogLevels::OFF)) {
        level = static_cast<int>(SonyOzLogSettings_LogLevels::OFF);
    }
    g_logLevel = level;
    applyLogSettings();
}

extern "C" void SRD_MuteCrtStdio(void)
{
    // Python must already have rebound sys.stdout/sys.stderr to duplicated
    // console FDs before this runs, otherwise print() breaks (WinError 1).
    if (g_crtStdioMuted) {
        return;
    }
#if defined(_WIN32)
    FILE* nul_out = nullptr;
    FILE* nul_err = nullptr;
    freopen_s(&nul_out, "NUL", "w", stdout);
    freopen_s(&nul_err, "NUL", "w", stderr);
#else
    freopen("/dev/null", "w", stdout);
    freopen("/dev/null", "w", stderr);
#endif
    g_crtStdioMuted = true;
}

extern "C" int SRD_Init(void)
{
    if (g.initialized) {
        return 1;
    }
    setError(nullptr);

    if (!glfwInit()) {
        setError("glfwInit failed");
        return 0;
    }

    SonyOzResult result = LinkXrLibrary(kPlatformId);
    if (result != SonyOzResult::SUCCESS) {
        setError("LinkXrLibrary failed (is the Spatial Reality Display runtime installed?)");
        glfwTerminate();
        return 0;
    }

    // Redirect SDK logs through our filter (no CRT stdout freopen).
    g_logCallbackInstalled = true;
    applyLogSettings();

    SonyOzDeviceInfo devices[3]{};
    uint64_t deviceCount = static_cast<uint64_t>(std::size(devices));
    result = EnumerateDevices(kPlatformId, deviceCount, devices);
    if (result != SonyOzResult::SUCCESS || deviceCount == 0) {
        setError("No Spatial Reality Display devices found");
        UnlinkXrLibrary();
        glfwTerminate();
        return 0;
    }

    g.monitorRect = devices[0].target_monitor_rectangle;
    g.deviceWidth = g.monitorRect.right - g.monitorRect.left;
    g.deviceHeight = g.monitorRect.bottom - g.monitorRect.top;
    if (g.deviceWidth <= 0 || g.deviceHeight <= 0) {
        setError("Invalid SRD monitor rectangle");
        UnlinkXrLibrary();
        glfwTerminate();
        return 0;
    }

    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_FALSE);
    glfwWindowHint(GLFW_DECORATED, GLFW_FALSE);
    glfwWindowHint(GLFW_AUTO_ICONIFY, GLFW_FALSE);

    g.window = glfwCreateWindow(
        g.deviceWidth,
        g.deviceHeight,
        "SRDBridge",
        nullptr,
        nullptr);
    if (!g.window) {
        setError("glfwCreateWindow failed");
        UnlinkXrLibrary();
        glfwTerminate();
        return 0;
    }

    glfwMakeContextCurrent(g.window);
    glfwSwapInterval(1);

    if (gl3wInit() != 0) {
        setError("gl3wInit failed");
        glfwDestroyWindow(g.window);
        g.window = nullptr;
        UnlinkXrLibrary();
        glfwTerminate();
        return 0;
    }

    if (!placeWindowOnSrd()) {
        glfwDestroyWindow(g.window);
        g.window = nullptr;
        UnlinkXrLibrary();
        glfwTerminate();
        return 0;
    }

    result = CreateSession(
        kPlatformId,
        &devices[0],
        RUNTIME_OPTION_IS_XR_CONTENT,
        PLATFORM_OPTION_NONE,
        &g.session);
    if (result != SonyOzResult::SUCCESS || !g.session) {
        setError("CreateSession failed");
        glfwDestroyWindow(g.window);
        g.window = nullptr;
        UnlinkXrLibrary();
        glfwTerminate();
        return 0;
    }

    result = BeginSession(g.session);
    if (result != SonyOzResult::SUCCESS) {
        setError("BeginSession failed");
        DestroySession(&g.session);
        g.session = nullptr;
        glfwDestroyWindow(g.window);
        g.window = nullptr;
        UnlinkXrLibrary();
        glfwTerminate();
        return 0;
    }

    if (!utility::WaitUntilRunningState(g.session)) {
        setError("WaitUntilRunningState failed");
        EndSession(g.session);
        DestroySession(&g.session);
        g.session = nullptr;
        glfwDestroyWindow(g.window);
        g.window = nullptr;
        UnlinkXrLibrary();
        glfwTerminate();
        return 0;
    }

    // Best-effort quality flags; ignore unsupported features.
    SetHighImageQuality(kPlatformId, g.session, true);

    if (GetDisplaySpec(g.session, &g.displaySpec) != SonyOzResult::SUCCESS) {
        setError("GetDisplaySpec failed");
        EndSession(g.session);
        DestroySession(&g.session);
        g.session = nullptr;
        glfwDestroyWindow(g.window);
        g.window = nullptr;
        UnlinkXrLibrary();
        glfwTerminate();
        return 0;
    }

    EnableStereo(g.session, true);

    if (!createGlResources()) {
        EnableStereo(g.session, false);
        EndSession(g.session);
        DestroySession(&g.session);
        g.session = nullptr;
        destroyGlResources();
        glfwDestroyWindow(g.window);
        g.window = nullptr;
        UnlinkXrLibrary();
        glfwTerminate();
        return 0;
    }

    g.initialized = true;
    setError(nullptr);
    return 1;
}

extern "C" void SRD_Shutdown(void)
{
    if (!g.initialized && !g.window && !g.session) {
        return;
    }

    if (g.window) {
        glfwMakeContextCurrent(g.window);
    }

    destroyGlResources();

    if (g.session) {
        EnableStereo(g.session, false);
        EndSession(g.session);
        DestroySession(&g.session);
        g.session = nullptr;
    }

    if (g.window) {
        glfwDestroyWindow(g.window);
        g.window = nullptr;
    }

    UnlinkXrLibrary();
    glfwTerminate();

    g.initialized = false;
    g.deviceWidth = 0;
    g.deviceHeight = 0;
    g.hasLastPose[0] = g.hasLastPose[1] = g.hasLastPose[2] = false;
    setError(nullptr);
}

extern "C" int SRD_IsInitialized(void)
{
    return g.initialized ? 1 : 0;
}

extern "C" int SRD_PollEvents(void)
{
    if (!g.initialized || !g.window) {
        return 0;
    }
    glfwPollEvents();
    if (glfwWindowShouldClose(g.window)) {
        return 0;
    }
    return 1;
}

extern "C" int SRD_GetDisplayInfo(SRDDisplayInfo* out_info)
{
    if (!g.initialized || !out_info) {
        setError("SRD_GetDisplayInfo: not initialized or null out_info");
        return 0;
    }
    out_info->width_px = g.deviceWidth;
    out_info->height_px = g.deviceHeight;
    out_info->width_m = g.displaySpec.display_size.width_m;
    out_info->height_m = g.displaySpec.display_size.height_m;
    out_info->tilt_rad = g.displaySpec.display_tilt_rad;
    out_info->monitor_left = g.monitorRect.left;
    out_info->monitor_top = g.monitorRect.top;
    out_info->monitor_right = g.monitorRect.right;
    out_info->monitor_bottom = g.monitorRect.bottom;
    return 1;
}

extern "C" int SRD_GetEyeResolution(int* out_width, int* out_height)
{
    if (!g.initialized || !out_width || !out_height) {
        setError("SRD_GetEyeResolution: not initialized or null args");
        return 0;
    }
    *out_width = g.deviceWidth;
    *out_height = g.deviceHeight;
    return 1;
}

extern "C" int SRD_UpdateTracking(void)
{
    if (!ensureSessionRunning()) {
        return 0;
    }
    if (UpdateTrackingResultCache(g.session) != SonyOzResult::SUCCESS) {
        setError("UpdateTrackingResultCache failed");
        return 0;
    }
    return 1;
}

extern "C" int SRD_GetEyePose(int eye, SRDPose* out_pose)
{
    if (!out_pose) {
        setError("SRD_GetEyePose: null out_pose");
        return 0;
    }
    if (!ensureSessionRunning()) {
        return 0;
    }

    SonyOzPosef pose{};
    if (!fetchPose(eye, &pose)) {
        setError("GetCachedPose failed");
        return 0;
    }

    out_pose->position[0] = pose.position.x;
    out_pose->position[1] = pose.position.y;
    out_pose->position[2] = pose.position.z;
    out_pose->orientation[0] = pose.orientation.x;
    out_pose->orientation[1] = pose.orientation.y;
    out_pose->orientation[2] = pose.orientation.z;
    out_pose->orientation[3] = pose.orientation.w;
    return 1;
}

extern "C" int SRD_GetViewMatrix(int eye, float* out_matrix16)
{
    if (!out_matrix16) {
        setError("SRD_GetViewMatrix: null out_matrix16");
        return 0;
    }
    if (!ensureSessionRunning()) {
        return 0;
    }

    SonyOzPosef pose{};
    if (!fetchPose(eye, &pose)) {
        setError("GetCachedPose failed for view matrix");
        return 0;
    }

    const glm::mat4 view = makeViewMatrix(pose);
    std::memcpy(out_matrix16, glm::value_ptr(view), sizeof(float) * 16);
    return 1;
}

extern "C" int SRD_GetProjectionMatrix(
    int eye,
    float near_z,
    float far_z,
    float* out_matrix16)
{
    if (!out_matrix16) {
        setError("SRD_GetProjectionMatrix: null out_matrix16");
        return 0;
    }
    if (!ensureSessionRunning()) {
        return 0;
    }
    if (!(near_z > 0.0f) || !(far_z > near_z)) {
        setError("SRD_GetProjectionMatrix: invalid near/far");
        return 0;
    }

    SonyOzProjection projection{};
    UpdateTrackingResultCache(g.session);
    if (GetProjection(g.session, toPoseId(eye), &projection) != SonyOzResult::SUCCESS) {
        // Fallback symmetric FOV (~40 deg half-angle) so frames still render
        // before tracking / projection settle.
        projection.half_angles_left = 0.35f;
        projection.half_angles_right = 0.35f;
        projection.half_angles_top = 0.22f;
        projection.half_angles_bottom = 0.22f;
    }

    const glm::mat4 proj = makeProjectionMatrix(projection, near_z, far_z);
    std::memcpy(out_matrix16, glm::value_ptr(proj), sizeof(float) * 16);
    return 1;
}

extern "C" int SRD_GetProjectionHalfAngles(
    int eye,
    float* out_left,
    float* out_right,
    float* out_top,
    float* out_bottom)
{
    if (!out_left || !out_right || !out_top || !out_bottom) {
        setError("SRD_GetProjectionHalfAngles: null output");
        return 0;
    }
    if (!ensureSessionRunning()) {
        return 0;
    }

    SonyOzProjection projection{};
    UpdateTrackingResultCache(g.session);
    if (GetProjection(g.session, toPoseId(eye), &projection) != SonyOzResult::SUCCESS) {
        projection.half_angles_left = 0.35f;
        projection.half_angles_right = 0.35f;
        projection.half_angles_top = 0.22f;
        projection.half_angles_bottom = 0.22f;
    }
    *out_left = projection.half_angles_left;
    *out_right = projection.half_angles_right;
    *out_top = projection.half_angles_top;
    *out_bottom = projection.half_angles_bottom;
    return 1;
}

extern "C" int SRD_SubmitRGBA(
    const uint8_t* rgba,
    int width,
    int height,
    int flip_y)
{
    if (!g.initialized) {
        setError("SRD_SubmitRGBA: not initialized");
        return 0;
    }
    if (!uploadSbsRgba(rgba, width, height)) {
        return 0;
    }
    return submitSideBySideTexture(g.sideBySide.texture, flip_y) ? 1 : 0;
}

extern "C" int SRD_SubmitStereoRGBA(
    const uint8_t* left_rgba,
    const uint8_t* right_rgba,
    int eye_width,
    int eye_height,
    int flip_y)
{
    if (!g.initialized) {
        setError("SRD_SubmitStereoRGBA: not initialized");
        return 0;
    }
    if (!left_rgba || !right_rgba || eye_width <= 0 || eye_height <= 0) {
        setError("SRD_SubmitStereoRGBA: invalid eye buffers");
        return 0;
    }

    glfwMakeContextCurrent(g.window);
    const int sbsWidth = eye_width * 2;
    if (!g.sideBySide.ensureSize(sbsWidth, eye_height)) {
        setError("Failed to resize side-by-side texture for stereo submit");
        return 0;
    }

    glBindTexture(GL_TEXTURE_2D, g.sideBySide.texture);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexSubImage2D(
        GL_TEXTURE_2D, 0, 0, 0, eye_width, eye_height,
        GL_RGBA, GL_UNSIGNED_BYTE, left_rgba);
    glTexSubImage2D(
        GL_TEXTURE_2D, 0, eye_width, 0, eye_width, eye_height,
        GL_RGBA, GL_UNSIGNED_BYTE, right_rgba);
    glBindTexture(GL_TEXTURE_2D, 0);

    return submitSideBySideTexture(g.sideBySide.texture, flip_y) ? 1 : 0;
}

extern "C" int SRD_SubmitTexture(unsigned int side_by_side_texture, int flip_y)
{
    if (!g.initialized) {
        setError("SRD_SubmitTexture: not initialized");
        return 0;
    }
    if (side_by_side_texture == 0) {
        setError("SRD_SubmitTexture: texture id is 0");
        return 0;
    }
    return submitSideBySideTexture(static_cast<GLuint>(side_by_side_texture), flip_y) ? 1 : 0;
}

extern "C" int SRD_MakeCurrent(void)
{
    if (!g.initialized || !g.window) {
        setError("SRD_MakeCurrent: not initialized");
        return 0;
    }
    glfwMakeContextCurrent(g.window);
    return 1;
}

extern "C" const char* SRD_GetLastError(void)
{
    return g.lastError;
}
