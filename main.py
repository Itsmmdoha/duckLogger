from settings import Settings

settings = Settings()

if settings.mesh_only:
    # Safe bench mode: the mesh node emits synthetic telemetry only. Do not
    # import or initialize the UART, CH9350, USB HID, or local key logger.
    import asyncio
    from mesh_network import MeshNetwork

    if settings.role != "node" or not settings.mesh_enabled:
        raise ValueError("mesh_only requires an enabled node role")

    mesh = MeshNetwork(settings)
    mesh.start()

    async def run_mesh_node():
        asyncio.create_task(mesh.run())
        asyncio.create_task(mesh.run_synthetic_telemetry())
        while True:
            await asyncio.sleep_ms(1000)

    asyncio.run(run_mesh_node())
else:
    from machine import Pin, UART
    import neopixel
    import time
    import asyncio

    PIN_NUM = 48
    NUM_LEDS = 1
    np = neopixel.NeoPixel(Pin(PIN_NUM), NUM_LEDS)

    for _ in range(5):
        np[0] = (0, 255, 0)
        np.write()
        time.sleep(0.2)
        np[0] = (0, 0, 0)
        np.write()
        time.sleep(0.2)

    from uart_buffer import UARTBuffer
    from key_led import KeyboardLED
    from logger import Log
    from keyboard import Keyboard
    from api import DuckLoggerAPI
    from mapper import HIDEncoder
    from duckyscript import DuckyScript
    import wifi_radio
    from mesh_network import MeshNetwork
    from mesh_store import MeshStore

    uart = UART(1, baudrate=115200, tx=Pin(2), rx=Pin(1))
    buffer = UARTBuffer(uart)
    led = KeyboardLED(uart)
    log = Log(20_000, led)
    kbd = Keyboard()

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
                except ValueError as exc:
                    script_execution.enqueue(str(exc))

            if not remote_keys.is_empty():
                key = remote_keys.dequeue()
                key_codes = encoder.key_parser(key)
                kbd.send_keys(key_codes)
                await asyncio.sleep_ms(20)
                kbd.send_keys([])
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
