// Формат UDP-пакета между Python-клиентом (client/vrhand_core.py) и драйвером.
// Все числа little-endian. Размер пакета ровно 172 байта.
//
// ВАЖНО: если меняете этот файл, меняйте и PACKET_FORMAT в client/vrhand_core.py.
#pragma once

#include <cstdint>

namespace vrhand {

// Байты 'V','R','H','1' подряд -> uint32 little-endian.
constexpr uint32_t kMagic = 0x31485256u;

// Биты в Packet::buttons[hand]
enum ButtonBits : uint32_t {
    kBtnStickClick = 1u << 0,
    kBtnA = 1u << 1,  // у левой руки это X
    kBtnB = 1u << 2,  // у левой руки это Y
    kBtnSystem = 1u << 3,
};

#pragma pack(push, 1)
struct Packet {
    uint32_t magic;       // kMagic
    uint32_t seq;         // счётчик пакетов (для отладки)
    float head[7];        // x y z qx qy qz qw (метры, система координат OpenVR)
    float hand[2][7];     // [0] = левая, [1] = правая; x y z qx qy qz qw
    float trigger[2];     // 0..1
    float grip[2];        // 0..1
    float stick[2][2];    // [рука][x,y], -1..1
    uint32_t buttons[2];  // ButtonBits
    float fingers[2][5];  // изгиб пальцев 0..1: большой, указательный, средний, безымянный, мизинец
};
#pragma pack(pop)

static_assert(sizeof(Packet) == 172, "Packet layout must be 172 bytes (see client/vrhand_core.py)");

}  // namespace vrhand
