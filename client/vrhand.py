"""vrhand — управление виртуальным VR-шлемом и руками с клавиатуры и мыши.

Запуск:  python vrhand.py
Нужен драйвер VRHand в SteamVR (см. README.md). Только стандартная библиотека Python 3.8+.

Как это работает: окно программы ловит мышь и клавиатуру, считает позы головы и рук
(vrhand_core.py) и 120 раз в секунду шлёт их драйверу по UDP на 127.0.0.1.
Roblox при этом должен быть запущен отдельно — окно программы нужно только для ввода.
"""

from __future__ import annotations

import argparse
import math
import sys
import threading
import time

from vrhand_core import (
    BTN_A,
    BTN_B,
    BTN_STICK_CLICK,
    LEFT,
    RIGHT,
    Config,
    Inputs,
    Sender,
    Simulator,
    FINGER_KEYS,
)

IS_WINDOWS = sys.platform == "win32"

# Имя клавиши -> виртуальный код Windows
VK_TABLE = {
    "shift": 0x10, "ctrl": 0x11, "space": 0x20,
    "pageup": 0x21, "pagedown": 0x22, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "comma": 0xBC, "period": 0xBE,
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK_TABLE[_c] = ord(_c.upper())

VK_MOUSE = {"left": 0x01, "right": 0x02, "middle": 0x04}

LEGEND = """\
МЫШЬ                 голова (взгляд)
Shift + мышь         правая рука (колесо: вперёд/назад)
Ctrl + мышь          левая рука
ЛКМ / ПКМ            триггер / грип (выбранной руки)
СКМ (колесо-клик)    нажатие стика
W A S D              левый стик (ходьба)
Q / E                правый стик (поворот)
Пробел / R           правая рука: A / B
T / Y                левая рука: X / Y
Стрелки, «,» «.»     повернуть руку / крен (выбранной)
Z X C V B            левая рука: мизинец ... большой
F G H J K            правая рука: большой ... мизинец
Home                 сбросить голову и руки
PgUp / PgDn          рост (высота головы)
Esc                  отпустить мышь"""


# ---------------------------------------------------------------------------
# Чтение ввода (Windows)
# ---------------------------------------------------------------------------
class WinInput:
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.user32 = ctypes.windll.user32
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short
        self.point = wintypes.POINT()

    def key_down(self, vk: int) -> bool:
        return bool(self.user32.GetAsyncKeyState(vk) & 0x8000)

    def pressed_keys(self) -> frozenset:
        return frozenset(name for name, vk in VK_TABLE.items() if self.key_down(vk))

    def pressed_mouse(self) -> frozenset:
        return frozenset(name for name, vk in VK_MOUSE.items() if self.key_down(vk))

    def cursor_delta_and_recenter(self, cx: int, cy: int):
        self.user32.GetCursorPos(self.ctypes.byref(self.point))
        dx = self.point.x - cx
        dy = self.point.y - cy
        if dx or dy:
            self.user32.SetCursorPos(cx, cy)
        return dx, dy


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------
class App:
    RATE_HZ = 120

    def __init__(self, args):
        import tkinter as tk

        self.tk = tk
        if IS_WINDOWS:
            try:  # чтобы координаты мыши совпадали с экранными пикселями
                import ctypes

                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass
            try:
                import ctypes

                ctypes.windll.winmm.timeBeginPeriod(1)
            except Exception:
                pass

        cfg = Config(
            mouse_sensitivity=args.sens,
            hand_sensitivity=args.hand_sens,
            invert_y=args.invert_y,
            head_height=args.height,
            hand_pitch_offset_deg=args.hand_pitch,
        )
        self.sim = Simulator(cfg)
        self.sender = Sender(args.host, args.port)
        self.win = WinInput()

        self.captured = False
        self.wait_release = False
        self.center = (0, 0)
        self.wheel = 0.0
        self.lock = threading.Lock()
        self.running = True
        self.last_packet_ok = True

        self._build_ui(args)

    # -- интерфейс -------------------------------------------------------------
    def _build_ui(self, args):
        tk = self.tk
        root = tk.Tk()
        self.root = root
        root.title("VRHand — управление")
        root.geometry("560x560+40+40")
        root.configure(bg="#14161a")
        if not args.no_topmost:
            root.attributes("-topmost", True)

        self.status = tk.Label(
            root, text="", font=("Segoe UI", 15, "bold"), bg="#14161a", fg="#ffffff", pady=10
        )
        self.status.pack(fill="x")

        self.info = tk.Label(
            root, text="", font=("Consolas", 10), bg="#14161a", fg="#9fb3c8", justify="left"
        )
        self.info.pack(fill="x", padx=12)

        legend = tk.Label(
            root, text=LEGEND, font=("Consolas", 10), bg="#14161a", fg="#d7dde4", justify="left", anchor="w"
        )
        legend.pack(fill="both", expand=True, padx=12, pady=(8, 6))

        self.foot = tk.Label(
            root,
            text=f"UDP -> {args.host}:{args.port}",
            font=("Consolas", 9),
            bg="#14161a",
            fg="#667085",
        )
        self.foot.pack(fill="x", pady=(0, 6))

        root.bind("<Button-1>", self._on_click)
        root.bind("<Escape>", lambda e: self.release())
        root.bind("<FocusOut>", lambda e: self.release())
        root.bind("<MouseWheel>", self._on_wheel)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self._refresh_ui()

    def _on_click(self, event):
        if not self.captured:
            self.capture()

    def _on_wheel(self, event):
        if self.captured:
            with self.lock:
                self.wheel += event.delta / 120.0

    def _update_center(self):
        r = self.root
        cx = r.winfo_rootx() + r.winfo_width() // 2
        cy = r.winfo_rooty() + r.winfo_height() // 2
        self.center = (cx, cy)

    def capture(self):
        self._update_center()
        self.captured = True
        self.wait_release = True  # не считать первый клик нажатием триггера
        self.root.config(cursor="none")
        self.root.focus_force()
        if IS_WINDOWS:
            self.win.user32.SetCursorPos(*self.center)

    def release(self):
        if self.captured:
            self.captured = False
            self.root.config(cursor="")

    def close(self):
        self.running = False
        self.release()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _refresh_ui(self):
        if not self.running:
            return
        if self.captured:
            self._update_center()
            self.status.config(text="УПРАВЛЕНИЕ ВКЛЮЧЕНО  (Esc — отпустить)", fg="#4ade80")
        else:
            self.status.config(text="Кликните в окно, чтобы начать", fg="#fbbf24")

        s = self.sim
        hands = "".join("L" if h == LEFT else "R" for h in s.moving_hands) or "-"
        fl = " ".join(f"{v:.1f}" for v in s.fingers[LEFT])
        fr = " ".join(f"{v:.1f}" for v in s.fingers[RIGHT])
        self.info.config(
            text=(
                f"голова: yaw {math.degrees(s.yaw):6.1f}°  pitch {math.degrees(s.pitch):5.1f}°  "
                f"рост {s.head_height:.2f} м\n"
                f"мышь двигает: {'голову' if hands == '-' else 'руку ' + hands}   "
                f"ходьба: ({s.stick[LEFT][0]:+.0f},{s.stick[LEFT][1]:+.0f})  "
                f"поворот: {s.stick[RIGHT][0]:+.0f}\n"
                f"триггер L/R {s.trigger[LEFT]:.1f}/{s.trigger[RIGHT]:.1f}   "
                f"грип L/R {s.grip[LEFT]:.1f}/{s.grip[RIGHT]:.1f}\n"
                f"пальцы L: {fl}\n"
                f"пальцы R: {fr}"
            )
        )
        self.root.after(80, self._refresh_ui)

    # -- рабочий поток: ввод -> симуляция -> UDP --------------------------------
    def read_inputs(self) -> Inputs:
        if not (self.captured and IS_WINDOWS):
            return Inputs()

        mouse = self.win.pressed_mouse()
        if self.wait_release:
            if not mouse:
                self.wait_release = False
            mouse = frozenset()

        dx, dy = self.win.cursor_delta_and_recenter(*self.center)
        with self.lock:
            wheel, self.wheel = self.wheel, 0.0
        return Inputs(keys=self.win.pressed_keys(), mouse_buttons=mouse, dx=dx, dy=dy, wheel=wheel)

    def worker(self):
        period = 1.0 / self.RATE_HZ
        last = time.perf_counter()
        while self.running:
            t0 = time.perf_counter()
            dt = t0 - last
            last = t0
            try:
                self.sim.update(dt, self.read_inputs())
                self.sender.send(self.sim.pack())
            except Exception as exc:  # поток не должен молча умирать
                print("ошибка в цикле ввода:", exc, file=sys.stderr)
                time.sleep(0.5)
            spare = period - (time.perf_counter() - t0)
            if spare > 0:
                time.sleep(spare)

    def run(self):
        thread = threading.Thread(target=self.worker, daemon=True)
        thread.start()
        try:
            self.root.mainloop()
        finally:
            self.running = False
            thread.join(timeout=1.0)
            self.sender.close()
            if IS_WINDOWS:
                try:
                    import ctypes

                    ctypes.windll.winmm.timeEndPeriod(1)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Демо без окна: голова и руки двигаются сами. Нужно, чтобы проверить драйвер.
# ---------------------------------------------------------------------------
def run_demo(args):
    cfg = Config(head_height=args.height, hand_pitch_offset_deg=args.hand_pitch)
    sim = Simulator(cfg)
    sender = Sender(args.host, args.port)
    print(f"Демо: шлём движение на {args.host}:{args.port}. Ctrl+C — выход.")
    print("В SteamVR шлем должен покачивать «головой» влево-вправо, а контроллеры — двигаться.")
    t_start = last = time.perf_counter()
    try:
        while True:
            now = time.perf_counter()
            dt, last = now - last, now
            t = now - t_start
            # скорость мыши в пикселях/кадр, чтобы голова качалась +-40 градусов
            dx = math.cos(t * 1.2) * 4.0 * dt * 60
            keys = set()
            if int(t) % 4 == 2:
                keys.add("g")  # согнуть указательный правой
            if int(t) % 6 == 4:
                keys.add("w")
            mouse = {"left"} if int(t) % 3 == 1 else set()
            sim.update(dt, Inputs(keys=frozenset(keys), mouse_buttons=frozenset(mouse), dx=dx))
            sender.send(sim.pack())
            time.sleep(1 / 120)
    except KeyboardInterrupt:
        print("Стоп.")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="VRHand: VR без шлема (клавиатура + мышь)")
    p.add_argument("--host", default="127.0.0.1", help="адрес драйвера (по умолчанию 127.0.0.1)")
    p.add_argument("--port", type=int, default=49555, help="UDP-порт драйвера (по умолчанию 49555)")
    p.add_argument("--sens", type=float, default=0.0025, help="чувствительность головы (рад/пиксель)")
    p.add_argument("--hand-sens", type=float, default=0.0015, help="чувствительность рук (м/пиксель)")
    p.add_argument("--invert-y", action="store_true", help="инвертировать вертикаль мыши")
    p.add_argument("--height", type=float, default=1.6, help="высота глаз в метрах")
    p.add_argument("--hand-pitch", type=float, default=0.0, help="наклон контроллеров в градусах")
    p.add_argument("--no-topmost", action="store_true", help="не держать окно поверх остальных")
    p.add_argument("--demo", action="store_true", help="без окна: сами двигаем голову/руки (проверка драйвера)")
    return p.parse_args(argv)


def main():
    args = parse_args()
    if args.demo:
        run_demo(args)
        return
    if not IS_WINDOWS:
        print("Окно управления работает только в Windows. Для проверки драйвера используйте --demo.")
        sys.exit(1)
    App(args).run()


if __name__ == "__main__":
    main()
