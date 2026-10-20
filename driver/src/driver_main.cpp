// VRHand — виртуальный VR-шлем и два виртуальных контроллера (эмуляция Valve Index)
// для SteamVR. Позиции и кнопки приходят по UDP от Python-клиента (client/vrhand.py).
//
// Что создаёт драйвер:
//   * HMD  — виртуальный шлем с окном-дисплеем (как null-драйвер SteamVR, но с позой от клиента)
//   * левый и правый контроллеры "knuckles" (Index): триггер, грип, стик, A/B, касания

#include "openvr_driver.h"
#include "protocol.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#define VRHAND_EXPORT extern "C" __declspec(dllexport)
using socket_t = SOCKET;
static const socket_t kInvalidSocket = INVALID_SOCKET;
static void CloseSocket(socket_t s) { closesocket(s); }
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#define VRHAND_EXPORT extern "C" __attribute__((visibility("default")))
using socket_t = int;
static const socket_t kInvalidSocket = -1;
static void CloseSocket(socket_t s) { close(s); }
#endif

namespace {

using vrhand::Packet;

constexpr const char* kSettingsSection = "driver_vrhand";

void Log(const std::string& msg) {
    if (vr::VRDriverLog()) {
        vr::VRDriverLog()->Log(("[vrhand] " + msg + "\n").c_str());
    }
}

// ---------------------------------------------------------------------------
// Общее состояние: последнее, что прислал клиент
// ---------------------------------------------------------------------------
class SharedState {
public:
    SharedState() { Reset(); }

    void Reset() {
        std::lock_guard<std::mutex> lock(mutex_);
        std::memset(&packet_, 0, sizeof(packet_));
        packet_.magic = vrhand::kMagic;
        // голова: стоим, высота глаз 1.6 м, смотрим вперёд (-Z)
        packet_.head[1] = 1.6f;
        packet_.head[6] = 1.0f;
        // руки по умолчанию перед собой
        packet_.hand[0][0] = -0.25f;
        packet_.hand[0][1] = 1.25f;
        packet_.hand[0][2] = -0.35f;
        packet_.hand[0][6] = 1.0f;
        packet_.hand[1][0] = 0.25f;
        packet_.hand[1][1] = 1.25f;
        packet_.hand[1][2] = -0.35f;
        packet_.hand[1][6] = 1.0f;
    }

    void Set(const Packet& p) {
        std::lock_guard<std::mutex> lock(mutex_);
        packet_ = p;
        packets_received_++;
    }

    Packet Get() {
        std::lock_guard<std::mutex> lock(mutex_);
        return packet_;
    }

    uint64_t PacketsReceived() {
        std::lock_guard<std::mutex> lock(mutex_);
        return packets_received_;
    }

private:
    std::mutex mutex_;
    Packet packet_;
    uint64_t packets_received_ = 0;
};

SharedState g_state;

// ---------------------------------------------------------------------------
// Вспомогательное
// ---------------------------------------------------------------------------
bool Finite(float v) { return std::isfinite(v); }

float Clamp(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Проверяет и чинит пакет. Возвращает false, если пакет мусорный.
bool Sanitize(Packet& p) {
    if (p.magic != vrhand::kMagic) return false;

    auto fix_pose = [](float* pose) -> bool {
        for (int i = 0; i < 7; i++) {
            if (!Finite(pose[i])) return false;
        }
        for (int i = 0; i < 3; i++) pose[i] = Clamp(pose[i], -100.f, 100.f);
        float n = std::sqrt(pose[3] * pose[3] + pose[4] * pose[4] + pose[5] * pose[5] + pose[6] * pose[6]);
        if (n < 1e-3f) {
            pose[3] = pose[4] = pose[5] = 0.f;
            pose[6] = 1.f;
        } else {
            for (int i = 3; i < 7; i++) pose[i] /= n;
        }
        return true;
    };

    if (!fix_pose(p.head)) return false;
    for (int h = 0; h < 2; h++) {
        if (!fix_pose(p.hand[h])) return false;
        if (!Finite(p.trigger[h]) || !Finite(p.grip[h])) return false;
        p.trigger[h] = Clamp(p.trigger[h], 0.f, 1.f);
        p.grip[h] = Clamp(p.grip[h], 0.f, 1.f);
        for (int i = 0; i < 2; i++) {
            if (!Finite(p.stick[h][i])) return false;
            p.stick[h][i] = Clamp(p.stick[h][i], -1.f, 1.f);
        }
        for (int i = 0; i < 5; i++) {
            if (!Finite(p.fingers[h][i])) return false;
            p.fingers[h][i] = Clamp(p.fingers[h][i], 0.f, 1.f);
        }
    }
    return true;
}

vr::DriverPose_t MakePose(const float* pose7) {
    vr::DriverPose_t pose;
    std::memset(&pose, 0, sizeof(pose));

    pose.poseTimeOffset = 0.0;
    pose.qWorldFromDriverRotation.w = 1.0;
    pose.qDriverFromHeadRotation.w = 1.0;

    pose.vecPosition[0] = pose7[0];
    pose.vecPosition[1] = pose7[1];
    pose.vecPosition[2] = pose7[2];

    pose.qRotation.x = pose7[3];
    pose.qRotation.y = pose7[4];
    pose.qRotation.z = pose7[5];
    pose.qRotation.w = pose7[6];

    pose.result = vr::TrackingResult_Running_OK;
    pose.poseIsValid = true;
    pose.deviceIsConnected = true;
    pose.willDriftInYaw = false;
    pose.shouldApplyHeadModel = false;
    return pose;
}

// ---------------------------------------------------------------------------
// Виртуальный шлем
// ---------------------------------------------------------------------------
struct DisplayConfig {
    int32_t window_x = 0;
    int32_t window_y = 0;
    int32_t window_width = 1280;
    int32_t window_height = 720;
    int32_t render_width = 1080;   // на один глаз
    int32_t render_height = 1200;  // на один глаз
    float display_frequency = 60.f;
    float seconds_from_vsync_to_photons = 0.011f;
    float ipd = 0.063f;
};

class HmdDevice final : public vr::ITrackedDeviceServerDriver, public vr::IVRDisplayComponent {
public:
    explicit HmdDevice(const DisplayConfig& cfg) : cfg_(cfg) {}

    const char* Serial() const { return "VRHAND-HMD-0001"; }
    uint32_t ObjectId() const { return object_id_.load(); }

    vr::EVRInitError Activate(uint32_t object_id) override {
        object_id_ = object_id;
        vr::PropertyContainerHandle_t c = vr::VRProperties()->TrackedDeviceToPropertyContainer(object_id);
        auto* p = vr::VRProperties();

        p->SetStringProperty(c, vr::Prop_ModelNumber_String, "VRHand Virtual HMD");
        p->SetStringProperty(c, vr::Prop_ManufacturerName_String, "VRHand");
        p->SetStringProperty(c, vr::Prop_TrackingSystemName_String, "vrhand");
        p->SetFloatProperty(c, vr::Prop_UserIpdMeters_Float, cfg_.ipd);
        p->SetFloatProperty(c, vr::Prop_UserHeadToEyeDepthMeters_Float, 0.f);
        p->SetFloatProperty(c, vr::Prop_DisplayFrequency_Float, cfg_.display_frequency);
        p->SetFloatProperty(c, vr::Prop_SecondsFromVsyncToPhotons_Float, cfg_.seconds_from_vsync_to_photons);
        p->SetUint64Property(c, vr::Prop_CurrentUniverseId_Uint64, 2);
        // Окно показывается как обычное окно на рабочем столе, а не на весь экран.
        p->SetBoolProperty(c, vr::Prop_IsOnDesktop_Bool, false);
        p->SetBoolProperty(c, vr::Prop_DisplayDebugMode_Bool, true);
        return vr::VRInitError_None;
    }

    void Deactivate() override { object_id_ = vr::k_unTrackedDeviceIndexInvalid; }
    void EnterStandby() override {}

    void* GetComponent(const char* name) override {
        if (std::strcmp(name, vr::IVRDisplayComponent_Version) == 0) {
            return static_cast<vr::IVRDisplayComponent*>(this);
        }
        return nullptr;
    }

    void DebugRequest(const char*, char* response, uint32_t size) override {
        if (size > 0) response[0] = '\0';
    }

    vr::DriverPose_t GetPose() override {
        Packet p = g_state.Get();
        return MakePose(p.head);
    }

    // --- IVRDisplayComponent ---
    void GetWindowBounds(int32_t* x, int32_t* y, uint32_t* w, uint32_t* h) override {
        *x = cfg_.window_x;
        *y = cfg_.window_y;
        *w = static_cast<uint32_t>(cfg_.window_width);
        *h = static_cast<uint32_t>(cfg_.window_height);
    }
    bool IsDisplayOnDesktop() override { return true; }
    bool IsDisplayRealDisplay() override { return false; }

    void GetRecommendedRenderTargetSize(uint32_t* w, uint32_t* h) override {
        *w = static_cast<uint32_t>(cfg_.render_width);
        *h = static_cast<uint32_t>(cfg_.render_height);
    }

    void GetEyeOutputViewport(vr::EVREye eye, uint32_t* x, uint32_t* y, uint32_t* w, uint32_t* h) override {
        *y = 0;
        *w = static_cast<uint32_t>(cfg_.window_width) / 2;
        *h = static_cast<uint32_t>(cfg_.window_height);
        *x = (eye == vr::Eye_Left) ? 0 : *w;
    }

    void GetProjectionRaw(vr::EVREye, float* left, float* right, float* top, float* bottom) override {
        // В OpenVR "top" отрицательный, "bottom" положительный.
        *left = -1.0f;
        *right = 1.0f;
        *top = -1.0f;
        *bottom = 1.0f;
    }

    vr::DistortionCoordinates_t ComputeDistortion(vr::EVREye, float u, float v) override {
        vr::DistortionCoordinates_t d;
        d.rfRed[0] = u;
        d.rfRed[1] = v;
        d.rfGreen[0] = u;
        d.rfGreen[1] = v;
        d.rfBlue[0] = u;
        d.rfBlue[1] = v;
        return d;
    }

    bool ComputeInverseDistortion(vr::HmdVector2_t* result, vr::EVREye, uint32_t, float u, float v) override {
        result->v[0] = u;
        result->v[1] = v;
        return true;
    }

private:
    DisplayConfig cfg_;
    std::atomic<uint32_t> object_id_{vr::k_unTrackedDeviceIndexInvalid};
};

// ---------------------------------------------------------------------------
// Виртуальный контроллер (Valve Index)
// ---------------------------------------------------------------------------
class ControllerDevice final : public vr::ITrackedDeviceServerDriver {
public:
    // hand: 0 = левая, 1 = правая
    explicit ControllerDevice(int hand) : hand_(hand) {}

    const char* Serial() const { return hand_ == 0 ? "VRHAND-CTRL-LEFT" : "VRHAND-CTRL-RIGHT"; }
    uint32_t ObjectId() const { return object_id_.load(); }

    vr::EVRInitError Activate(uint32_t object_id) override {
        object_id_ = object_id;
        auto* p = vr::VRProperties();
        container_ = p->TrackedDeviceToPropertyContainer(object_id);
        const bool left = (hand_ == 0);

        p->SetStringProperty(container_, vr::Prop_ModelNumber_String, left ? "Knuckles Left" : "Knuckles Right");
        p->SetStringProperty(container_, vr::Prop_ManufacturerName_String, "Valve");
        p->SetStringProperty(container_, vr::Prop_TrackingSystemName_String, "indexcontroller");
        p->SetStringProperty(container_, vr::Prop_ControllerType_String, "knuckles");
        p->SetStringProperty(container_, vr::Prop_InputProfilePath_String,
                             "{indexcontroller}/input/index_controller_profile.json");
        p->SetStringProperty(container_, vr::Prop_RenderModelName_String,
                             left ? "{indexcontroller}valve_controller_knu_1_0_left"
                                  : "{indexcontroller}valve_controller_knu_1_0_right");
        p->SetStringProperty(container_, vr::Prop_RegisteredDeviceType_String,
                             left ? "valve/index_controllerVRHAND-LEFT" : "valve/index_controllerVRHAND-RIGHT");
        p->SetInt32Property(container_, vr::Prop_ControllerRoleHint_Int32,
                            left ? vr::TrackedControllerRole_LeftHand : vr::TrackedControllerRole_RightHand);

        auto* in = vr::VRDriverInput();
        in->CreateScalarComponent(container_, "/input/trigger/value", &trigger_value_, vr::VRScalarType_Absolute,
                                  vr::VRScalarUnits_NormalizedOneSided);
        in->CreateBooleanComponent(container_, "/input/trigger/click", &trigger_click_);
        in->CreateBooleanComponent(container_, "/input/trigger/touch", &trigger_touch_);

        in->CreateScalarComponent(container_, "/input/thumbstick/x", &stick_x_, vr::VRScalarType_Absolute,
                                  vr::VRScalarUnits_NormalizedTwoSided);
        in->CreateScalarComponent(container_, "/input/thumbstick/y", &stick_y_, vr::VRScalarType_Absolute,
                                  vr::VRScalarUnits_NormalizedTwoSided);
        in->CreateBooleanComponent(container_, "/input/thumbstick/click", &stick_click_);
        in->CreateBooleanComponent(container_, "/input/thumbstick/touch", &stick_touch_);

        in->CreateBooleanComponent(container_, "/input/a/click", &a_click_);
        in->CreateBooleanComponent(container_, "/input/a/touch", &a_touch_);
        in->CreateBooleanComponent(container_, "/input/b/click", &b_click_);
        in->CreateBooleanComponent(container_, "/input/b/touch", &b_touch_);

        in->CreateScalarComponent(container_, "/input/grip/value", &grip_value_, vr::VRScalarType_Absolute,
                                  vr::VRScalarUnits_NormalizedOneSided);
        in->CreateScalarComponent(container_, "/input/grip/force", &grip_force_, vr::VRScalarType_Absolute,
                                  vr::VRScalarUnits_NormalizedOneSided);
        in->CreateBooleanComponent(container_, "/input/grip/touch", &grip_touch_);

        // Изгиб пальцев. Если такого компонента нет в профиле, SteamVR вернёт ошибку — это не страшно.
        const char* finger_names[5] = {"/input/finger/thumb", "/input/finger/index", "/input/finger/middle",
                                       "/input/finger/ring", "/input/finger/pinky"};
        for (int i = 0; i < 5; i++) {
            in->CreateScalarComponent(container_, finger_names[i], &finger_[i], vr::VRScalarType_Absolute,
                                      vr::VRScalarUnits_NormalizedOneSided);
        }

        in->CreateHapticComponent(container_, "/output/haptic", &haptic_);
        return vr::VRInitError_None;
    }

    void Deactivate() override { object_id_ = vr::k_unTrackedDeviceIndexInvalid; }
    void EnterStandby() override {}
    void* GetComponent(const char*) override { return nullptr; }
    void DebugRequest(const char*, char* response, uint32_t size) override {
        if (size > 0) response[0] = '\0';
    }

    vr::DriverPose_t GetPose() override {
        Packet p = g_state.Get();
        return MakePose(p.hand[hand_]);
    }

    // Вызывается из RunFrame (поток SteamVR): обновляет кнопки и оси.
    void UpdateInputs(const Packet& p) {
        if (object_id_.load() == vr::k_unTrackedDeviceIndexInvalid) return;
        auto* in = vr::VRDriverInput();

        const float trigger = p.trigger[hand_];
        const float grip = p.grip[hand_];
        const float sx = p.stick[hand_][0];
        const float sy = p.stick[hand_][1];
        const uint32_t b = p.buttons[hand_];
        const bool stick_click = (b & vrhand::kBtnStickClick) != 0;
        const bool a = (b & vrhand::kBtnA) != 0;
        const bool bb = (b & vrhand::kBtnB) != 0;

        in->UpdateScalarComponent(trigger_value_, trigger, 0.0);
        in->UpdateBooleanComponent(trigger_click_, trigger > 0.7f, 0.0);
        in->UpdateBooleanComponent(trigger_touch_, trigger > 0.05f, 0.0);

        in->UpdateScalarComponent(stick_x_, sx, 0.0);
        in->UpdateScalarComponent(stick_y_, sy, 0.0);
        in->UpdateBooleanComponent(stick_click_, stick_click, 0.0);
        in->UpdateBooleanComponent(stick_touch_, stick_click || std::fabs(sx) > 0.05f || std::fabs(sy) > 0.05f, 0.0);

        in->UpdateBooleanComponent(a_click_, a, 0.0);
        in->UpdateBooleanComponent(a_touch_, a, 0.0);
        in->UpdateBooleanComponent(b_click_, bb, 0.0);
        in->UpdateBooleanComponent(b_touch_, bb, 0.0);

        in->UpdateScalarComponent(grip_value_, grip, 0.0);
        in->UpdateScalarComponent(grip_force_, grip, 0.0);
        in->UpdateBooleanComponent(grip_touch_, grip > 0.05f, 0.0);

        for (int i = 0; i < 5; i++) {
            in->UpdateScalarComponent(finger_[i], p.fingers[hand_][i], 0.0);
        }
    }

private:
    int hand_;
    std::atomic<uint32_t> object_id_{vr::k_unTrackedDeviceIndexInvalid};
    vr::PropertyContainerHandle_t container_ = vr::k_ulInvalidPropertyContainer;

    vr::VRInputComponentHandle_t trigger_value_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t trigger_click_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t trigger_touch_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t stick_x_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t stick_y_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t stick_click_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t stick_touch_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t a_click_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t a_touch_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t b_click_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t b_touch_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t grip_value_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t grip_force_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t grip_touch_ = vr::k_ulInvalidInputComponentHandle;
    vr::VRInputComponentHandle_t finger_[5] = {
        vr::k_ulInvalidInputComponentHandle, vr::k_ulInvalidInputComponentHandle,
        vr::k_ulInvalidInputComponentHandle, vr::k_ulInvalidInputComponentHandle,
        vr::k_ulInvalidInputComponentHandle};
    vr::VRInputComponentHandle_t haptic_ = vr::k_ulInvalidInputComponentHandle;
};

// ---------------------------------------------------------------------------
// Провайдер: создаёт устройства, слушает UDP, обновляет позы
// ---------------------------------------------------------------------------
class VrHandProvider : public vr::IServerTrackedDeviceProvider {
public:
    vr::EVRInitError Init(vr::IVRDriverContext* context) override {
        VR_INIT_SERVER_DRIVER_CONTEXT(context);
        Log("Init");

        ReadSettings();

        if (!StartUdp()) {
            Log("UDP не запустился — драйвер работает без клиента (позы по умолчанию)");
        }

        hmd_ = new HmdDevice(display_);
        left_ = new ControllerDevice(0);
        right_ = new ControllerDevice(1);

        vr::VRServerDriverHost()->TrackedDeviceAdded(hmd_->Serial(), vr::TrackedDeviceClass_HMD, hmd_);
        if (enable_controllers_) {
            vr::VRServerDriverHost()->TrackedDeviceAdded(left_->Serial(), vr::TrackedDeviceClass_Controller, left_);
            vr::VRServerDriverHost()->TrackedDeviceAdded(right_->Serial(), vr::TrackedDeviceClass_Controller, right_);
        }

        running_ = true;
        pose_thread_ = std::thread([this]() { PoseLoop(); });
        return vr::VRInitError_None;
    }

    void Cleanup() override {
        Log("Cleanup");
        running_ = false;
        if (pose_thread_.joinable()) pose_thread_.join();
        StopUdp();

        delete hmd_;
        delete left_;
        delete right_;
        hmd_ = nullptr;
        left_ = nullptr;
        right_ = nullptr;
        VR_CLEANUP_SERVER_DRIVER_CONTEXT();
    }

    const char* const* GetInterfaceVersions() override { return vr::k_InterfaceVersions; }

    void RunFrame() override {
        // Разгребаем очередь событий (хаптика и т.п. нам не нужны).
        vr::VREvent_t ev;
        while (vr::VRServerDriverHost()->PollNextEvent(&ev, sizeof(ev))) {
        }

        Packet p = g_state.Get();
        if (enable_controllers_ && left_ && right_) {
            left_->UpdateInputs(p);
            right_->UpdateInputs(p);
        }
    }

    bool ShouldBlockStandbyMode() override { return false; }
    void EnterStandby() override {}
    void LeaveStandby() override {}

private:
    void ReadSettings() {
        auto* s = vr::VRSettings();
        vr::EVRSettingsError err = vr::VRSettingsError_None;

        auto geti = [&](const char* key, int32_t def) {
            err = vr::VRSettingsError_None;
            int32_t v = s->GetInt32(kSettingsSection, key, &err);
            return err == vr::VRSettingsError_None ? v : def;
        };
        auto getf = [&](const char* key, float def) {
            err = vr::VRSettingsError_None;
            float v = s->GetFloat(kSettingsSection, key, &err);
            return err == vr::VRSettingsError_None ? v : def;
        };
        auto getb = [&](const char* key, bool def) {
            err = vr::VRSettingsError_None;
            bool v = s->GetBool(kSettingsSection, key, &err);
            return err == vr::VRSettingsError_None ? v : def;
        };

        udp_port_ = geti("udpPort", 49555);
        enable_controllers_ = getb("enableControllers", true);
        display_.window_x = geti("windowX", 50);
        display_.window_y = geti("windowY", 50);
        display_.window_width = geti("windowWidth", 1280);
        display_.window_height = geti("windowHeight", 720);
        display_.render_width = geti("renderWidth", 1080);
        display_.render_height = geti("renderHeight", 1200);
        display_.display_frequency = getf("displayFrequency", 60.f);
        display_.seconds_from_vsync_to_photons = getf("secondsFromVsyncToPhotons", 0.011f);
        display_.ipd = getf("ipd", 0.063f);

        if (display_.window_width < 320) display_.window_width = 320;
        if (display_.window_height < 240) display_.window_height = 240;
        if (display_.render_width < 256) display_.render_width = 256;
        if (display_.render_height < 256) display_.render_height = 256;
        if (display_.display_frequency < 30.f) display_.display_frequency = 30.f;
    }

    bool StartUdp() {
#ifdef _WIN32
        WSADATA wsa;
        if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
            Log("WSAStartup failed");
            return false;
        }
        wsa_started_ = true;
#endif
        sock_ = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (sock_ == kInvalidSocket) {
            Log("socket() failed");
            return false;
        }

        sockaddr_in addr;
        std::memset(&addr, 0, sizeof(addr));
        addr.sin_family = AF_INET;
        addr.sin_port = htons(static_cast<uint16_t>(udp_port_));
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);  // только локальный компьютер
        if (::bind(sock_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
            Log("bind() failed на порту " + std::to_string(udp_port_) + " (порт занят?)");
            CloseSocket(sock_);
            sock_ = kInvalidSocket;
            return false;
        }

        // Таймаут чтения 200 мс, чтобы поток мог корректно завершиться.
#ifdef _WIN32
        DWORD timeout_ms = 200;
        setsockopt(sock_, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&timeout_ms), sizeof(timeout_ms));
#else
        timeval tv;
        tv.tv_sec = 0;
        tv.tv_usec = 200 * 1000;
        setsockopt(sock_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
#endif

        udp_running_ = true;
        udp_thread_ = std::thread([this]() { UdpLoop(); });
        Log("UDP слушает 127.0.0.1:" + std::to_string(udp_port_));
        return true;
    }

    void StopUdp() {
        udp_running_ = false;
        if (udp_thread_.joinable()) udp_thread_.join();
        if (sock_ != kInvalidSocket) {
            CloseSocket(sock_);
            sock_ = kInvalidSocket;
        }
#ifdef _WIN32
        if (wsa_started_) {
            WSACleanup();
            wsa_started_ = false;
        }
#endif
    }

    void UdpLoop() {
        char buf[512];
        while (udp_running_) {
            int n = static_cast<int>(::recv(sock_, buf, sizeof(buf), 0));
            if (n != static_cast<int>(sizeof(Packet))) continue;  // таймаут или чужой пакет
            Packet p;
            std::memcpy(&p, buf, sizeof(p));
            if (Sanitize(p)) g_state.Set(p);
        }
    }

    void PoseLoop() {
        using namespace std::chrono;
        while (running_) {
            if (hmd_ && hmd_->ObjectId() != vr::k_unTrackedDeviceIndexInvalid) {
                vr::VRServerDriverHost()->TrackedDevicePoseUpdated(hmd_->ObjectId(), hmd_->GetPose(),
                                                                   sizeof(vr::DriverPose_t));
            }
            if (enable_controllers_) {
                if (left_ && left_->ObjectId() != vr::k_unTrackedDeviceIndexInvalid) {
                    vr::VRServerDriverHost()->TrackedDevicePoseUpdated(left_->ObjectId(), left_->GetPose(),
                                                                       sizeof(vr::DriverPose_t));
                }
                if (right_ && right_->ObjectId() != vr::k_unTrackedDeviceIndexInvalid) {
                    vr::VRServerDriverHost()->TrackedDevicePoseUpdated(right_->ObjectId(), right_->GetPose(),
                                                                       sizeof(vr::DriverPose_t));
                }
            }
            std::this_thread::sleep_for(milliseconds(4));
        }
    }

    // настройки
    int32_t udp_port_ = 49555;
    bool enable_controllers_ = true;
    DisplayConfig display_;

    // устройства (SteamVR вызывает Deactivate до Cleanup, удаляем сами)
    HmdDevice* hmd_ = nullptr;
    ControllerDevice* left_ = nullptr;
    ControllerDevice* right_ = nullptr;

    // потоки
    std::atomic<bool> running_{false};
    std::thread pose_thread_;
    std::atomic<bool> udp_running_{false};
    std::thread udp_thread_;
    socket_t sock_ = kInvalidSocket;
#ifdef _WIN32
    bool wsa_started_ = false;
#endif
};

VrHandProvider g_provider;

}  // namespace

VRHAND_EXPORT void* HmdDriverFactory(const char* interface_name, int* return_code) {
    if (std::strcmp(vr::IServerTrackedDeviceProvider_Version, interface_name) == 0) {
        return &g_provider;
    }
    if (return_code) *return_code = vr::VRInitError_Init_InterfaceNotFound;
    return nullptr;
}
