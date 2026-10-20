"""Проверки без SteamVR:  python -m unittest discover -s tests  (из корня репозитория)

* логика симулятора (мышь -> голова/руки, клавиши -> стики/кнопки/пальцы);
* формат пакета совпадает с C++ (если в системе есть g++ или clang++).
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "client"))

import vrhand_core as core  # noqa: E402
from vrhand_core import Inputs, Simulator, LEFT, RIGHT  # noqa: E402


def step(sim, inp, seconds=0.5, rate=120):
    for _ in range(int(seconds * rate)):
        sim.update(1.0 / rate, inp)


def norm(q):
    return math.sqrt(sum(c * c for c in q))


class SimulatorTests(unittest.TestCase):
    def test_packet_size(self):
        self.assertEqual(core.PACKET_SIZE, 172)
        self.assertEqual(len(Simulator().pack()), 172)

    def test_mouse_right_turns_head_right(self):
        sim = Simulator()
        sim.update(0.01, Inputs(dx=100))
        self.assertLess(sim.yaw, 0)  # вправо = минус yaw в OpenVR
        # вперёд (-Z) после поворота вправо должен смотреть в сторону +X
        fx, _, fz = core.q_rotate(sim.head_pose()[3:], (0, 0, -1))
        self.assertGreater(fx, 0)

    def test_mouse_down_looks_down(self):
        sim = Simulator()
        sim.update(0.01, Inputs(dy=100))
        self.assertLess(sim.pitch, 0)
        _, fy, _ = core.q_rotate(sim.head_pose()[3:], (0, 0, -1))
        self.assertLess(fy, 0)

    def test_pitch_clamped(self):
        sim = Simulator()
        for _ in range(100):
            sim.update(0.01, Inputs(dy=-10000))
        self.assertLessEqual(sim.pitch, math.radians(89.0001))

    def test_shift_moves_right_hand_not_head(self):
        sim = Simulator()
        before = sim.hand_pose(RIGHT)
        sim.update(0.01, Inputs(keys=frozenset({"shift"}), dx=100))
        self.assertEqual(sim.yaw, 0.0)
        self.assertGreater(sim.hand_pose(RIGHT)[0], before[0])
        self.assertEqual(sim.hand_pose(LEFT)[:3], Simulator().hand_pose(LEFT)[:3])

    def test_ctrl_moves_left_hand(self):
        sim = Simulator()
        before = sim.hand_pose(LEFT)
        sim.update(0.01, Inputs(keys=frozenset({"ctrl"}), dy=-100))  # мышь вверх
        self.assertGreater(sim.hand_pose(LEFT)[1], before[1])

    def test_hands_follow_head_yaw(self):
        sim = Simulator()
        sim.update(0.01, Inputs(dx=-int(math.radians(90) / sim.cfg.mouse_sensitivity)))  # поворот влево на 90°
        x, _, z = sim.hand_pose(RIGHT)[:3]
        # правая рука была справа-спереди (+x, -z); после поворота налево на 90° она спереди-справа от нового взгляда
        self.assertAlmostEqual(math.hypot(x, z), math.hypot(0.22, 0.35), places=3)
        self.assertLess(x, 0.0)  # взгляд теперь на -X, значит «вперёд» руки это -X

    def test_wasd_left_stick(self):
        sim = Simulator()
        sim.update(0.01, Inputs(keys=frozenset({"w", "d"})))
        x, y = sim.stick[LEFT]
        self.assertAlmostEqual(math.hypot(x, y), 1.0, places=5)  # диагональ не быстрее
        self.assertGreater(x, 0)
        self.assertGreater(y, 0)

    def test_qe_right_stick(self):
        sim = Simulator()
        sim.update(0.01, Inputs(keys=frozenset({"q"})))
        self.assertEqual(sim.stick[RIGHT][0], -1.0)
        sim.update(0.01, Inputs(keys=frozenset({"e"})))
        self.assertEqual(sim.stick[RIGHT][0], 1.0)

    def test_face_buttons(self):
        sim = Simulator()
        sim.update(0.01, Inputs(keys=frozenset({"space", "r", "t", "y"})))
        self.assertEqual(sim.buttons[RIGHT], core.BTN_A | core.BTN_B)
        self.assertEqual(sim.buttons[LEFT], core.BTN_A | core.BTN_B)

    def test_lmb_trigger_follows_selected_hand(self):
        sim = Simulator()
        step(sim, Inputs(mouse_buttons=frozenset({"left"})))
        self.assertGreater(sim.trigger[RIGHT], 0.99)
        self.assertEqual(sim.trigger[LEFT], 0.0)
        sim2 = Simulator()
        step(sim2, Inputs(keys=frozenset({"ctrl"}), mouse_buttons=frozenset({"left"})))
        self.assertGreater(sim2.trigger[LEFT], 0.99)
        self.assertEqual(sim2.trigger[RIGHT], 0.0)

    def test_rmb_grip_curls_three_fingers(self):
        sim = Simulator()
        step(sim, Inputs(mouse_buttons=frozenset({"right"})))
        f = sim.fingers[RIGHT]
        self.assertGreater(sim.grip[RIGHT], 0.99)
        self.assertTrue(all(v > 0.99 for v in f[2:]))
        self.assertLess(f[1], 0.01)

    def test_finger_keys(self):
        for hand, keys in core.FINGER_KEYS.items():
            for i, k in enumerate(keys):
                sim = Simulator()
                step(sim, Inputs(keys=frozenset({k})), seconds=0.4)
                self.assertGreater(sim.fingers[hand][i], 0.99, (hand, k))
                others = [v for h in (LEFT, RIGHT) for j, v in enumerate(sim.fingers[h]) if (h, j) != (hand, i)]
                self.assertTrue(all(v < 0.01 for v in others), (hand, k, others))
                # отпустили — палец плавно разгибается
                step(sim, Inputs(), seconds=0.4)
                self.assertLess(sim.fingers[hand][i], 0.01)

    def test_finger_keys_are_unique(self):
        used = [k for keys in core.FINGER_KEYS.values() for k in keys]
        self.assertEqual(len(used), len(set(used)))
        others = {
            core.KEY_MOVE_FORWARD, core.KEY_MOVE_BACK, core.KEY_MOVE_LEFT, core.KEY_MOVE_RIGHT,
            core.KEY_TURN_LEFT, core.KEY_TURN_RIGHT, core.KEY_RIGHT_A, core.KEY_RIGHT_B,
            core.KEY_LEFT_A, core.KEY_LEFT_B, core.KEY_RESET,
        }
        self.assertFalse(set(used) & others, set(used) & others)

    def test_reset(self):
        sim = Simulator()
        sim.update(0.01, Inputs(dx=500, dy=300))
        sim.update(0.01, Inputs(keys=frozenset({"home"})))
        self.assertEqual((sim.yaw, sim.pitch), (0.0, 0.0))

    def test_quaternions_normalized(self):
        sim = Simulator()
        sim.update(0.01, Inputs(dx=321, dy=-123, keys=frozenset({"left", "up", "comma"})))
        for pose in (sim.head_pose(), sim.hand_pose(LEFT), sim.hand_pose(RIGHT)):
            self.assertAlmostEqual(norm(pose[3:]), 1.0, places=5)

    def test_pack_roundtrip(self):
        sim = Simulator()
        sim.update(0.01, Inputs(keys=frozenset({"w", "space"}), dx=40))
        d = core.unpack_packet(sim.pack())
        self.assertEqual(d["magic"], core.MAGIC)
        self.assertEqual(d["seq"], 1)
        self.assertEqual(d["buttons"][RIGHT], core.BTN_A)
        self.assertAlmostEqual(d["stick"][LEFT][1], 1.0)


@unittest.skipIf(sys.platform == "win32", "тест читает бинарный stdin, на Windows пропускаем")
@unittest.skipUnless(shutil.which("g++") or shutil.which("clang++"), "нет компилятора C++")
class CppProtocolTests(unittest.TestCase):
    def test_python_and_cpp_agree(self):
        cxx = shutil.which("g++") or shutil.which("clang++")
        with tempfile.TemporaryDirectory() as tmp:
            exe = os.path.join(tmp, "protocol_check")
            src = os.path.join(ROOT, "tests", "protocol_check.cpp")
            subprocess.run([cxx, "-std=c++17", src, "-o", exe], check=True)

            # значения, различные в каждом поле
            head = (0.1, 1.6, -0.2, 0.0, 0.5, 0.0, math.sqrt(0.75))
            hl = (-0.2, 1.2, -0.3, 0.1, 0.2, 0.3, math.sqrt(1 - 0.14))
            hr = (0.3, 1.1, -0.4, 0.0, 0.0, 0.0, 1.0)
            data = core.pack_packet(
                77, head, hl, hr, (0.25, 0.75), (0.5, 1.0), ((0.1, -0.2), (0.3, -0.4)),
                (core.BTN_A | core.BTN_STICK_CLICK, core.BTN_B), ((0.1, 0.2, 0.3, 0.4, 0.5), (0.6, 0.7, 0.8, 0.9, 1.0)),
            )
            out = subprocess.run([exe], input=data, capture_output=True, check=True).stdout.decode().splitlines()
            got = {line.split()[0]: [float(x) for x in line.split()[1:]] for line in out}

            self.assertEqual(int(got["sizeof"][0]), 172)
            self.assertEqual(int(got["magic"][0]), core.MAGIC)
            self.assertEqual(int(got["seq"][0]), 77)
            for name, expect in (
                ("head", head), ("hand0", hl), ("hand1", hr),
                ("trigger", (0.25, 0.75)), ("grip", (0.5, 1.0)),
                ("stick", (0.1, -0.2, 0.3, -0.4)),
                ("fingers0", (0.1, 0.2, 0.3, 0.4, 0.5)), ("fingers1", (0.6, 0.7, 0.8, 0.9, 1.0)),
            ):
                for a, b in zip(got[name], expect):
                    self.assertAlmostEqual(a, b, places=5, msg=name)
            self.assertEqual([int(x) for x in got["buttons"]], [core.BTN_A | core.BTN_STICK_CLICK, core.BTN_B])


if __name__ == "__main__":
    unittest.main()
