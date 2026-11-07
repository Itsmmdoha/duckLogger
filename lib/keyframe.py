class KeyFrame:
    def get_modifiers(self, frame) -> list:
        mod_byte = frame[3]
        mods_keys = []

        # Modifier bits mapping:
        # Bit: 0=LCtrl, 1=LShift, 2=LAlt, 3=LWin, 4=RCtrl, 5=RShift, 6=RAlt, 7=RWin
        if mod_byte & 0x01: mods_keys.append(-0x01)  # LEFT_CTRL
        if mod_byte & 0x10: mods_keys.append(-0x10)  # RIGHT_CTRL
        if mod_byte & 0x02: mods_keys.append(-0x02)  # LEFT_SHIFT
        if mod_byte & 0x20: mods_keys.append(-0x20)  # RIGHT_SHIFT
        if mod_byte & 0x04: mods_keys.append(-0x04)  # LEFT_ALT
        if mod_byte & 0x40: mods_keys.append(-0x40)  # RIGHT_ALT
        if mod_byte & 0x08: mods_keys.append(-0x08)  # LEFT_UI
        if mod_byte & 0x80: mods_keys.append(-0x80)  # RIGHT_UI

        return mods_keys

    def get_keys(self, frame) -> list:
        return [k for k in frame[5:11] if k != 0x00]

    def get_all_keys(self, frame) -> list:
        all_keys = self.get_modifiers(frame)
        all_keys.extend(self.get_keys(frame))
        return all_keys
