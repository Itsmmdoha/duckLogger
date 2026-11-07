import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib"))

from logger import Log


class FakeLock:
    def __init__(self, caps_lock=False):
        self.caps_lock = caps_lock


def test_letter_press_is_not_duplicated():
    log = Log(100, FakeLock())
    assert log.add([], [4]) == "a"


def test_shifted_letter():
    log = Log(100, FakeLock())
    assert log.add([-0x02], [4]) == "A"


def test_caps_lock_letter():
    log = Log(100, FakeLock(caps_lock=True))
    assert log.add([], [4]) == "A"


def test_shortcut_press():
    log = Log(100, FakeLock())
    assert log.add([-0x01], [6]) == "[CTRL+c]"


def test_repeated_key_is_not_logged_twice():
    log = Log(100, FakeLock())
    assert log.add([], [4]) == "a"
    assert log.add([], [4]) == ""


def test_release_then_press_is_logged_again():
    log = Log(100, FakeLock())
    assert log.add([], [4]) == "a"
    assert log.add([], []) == ""
    assert log.add([], [4]) == "a"
