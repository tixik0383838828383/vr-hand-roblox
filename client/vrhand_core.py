"""vrhand_core — логика эмуляции VR-шлема и рук по клавиатуре и мыши.

Здесь нет окон и нет Windows-специфики, поэтому модуль можно тестировать где угодно.
Окно и чтение клавиш/мыши — в vrhand.py.

Система координат — как в OpenVR/SteamVR: правая, Y вверх, «вперёд» = -Z, метры.
Кватернионы хранятся как (x, y, z, w).
"""

from __future__ import annotations

import math
import socket
import struct
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Формат пакета (должен совпадать с driver/src/protocol.h, ровно 172 байта)
# ---------------------------------------------------------------------------
MAGIC = 0x31485256  # байты 'V','R','H','1'
PACKET_FORMAT = (
    "<II"      # magic, seq
    "7f"       # голова: x y z qx qy qz qw
    "7f7f"     # левая рука, правая рука
    "2f"       # trigger L, R
    "2f"       # grip L, R
    "4f"       # stick: Lx Ly Rx Ry
    "2I"       # buttons L, R
    "10f"      # пальцы: левая (5), правая (5)
)
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)
assert PACKET_SIZE == 172, PACKET_SIZE

BTN_STICK_CLICK = 1 << 0
BTN_A = 1 << 1  # у левой руки — X
BTN_B = 1 << 2  # у левой руки — Y
BTN_SYSTEM = 1 << 3

LEFT, RIGHT = 0, 1
FINGER_NAMES = ("большой", "указательный", "средний", "безымянный", "мизинец")

# ---------------------------------------------------------------------------
# Раскладка клавиш (имена как их выдаёт vrhand.py). Меняйте под себя.
# ---------------------------------------------------------------------------
# Пальцы по порядку: большой, указательный, средний, безымянный, мизинец
FINGER_KEYS = {
    LEFT: ("b", "v", "c", "x", "z"),    # ZXCVB — левая рука
    RIGHT: ("f", "g", "h", "j", "k"),   # FGHJK — правая рука
}

KEY_MOVE_FORWARD = "w"
KEY_MOVE_BACK = "s"
KEY_MOVE_LEFT = "a"
KEY_MOVE_RIGHT = "d"
KEY_TURN_LEFT = "q"
KEY_TURN_RIGHT = "e"

KEY_RIGHT_A = "space"   # прыжок в Roblox
KEY_RIGHT_B = "r"
KEY_LEFT_A = "t"        # X
KEY_LEFT_B = "y"        # Y

KEY_MODIFIER_RIGHT_HAND = "shift"
KEY_MODIFIER_LEFT_HAND = "ctrl"

KEY_AIM_LEFT = "left"
KEY_AIM_RIGHT = "right"
KEY_AIM_UP = "up"
KEY_AIM_DOWN = "down"
KEY_ROLL_LEFT = "comma"
KEY_ROLL_RIGHT = "period"

KEY_SCROLL_UP = "rbracket"    # ] — прокрутка вверх (правый стик вверх)
KEY_SCROLL_DOWN = "lbracket"  # [ — прокрутка вниз

KEY_RESET = "home"
KEY_HEIGHT_UP = "pageup"
KEY_HEIGHT_DOWN = "pagedown"


@dataclass
class Config:
    head_height: float = 1.6          # высота глаз, м
    mouse_sensitivity: float = 0.0025  # радиан на пиксель (поворот головы)
    hand_sensitivity: float = 0.0015   # метров на пиксель (движение руки)
    wheel_step: float = 0.05           # метров на щелчок колеса (рука вперёд/назад)
    invert_y: bool = False
    aim_speed: float = 1.4             # рад/с, повороты руки стрелками
    finger_speed: float = 9.0          # скорость сгибания пальца (единиц/с)
    trigger_speed: float = 14.0
    scroll_per_click: float = 0.7      # на сколько колесо отклоняет правый стик (прокрутка меню)
    scroll_decay: float = 4.0          # как быстро стик возвращается в центр, ед./с
    converge_distance: float = 2.0     # м: на таком расстоянии лучи рук сходятся в центре взгляда (0 = выкл.)
    hand_follows_gaze_pitch: bool = True  # луч руки следует за наклоном головы
    hand_pitch_offset_deg: float = 0.0    # поправка наклона контроллера
    # Начальные положения рук относительно головы (x вправо, y вверх, z вперёд = минус)
    default_offsets: dict = field(
        default_factory=lambda: {LEFT: (-0.22, -0.35, -0.35), RIGHT: (0.22, -0.35, -0.35)}
    )


@dataclass
class Inputs:
    """Что нажато прямо сейчас."""

    keys: frozenset = frozenset()          # имена клавиш в нижнем регистре
    mouse_buttons: frozenset = frozenset()  # {'left', 'right', 'middle'}
    dx: float = 0.0                        # сдвиг мыши с прошлого кадра, пиксели
    dy: float = 0.0
    wheel: float = 0.0                     # щелчки колеса, + = от себя


# ---------------------------------------------------------------------------
# Кватернионы
# ---------------------------------------------------------------------------
def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def q_axis(axis: str, angle: float):
    s, c = math.sin(angle / 2), math.cos(angle / 2)
    if axis == "x":
        return (s, 0.0, 0.0, c)
    if axis == "y":
        return (0.0, s, 0.0, c)
    return (0.0, 0.0, s, c)


def q_rotate(q, v):
    """Поворачивает вектор v кватернионом q."""
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v)
    tx = 2 * (y * vz - z * vy)
    ty = 2 * (z * vx - x * vz)
    tz = 2 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def approach(value, target, rate, dt):
    """Плавно двигает value к target со скоростью rate (единиц/с)."""
    step = rate * dt
    if value < target:
        return min(value + step, target)
    return max(value - step, target)


# ---------------------------------------------------------------------------
# Симулятор
# ---------------------------------------------------------------------------
class Simulator:
    def __init__(self, config: Config | None = None):
        self.cfg = config or Config()
        self.seq = 0
        self.head_height = self.cfg.head_height
        self._prev_keys = frozenset()
        self.reset()

    # -- сброс ---------------------------------------------------------------
    def reset(self):
        self.yaw = 0.0
        self.pitch = 0.0
        self.offset = {h: list(self.cfg.default_offsets[h]) for h in (LEFT, RIGHT)}
        self.aim = {h: [0.0, 0.0, 0.0] for h in (LEFT, RIGHT)}  # yaw, pitch, roll
        self.scroll = 0.0
        d = self.cfg.converge_distance
        if d > 0:
            # Лучи рук слегка «косят» к центру взгляда: курсор меню оказывается там, куда смотрит голова.
            for h in (LEFT, RIGHT):
                ox, oy, _ = self.offset[h]
                self.aim[h][0] = math.atan2(ox, d)
                self.aim[h][1] = math.atan2(-oy, d)
        self.trigger = [0.0, 0.0]
        self.grip = [0.0, 0.0]
        self.fingers = [[0.0] * 5, [0.0] * 5]
        self.stick = [[0.0, 0.0], [0.0, 0.0]]
        self.buttons = [0, 0]
        self.active_hands: tuple = (RIGHT,)
        self.moving_hands: tuple = ()

    # -- основной шаг ------------------------------------------------------------
    def update(self, dt: float, inp: Inputs):
        cfg = self.cfg
        keys = inp.keys
        dt = clamp(dt, 0.0, 0.1)

        # Какие руки сейчас «выбраны»
        shift = KEY_MODIFIER_RIGHT_HAND in keys
        ctrl = KEY_MODIFIER_LEFT_HAND in keys
        moving = []
        if ctrl:
            moving.append(LEFT)
        if shift:
            moving.append(RIGHT)
        self.moving_hands = tuple(moving)
        self.active_hands = tuple(moving) if moving else (RIGHT,)

        # Сброс по нажатию (не по удержанию)
        if KEY_RESET in keys and KEY_RESET not in self._prev_keys:
            self.reset()
        self._prev_keys = keys

        # Мышь: либо голова, либо руки
        dy = -inp.dy if cfg.invert_y else inp.dy
        if moving:
            for h in moving:
                o = self.offset[h]
                o[0] = clamp(o[0] + inp.dx * cfg.hand_sensitivity, -0.8, 0.8)
                o[1] = clamp(o[1] - dy * cfg.hand_sensitivity, -0.9, 0.5)
                o[2] = clamp(o[2] - inp.wheel * cfg.wheel_step, -0.9, 0.2)
        else:
            self.yaw -= inp.dx * cfg.mouse_sensitivity
            self.pitch = clamp(self.pitch - dy * cfg.mouse_sensitivity, math.radians(-89), math.radians(89))
            # Колесо без модификаторов — прокрутка (правый стик вверх/вниз), как на контроллере
            if inp.wheel:
                self.scroll = clamp(self.scroll + inp.wheel * cfg.scroll_per_click, -1.0, 1.0)
        self.scroll = approach(self.scroll, 0.0, cfg.scroll_decay, dt)
        self.yaw = (self.yaw + math.pi) % (2 * math.pi) - math.pi

        # Повороты руки стрелками и , .
        d_yaw = (KEY_AIM_LEFT in keys) - (KEY_AIM_RIGHT in keys)
        d_pitch = (KEY_AIM_UP in keys) - (KEY_AIM_DOWN in keys)
        d_roll = (KEY_ROLL_LEFT in keys) - (KEY_ROLL_RIGHT in keys)
        for h in self.active_hands:
            a = self.aim[h]
            a[0] = clamp(a[0] + d_yaw * cfg.aim_speed * dt, -1.5, 1.5)
            a[1] = clamp(a[1] + d_pitch * cfg.aim_speed * dt, -1.5, 1.5)
            a[2] = clamp(a[2] + d_roll * cfg.aim_speed * dt, -3.14, 3.14)

        # Высота головы
        self.head_height = clamp(
            self.head_height + ((KEY_HEIGHT_UP in keys) - (KEY_HEIGHT_DOWN in keys)) * 0.5 * dt, 0.5, 2.2
        )

        # Стики: левый — WASD, правый — Q/E (поворот)
        lx = (KEY_MOVE_RIGHT in keys) - (KEY_MOVE_LEFT in keys)
        ly = (KEY_MOVE_FORWARD in keys) - (KEY_MOVE_BACK in keys)
        length = math.hypot(lx, ly)
        if length > 1.0:
            lx, ly = lx / length, ly / length
        rx = (KEY_TURN_RIGHT in keys) - (KEY_TURN_LEFT in keys)
        ry = (KEY_SCROLL_UP in keys) - (KEY_SCROLL_DOWN in keys)
        ry = clamp(ry + self.scroll, -1.0, 1.0)
        self.stick = [[float(lx), float(ly)], [float(rx), float(ry)]]

        # Кнопки
        buttons = [0, 0]
        if KEY_LEFT_A in keys:
            buttons[LEFT] |= BTN_A
        if KEY_LEFT_B in keys:
            buttons[LEFT] |= BTN_B
        if KEY_RIGHT_A in keys:
            buttons[RIGHT] |= BTN_A
        if KEY_RIGHT_B in keys:
            buttons[RIGHT] |= BTN_B
        if "middle" in inp.mouse_buttons:
            for h in self.active_hands:
                buttons[h] |= BTN_STICK_CLICK
        self.buttons = buttons

        # Триггер и грип с мыши (ЛКМ / ПКМ) — для выбранных рук
        trig_target = [0.0, 0.0]
        grip_target = [0.0, 0.0]
        for h in self.active_hands:
            if "left" in inp.mouse_buttons:
                trig_target[h] = 1.0
            if "right" in inp.mouse_buttons:
                grip_target[h] = 1.0
        for h in (LEFT, RIGHT):
            self.trigger[h] = approach(self.trigger[h], trig_target[h], cfg.trigger_speed, dt)
            self.grip[h] = approach(self.grip[h], grip_target[h], cfg.trigger_speed, dt)

        # Пальцы: клавиши + то, что сгибается вместе с триггером/грипом/кнопками
        for h in (LEFT, RIGHT):
            keys_h = FINGER_KEYS[h]
            for i in range(5):
                target = 1.0 if keys_h[i] in keys else 0.0
                if i == 1:
                    target = max(target, self.trigger[h])
                elif i >= 2:
                    target = max(target, self.grip[h])
                elif i == 0 and buttons[h]:
                    target = max(target, 0.5)
                rate = cfg.finger_speed
                self.fingers[h][i] = approach(self.fingers[h][i], target, rate, dt)

    # -- позы ----------------------------------------------------------------
    def head_pose(self):
        q = q_mul(q_axis("y", self.yaw), q_axis("x", self.pitch))
        return (0.0, self.head_height, 0.0) + q

    def hand_pose(self, h: int):
        yaw_q = q_axis("y", self.yaw)
        ox, oy, oz = self.offset[h]
        rx, ry, rz = q_rotate(yaw_q, (ox, oy, oz))
        pos = (rx, self.head_height + ry, rz)

        aim_yaw, aim_pitch, aim_roll = self.aim[h]
        pitch = aim_pitch + math.radians(self.cfg.hand_pitch_offset_deg)
        if self.cfg.hand_follows_gaze_pitch:
            pitch += self.pitch
        q = yaw_q
        q = q_mul(q, q_axis("y", aim_yaw))
        q = q_mul(q, q_axis("x", pitch))
        q = q_mul(q, q_axis("z", aim_roll))
        return pos + q

    # -- пакет ---------------------------------------------------------------
    def pack(self) -> bytes:
        self.seq = (self.seq + 1) & 0xFFFFFFFF
        return pack_packet(
            self.seq,
            self.head_pose(),
            self.hand_pose(LEFT),
            self.hand_pose(RIGHT),
            self.trigger,
            self.grip,
            self.stick,
            self.buttons,
            self.fingers,
        )


def pack_packet(seq, head, hand_l, hand_r, trigger, grip, stick, buttons, fingers) -> bytes:
    return struct.pack(
        PACKET_FORMAT,
        MAGIC,
        seq,
        *head,
        *hand_l,
        *hand_r,
        trigger[LEFT], trigger[RIGHT],
        grip[LEFT], grip[RIGHT],
        stick[LEFT][0], stick[LEFT][1], stick[RIGHT][0], stick[RIGHT][1],
        buttons[LEFT], buttons[RIGHT],
        *fingers[LEFT], *fingers[RIGHT],
    )


def unpack_packet(data: bytes) -> dict:
    """Обратная операция — нужна для тестов."""
    v = struct.unpack(PACKET_FORMAT, data)
    return {
        "magic": v[0],
        "seq": v[1],
        "head": list(v[2:9]),
        "hand": [list(v[9:16]), list(v[16:23])],
        "trigger": list(v[23:25]),
        "grip": list(v[25:27]),
        "stick": [list(v[27:29]), list(v[29:31])],
        "buttons": list(v[31:33]),
        "fingers": [list(v[33:38]), list(v[38:43])],
    }


class Sender:
    """Шлёт пакеты драйверу по UDP на localhost."""

    def __init__(self, host: str = "127.0.0.1", port: int = 49555):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.errors = 0

    def send(self, data: bytes) -> bool:
        try:
            self.sock.sendto(data, self.addr)
            return True
        except OSError:
            self.errors += 1
            return False

    def close(self):
        self.sock.close()
