from machine import Pin
import neopixel
import time


PIN_NUM = 48  
NUM_LEDS = 1

np = neopixel.NeoPixel(Pin(PIN_NUM), NUM_LEDS)

for _ in range(5):
    np[0] = (0, 255, 0)  # ON
    np.write()
    time.sleep(0.2)

    np[0] = (0, 0, 0)        # OFF
    np.write()
    time.sleep(0.2)

# main
from machine import UART
from uart_buffer import UARTBuffer
from key_led import KeyboardLED
from logger import Log
from keyboard import Keyboard
from settings import Settings
import asyncio

uart = UART(1, baudrate=115200, tx=Pin(2), rx=Pin(1) )

buffer = UARTBuffer(uart)
led = KeyboardLED(uart)
log = Log(20_000, led) # flush to file when there's 20,000 char in the buffer
kbd = Keyboard()

from api import DuckLoggerAPI
from mapper import HIDEncoder, mod_map
from duckyscript import DuckyScript
import wifi_radio
from mesh_network import MeshNetwork
from mesh_store import MeshStore

settings = Settings()
mesh = None
mesh_store = None
if settings.mesh_enabled and settings.role in ("node", "gateway"):
    mesh_store = MeshStore(settings.mesh_log_path)
    mesh = MeshNetwork(
        settings,
        on_data=mesh_store.append if settings.role == "gateway" else None,
    )
    mesh.start()

if settings.management_enabled and (
    settings.local_ui or settings.role == "standalone"
):
    wifi_radio.start(
        settings,
        channel=settings.mesh_channel if mesh is not None else None,
    )

encoder = HIDEncoder()

async def main():
    if mesh is not None:
        asyncio.create_task(mesh.run())
        if settings.role == "node":
            asyncio.create_task(mesh.run_synthetic_telemetry())

    api = DuckLoggerAPI(
        mesh=mesh,
        mesh_log_path=settings.mesh_log_path,
        hid_controls=(settings.role != "gateway"),
    )
    remote_keys = api.keys
    scripts = api.scripts
    script_execution = api.script_execution
    asyncio.create_task(api.start_server())
    last_activity = time.ticks_ms()

    while True:
        if time.ticks_diff(time.ticks_ms(), last_activity) >= 10_000:
            log._flush()
            last_activity = time.ticks_ms()

        if not scripts.is_empty():
            ducky_script = DuckyScript(scripts.dequeue(), kbd)
            try:
                await ducky_script.inject()
                script_execution.enqueue("Success")
            except ValueError as e:
                script_execution.enqueue(str(e))

        if not remote_keys.is_empty():
            key = remote_keys.dequeue()
            key_codes = encoder.key_parser(key)
            kbd.send_keys(key_codes) # press 
            await asyncio.sleep_ms(20)
            kbd.send_keys([]) # release
            continue

        if not uart.any():
            await asyncio.sleep(0)
            continue


        frame = await buffer.get_frame()

        led.update_led(frame)
        kbd.emulate(frame)

        modifiers = kbd.get_modifiers(frame)
        keys = kbd.get_keys(frame)
        log.add(modifiers, keys)

        last_activity = time.ticks_ms()


asyncio.run(main())
