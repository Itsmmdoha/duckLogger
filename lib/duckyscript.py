from mapper import HIDEncoder
import asyncio

encoder = HIDEncoder()

def get_command_value(line: str):
    return line.split(" ", 1)[1]


class DuckyScript:
    def __init__(self, script: str, kbd) -> None:
        self.script = script
        self.kbd = kbd
    async def send_string(self, string, line_idx: int):
        for char in string:
            try:
                key_codes = encoder.encode(key=char)
            except ValueError:
                raise ValueError(f"Invalid Syntax on line:{line_idx+ 1}")
            self.kbd.send_keys(key_codes) # press
            await asyncio.sleep_ms(20)
            self.kbd.send_keys([])  # release

    async def delay(self, milisecods: int):
        await asyncio.sleep_ms(milisecods)

    async def execute_line(self, line: str, line_idx: int):
        line = line.strip()
        if not line:
            return
        if line.startswith("DELAY"):
            delay_time_str = get_command_value(line)
            try:
                delay_time = int(delay_time_str)
                await asyncio.sleep_ms(delay_time)
            except ValueError:
                raise ValueError(f"Invalid Syntax on line:{line_idx+ 1}: {line}")

        elif line.startswith("STRING"):
            string = get_command_value(line)
            await self.send_string(string, line_idx=line_idx)

        else: # Independent key / combo detected
            try:
                key_codes = encoder.key_parser(line)
            except ValueError:
                raise ValueError(f"Invalid Syntax on line:{line_idx+ 1}: {line}")
            self.kbd.send_keys(key_codes)
            await asyncio.sleep_ms(20)
            self.kbd.send_keys()
    async def inject(self):
        for idx, line in enumerate(self.script.strip().splitlines()):
            await self.execute_line(line, idx)

