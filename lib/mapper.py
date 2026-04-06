# Keys that are identical in both normal and shift maps
from readline import read_init_file


common_map = {
    # Controls
    40: "ENTER",
    41: "ESC",
    42: "BKSP",
    43: "TAB",
    44: " ",
    # Locks / function
    57: "CAPS",
    58: "F1", 59: "F2", 60: "F3", 61: "F4",
    62: "F5", 63: "F6", 64: "F7", 65: "F8",
    66: "F9", 67: "F10", 68: "F11", 69: "F12",
    70: "PRTSC",
    71: "SCRLK",
    72: "PAUSE",
    # Navigation
    73: "INS",
    74: "HOME",
    75: "PGUP",
    76: "DEL",
    77: "END",
    78: "PGDN",
    # Arrows
    79: "RIGHT",
    80: "LEFT",
    81: "DOWN",
    82: "UP",
    # Numpad
    83: "NUMLK",
    84: "NUM/",
    85: "NUM*",
    86: "NUM-",
    87: "NUM+",
    88: "NUM_ENTER",
    89: "NUM1", 90: "NUM2", 91: "NUM3", 92: "NUM4", 93: "NUM5",
    94: "NUM6", 95: "NUM7", 96: "NUM8", 97: "NUM9", 98: "NUM0",
}

# Modifier keys
mod_map= {
    -0x01: "CTRL",
    -0x02: "SHIFT",
    -0x04: "ALT",
    -0x08: "WIN",
    -0x10: "CTRL",
    -0x20: "SHIFT",
    -0x40: "ALT",
    -0x80: "WIN",
}

# Keys unique to the normal (unshifted) map
base_map = {
    # Letters
    4: "a", 5: "b", 6: "c", 7: "d", 8: "e", 9: "f", 10: "g",
    11: "h", 12: "i", 13: "j", 14: "k", 15: "l", 16: "m",
    17: "n", 18: "o", 19: "p", 20: "q", 21: "r", 22: "s",
    23: "t", 24: "u", 25: "v", 26: "w", 27: "x", 28: "y", 29: "z",
    # Numbers (top row)
    30: "1", 31: "2", 32: "3", 33: "4", 34: "5",
    35: "6", 36: "7", 37: "8", 38: "9", 39: "0",
    # Symbols
    45: "-", 46: "=", 47: "[", 48: "]", 49: "\\",
    50: "#", 51: ";", 52: "'", 53: "`",
    54: ",", 55: ".", 56: "/",
}

# Keys unique to the shifted map
shift_map = {
    # Letters - uppercase
    4: "A", 5: "B", 6: "C", 7: "D", 8: "E", 9: "F", 10: "G",
    11: "H", 12: "I", 13: "J", 14: "K", 15: "L", 16: "M",
    17: "N", 18: "O", 19: "P", 20: "Q", 21: "R", 22: "S",
    23: "T", 24: "U", 25: "V", 26: "W", 27: "X", 28: "Y", 29: "Z",
    # Numbers (top row) - shifted symbols
    30: "!", 31: "@", 32: "#", 33: "$", 34: "%",
    35: "^", 36: "&", 37: "*", 38: "(", 39: ")",
    # Symbols - shifted
    45: "_", 46: "+", 47: "{", 48: "}", 49: "|",
    50: "~", 51: ":", 52: '"', 53: "~",
    54: "<", 55: ">", 56: "?",
}

def invert_map(map: dict) -> dict:
    inverted_map = {}
    for key, value in map.items():
        inverted_map[value] = key 
    return inverted_map

class HIDDecoder:
    """
    HID code to key names.
    """
    def __init__(self) -> None:
        self.common_map = common_map
        self.base_map = base_map
        self.shift_map = shift_map
        self.mod_map = mod_map
    def decode(self, code: int, shift: bool = False) -> str:
        """Returns Shifted Key Name if `shift` is True"""
        # only map from the shift map if shift is True
        if shift and code in self.shift_map:
            return self.shift_map[code]
        # else map from the rest
        elif code in self.base_map:
            return self.base_map[code]
        elif code in self.common_map:
            return self.common_map[code]
        elif code in self.mod_map:
            return self.mod_map[code]
        else:
            raise ValueError("Invalid Keycode")

class HIDEncoder:
    """
    Key Name to list of HID codes.
    Auto adds shift key to the list per requirement.
    """
    def __init__(self) -> None:
        self.common_map = invert_map(common_map)
        self.base_map = invert_map(base_map)
        self.shift_map = invert_map(shift_map)
        self.mod_map = invert_map(mod_map)
    def encode(self, key: str) -> list[int]:
        if key in self.base_map:
            return [self.base_map[key]] 
        elif key in self.shift_map:
            return [-0x02,self.shift_map[key]]
        elif key in self.mod_map:
            return [self.mod_map[key]]
        elif key in self.common_map:
            return [self.common_map[key]]
        else:
            raise ValueError("Invalid Key Name")



