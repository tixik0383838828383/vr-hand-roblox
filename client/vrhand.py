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
    "lbracket": 0xDB, "rbracket": 0xDD,
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK_TABLE[_c] = ord(_c.upper())

VK_MOUSE = {"left": 0x01, "right": 0x02, "middle": 0x04}

LEGEND = """\
F8                   ВКЛ/ВЫКЛ управление (из любого окна)
МЫШЬ                 голова (взгляд)
Shift + мышь         правая рука (колесо: вперёд/назад)
Ctrl + мышь          левая рука
ЛКМ / ПКМ            триггер / грип (правой руки; с Ctrl — левой)
КОЛЕСО               прокрутка меню (правый стик вверх/вниз)
СКМ (колесо-клик)    нажатие стика
W A S D              левый стик (ходьба)
Q / E                правый стик (поворот)
[ / ]                прокрутка вниз / вверх
Пробел / R           правая рука: A / B
T / Y                левая рука: X / Y (Y — меню Roblox)
Стрелки, «,» «.»     повернуть руку / крен (выбранной)
Z X C V B            левая рука: мизинец ... большой
F G H J K            правая рука: большой ... мизинец
Home                 сбросить голову и руки
PgUp / PgDn          рост (высота головы)"""


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
# Глобальный перехват (Windows): работает в любом окне и не пропускает клавиши в игру
# ---------------------------------------------------------------------------
class HookInput:
    """Низкоуровневые хуки клавиатуры и мыши.

    Пока управление включено (F8), нажатия клавиш, кнопок мыши и колесо забираются себе
    и НЕ доходят до Roblox/Studio — иначе WASD ходили бы ещё и по рабочему столу.
    Движение мыши не блокируется: курсор каждый кадр возвращается в центр экрана.
    Если хук поставить не удалось, ok = False и приложение работает по-старому.
    """

    WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
    WM_LBUTTONDOWN, WM_LBUTTONUP = 0x201, 0x202
    WM_RBUTTONDOWN, WM_RBUTTONUP = 0x204, 0x205
    WM_MBUTTONDOWN, WM_MBUTTONUP = 0x207, 0x208
    WM_MOUSEWHEEL = 0x20A
    VK_TOGGLE = 0x77  # F8

    # Эти клавиши никогда не забираем (Win, Alt — чтобы можно было переключить окно)
    PASS_VK = {0x5B, 0x5C, 0xA4, 0xA5, 0x12}

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ok = False
        self.active = False
        self.lock = threading.Lock()
        self.down = set()          # нажатые сейчас имена клавиш (наши)
        self.swallowed_keys = set()   # vk, чьё нажатие мы забрали (их отпускание тоже забираем)
        self.mouse_down = set()
        self.swallowed_mouse = set()
        self.wheel = 0.0
        self._thread_id = 0
        self._hooks = []
        self._ready = threading.Event()
        self._ct = ctypes
        self._wt = wintypes

        self.vk_to_name = {vk: name for name, vk in VK_TABLE.items()}
        self.vk_to_name.update({0xA0: "shift", 0xA1: "shift", 0xA2: "ctrl", 0xA3: "ctrl"})

        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        self._ready.wait(3.0)

    # -- управление состоянием ---------------------------------------------------
    def set_active(self, value: bool):
        with self.lock:
            self.active = bool(value)
            if not self.active:
                self.down.clear()
                self.mouse_down.clear()
                self.wheel = 0.0

    def toggle(self):
        self.set_active(not self.active)

    def snapshot(self):
        with self.lock:
            wheel, self.wheel = self.wheel, 0.0
            return frozenset(self.down), frozenset(self.mouse_down), wheel

    # -- поток с хуками ------------------------------------------------------------
    def _run(self):
        ct, wt = self._ct, self._wt
        try:
            user32 = ct.WinDLL("user32", use_last_error=True)
            kernel32 = ct.WinDLL("kernel32", use_last_error=True)
            LRESULT = ct.c_ssize_t
            HOOKPROC = ct.WINFUNCTYPE(LRESULT, ct.c_int, wt.WPARAM, wt.LPARAM)

            class KBDLLHOOKSTRUCT(ct.Structure):
                _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                            ("time", wt.DWORD), ("dwExtraInfo", ct.c_size_t)]

            class MSLLHOOKSTRUCT(ct.Structure):
                _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                            ("time", wt.DWORD), ("dwExtraInfo", ct.c_size_t)]

            user32.SetWindowsHookExW.argtypes = [ct.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
            user32.SetWindowsHookExW.restype = ct.c_void_p
            user32.CallNextHookEx.argtypes = [ct.c_void_p, ct.c_int, wt.WPARAM, wt.LPARAM]
            user32.CallNextHookEx.restype = LRESULT
            user32.UnhookWindowsHookEx.argtypes = [ct.c_void_p]
            user32.GetMessageW.argtypes = [ct.POINTER(wt.MSG), wt.HWND, ct.c_uint, ct.c_uint]
            kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wt.HMODULE
            self._thread_id = kernel32.GetCurrentThreadId()

            def next_hook(code, wparam, lparam):
                return user32.CallNextHookEx(None, code, wparam, lparam)

            def kb_proc(code, wparam, lparam):
                try:
                    if code < 0:
                        return next_hook(code, wparam, lparam)
                    info = ct.cast(lparam, ct.POINTER(KBDLLHOOKSTRUCT)).contents
                    if info.flags & 0x10:  # события, созданные программно (в т.ч. нами) не трогаем
                        return next_hook(code, wparam, lparam)
                    vk = info.vkCode
                    is_down = wparam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN)

                    if vk == self.VK_TOGGLE:
                        if is_down and vk not in self.swallowed_keys:
                            self.toggle()
                        if is_down:
                            self.swallowed_keys.add(vk)
                        else:
                            self.swallowed_keys.discard(vk)
                        return 1
                    if not is_down:
                        if vk in self.swallowed_keys:
                            self.swallowed_keys.discard(vk)
                            with self.lock:
                                self.down.discard(self.vk_to_name.get(vk, ""))
                            return 1
                        return next_hook(code, wparam, lparam)
                    if not self.active or vk in self.PASS_VK:
                        return next_hook(code, wparam, lparam)
                    self.swallowed_keys.add(vk)
                    name = self.vk_to_name.get(vk)
                    if name:
                        with self.lock:
                            self.down.add(name)
                    return 1
                except Exception:
                    return next_hook(code, wparam, lparam)

            btn_map = {
                self.WM_LBUTTONDOWN: ("left", True), self.WM_LBUTTONUP: ("left", False),
                self.WM_RBUTTONDOWN: ("right", True), self.WM_RBUTTONUP: ("right", False),
                self.WM_MBUTTONDOWN: ("middle", True), self.WM_MBUTTONUP: ("middle", False),
            }

            def ms_proc(code, wparam, lparam):
                try:
                    if code < 0:
                        return next_hook(code, wparam, lparam)
                    info = ct.cast(lparam, ct.POINTER(MSLLHOOKSTRUCT)).contents
                    if info.flags & 0x1:  # программно созданное событие
                        return next_hook(code, wparam, lparam)
                    if wparam in btn_map:
                        name, is_down = btn_map[wparam]
                        if is_down:
                            if not self.active:
                                return next_hook(code, wparam, lparam)
                            self.swallowed_mouse.add(name)
                            with self.lock:
                                self.mouse_down.add(name)
                            return 1
                        if name in self.swallowed_mouse:
                            self.swallowed_mouse.discard(name)
                            with self.lock:
                                self.mouse_down.discard(name)
                            return 1
                        return next_hook(code, wparam, lparam)
                    if wparam == self.WM_MOUSEWHEEL and self.active:
                        delta = ct.c_short((info.mouseData >> 16) & 0xFFFF).value
                        with self.lock:
                            self.wheel += delta / 120.0
                        return 1
                    return next_hook(code, wparam, lparam)
                except Exception:
                    return next_hook(code, wparam, lparam)

            # ссылки на колбэки нужно держать, иначе их соберёт сборщик мусора
            self._kb_cb = HOOKPROC(kb_proc)
            self._ms_cb = HOOKPROC(ms_proc)
            hinst = kernel32.GetModuleHandleW(None)
            kb = user32.SetWindowsHookExW(13, self._kb_cb, hinst, 0)
            ms = user32.SetWindowsHookExW(14, self._ms_cb, hinst, 0)
            self._hooks = [h for h in (kb, ms) if h]
            self.ok = bool(kb and ms)
            self._ready.set()
            if not self._hooks:
                return

            msg = wt.MSG()
            while user32.GetMessageW(ct.byref(msg), None, 0, 0) > 0:
                pass
            for h in self._hooks:
                user32.UnhookWindowsHookEx(h)
        except Exception as exc:
            print("не удалось поставить хуки ввода:", exc, file=sys.stderr)
        finally:
            self._ready.set()

    def close(self):
        self.set_active(False)
        if self._thread_id:
            try:
                self._ct.windll.user32.PostThreadMessageW(self._thread_id, 0x12, 0, 0)  # WM_QUIT
            except Exception:
                pass

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
        self.hooks = None
        self._was_active = False
        if IS_WINDOWS:
            try:
                hooks = HookInput()
                if hooks.ok:
                    self.hooks = hooks
                else:
                    print("Глобальный перехват недоступен — работаю в режиме «окно в фокусе».", file=sys.stderr)
            except Exception as exc:
                print("Глобальный перехват не запустился:", exc, file=sys.stderr)
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
        if not self.hooks:
            root.bind("<Escape>", lambda e: self.release())
            root.bind("<FocusOut>", lambda e: self.release())
        root.bind("<MouseWheel>", self._on_wheel)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self._refresh_ui()

    def is_active(self) -> bool:
        return self.hooks.active if self.hooks else self.captured

    def _on_click(self, event):
        if not self.is_active():
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

    def _screen_center(self):
        u = self.win.user32
        return (u.GetSystemMetrics(0) // 2, u.GetSystemMetrics(1) // 2)

    def capture(self):
        if self.hooks:
            self.center = self._screen_center()
            self.hooks.set_active(True)
            return
        self._update_center()
        self.captured = True
        self.wait_release = True  # не считать первый клик нажатием триггера
        self.root.config(cursor="none")
        self.root.focus_force()
        if IS_WINDOWS:
            self.win.user32.SetCursorPos(*self.center)

    def release(self):
        if self.hooks:
            self.hooks.set_active(False)
            return
        if self.captured:
            self.captured = False
            self.root.config(cursor="")

    def close(self):
        self.running = False
        self.release()
        if self.hooks:
            self.hooks.close()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _refresh_ui(self):
        if not self.running:
            return
        if self.hooks:
            if self.hooks.active:
                self.status.config(text="УПРАВЛЕНИЕ ВКЛЮЧЕНО  (F8 — выключить)", fg="#4ade80")
            else:
                self.status.config(text="ВЫКЛЮЧЕНО — нажмите F8 (в любом окне)", fg="#fbbf24")
        elif self.captured:
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
        if self.hooks:
            return self._read_inputs_hooked()
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

    def _read_inputs_hooked(self) -> Inputs:
        active = self.hooks.active
        if not active:
            self._was_active = False
            return Inputs()
        if not self._was_active:
            # только что включили: ставим курсор в центр и не считаем скачок за движение мыши
            self._was_active = True
            self.center = self._screen_center()
            self.win.user32.SetCursorPos(*self.center)
            self.hooks.snapshot()
            return Inputs()
        keys, mouse, wheel = self.hooks.snapshot()
        dx, dy = self.win.cursor_delta_and_recenter(*self.center)
        return Inputs(keys=keys, mouse_buttons=mouse, dx=dx, dy=dy, wheel=wheel)

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
