import usb.device
from usb.device.keyboard import KeyboardInterface

from keyframe import KeyFrame


class Keyboard(KeyFrame):
    def __init__(self) -> None:
        self.kbd = KeyboardInterface()
        usb.device.get().init(self.kbd)

    def send_keys(self, keys):
        # keys is a iterable with byte(8 bit int, hex or binary) elements
        self.kbd.send_keys(keys)

    def emulate(self, frame):
        keys = self.get_all_keys(frame)
        self.send_keys(keys)
