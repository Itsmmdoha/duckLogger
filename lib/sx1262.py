"""Minimal SX1262 radio adapter for MicroPython (LoRa packet mode)."""

import time


class SX1262:
    SET_STANDBY = 0x80
    SET_RX = 0x82
    SET_TX = 0x83
    SET_PACKET_TYPE = 0x8A
    SET_RF_FREQUENCY = 0x86
    SET_PA_CONFIG = 0x95
    SET_TCXO = 0x97
    CALIBRATE_IMAGE = 0x98
    SET_TX_PARAMS = 0x8E
    SET_BUFFER_BASE = 0x8F
    SET_MOD_PARAMS = 0x8B
    SET_PACKET_PARAMS = 0x8C
    SET_DIO_IRQ = 0x08
    GET_IRQ = 0x12
    CLEAR_IRQ = 0x02
    GET_RX_STATUS = 0x13
    GET_PACKET_STATUS = 0x14
    WRITE_BUFFER = 0x0E
    READ_BUFFER = 0x1E
    IRQ_TX_DONE = 0x0001
    IRQ_RX_DONE = 0x0002
    IRQ_TIMEOUT = 0x0200

    def __init__(self, spi, cs, reset, busy, dio1, rf_switch=None,
                 frequency=868000000,
                 spreading_factor=7, bandwidth=125000, coding_rate=5,
                 tx_power=14):
        self.spi, self.cs, self.reset, self.busy, self.dio1 = spi, cs, reset, busy, dio1
        self.rf_switch = rf_switch
        self.frequency = frequency
        self.sf, self.bandwidth, self.cr, self.tx_power = spreading_factor, bandwidth, coding_rate, tx_power
        self.rx_packets = self.tx_packets = self.errors = 0
        self.last_rssi = self.last_snr = None

    def _sleep_us(self, value):
        try: time.sleep_us(value)
        except AttributeError: time.sleep(value / 1000000)

    def _wait_busy(self):
        started = time.time()
        while self.busy.value():
            if time.time() - started > 1:
                raise OSError("SX1262 busy timeout")
            self._sleep_us(100)

    def _command(self, opcode, data=b"", read=0):
        self._wait_busy(); self.cs.value(0)
        try:
            self.spi.write(bytes((opcode,)) + data)
            result = self.spi.read(read, 0) if read else b""
        finally:
            self.cs.value(1)
        self._wait_busy()
        return result

    def begin(self):
        self.cs.value(1)
        if self.rf_switch is not None:
            self.rf_switch.value(1)  # RX path on the Seeed Wio-SX1262 B2B board.
        self.reset.value(0); self._sleep_us(200); self.reset.value(1)
        self._sleep_us(10000)
        self._command(self.SET_STANDBY, b"\x00")
        # The Wio-SX1262 module uses a 1.8 V TCXO connected to DIO3. The
        # 24-bit timeout is in 15.625 us units (320 = 5 ms).
        self._command(self.SET_TCXO, b"\x02\x00\x01\x40")
        if 863000000 <= self.frequency <= 870000000:
            self._command(self.CALIBRATE_IMAGE, b"\xd7\xdb")
        elif 902000000 <= self.frequency <= 928000000:
            self._command(self.CALIBRATE_IMAGE, b"\xe1\xe9")
        self._command(self.SET_PACKET_TYPE, b"\x01")
        step = int(self.frequency * (1 << 25) / 32000000)
        self._command(self.SET_RF_FREQUENCY, step.to_bytes(4, "big"))
        bw_codes = {125000: 0x04, 250000: 0x05, 500000: 0x06}
        self._command(self.SET_MOD_PARAMS, bytes((self.sf, bw_codes[self.bandwidth], self.cr - 4, 0)))
        self._command(self.SET_PACKET_PARAMS, b"\x00\x08\x00\xff\x01\x00")
        self._command(self.SET_BUFFER_BASE, b"\x00\x00")
        self._command(self.SET_PA_CONFIG, b"\x04\x07\x00\x01")
        self._command(self.SET_TX_PARAMS, bytes((self.tx_power & 0xff, 0x04)))
        self._command(self.SET_DIO_IRQ, b"\x03\xff\x03\xff\x00\x00\x00\x00")
        self.start_receive()

    def start_receive(self):
        if self.rf_switch is not None:
            self.rf_switch.value(1)
        self._command(self.CLEAR_IRQ, b"\xff\xff")
        self._command(self.SET_RX, b"\xff\xff\xff")

    def send(self, payload):
        if len(payload) > 255: raise ValueError("SX1262 payload exceeds 255 bytes")
        self._command(self.SET_STANDBY, b"\x00")
        self._command(self.WRITE_BUFFER, b"\x00" + payload)
        self._command(self.SET_PACKET_PARAMS, b"\x00\x08\x00" + bytes((len(payload),)) + b"\x01\x00")
        self._command(self.CLEAR_IRQ, b"\xff\xff")
        if self.rf_switch is not None:
            self.rf_switch.value(0)  # TX path on the Seeed Wio-SX1262 B2B board.
        self._command(self.SET_TX, b"\x00\x00\x00")
        started = time.time()
        while not self.dio1.value():
            if time.time() - started > 10: self.errors += 1; raise OSError("SX1262 TX timeout")
            self._sleep_us(1000)
        self.tx_packets += 1; self.start_receive()

    def recv(self):
        if not self.dio1.value(): return None
        irq = self._command(self.GET_IRQ, b"\x00", 2)
        flags = int.from_bytes(irq, "big") if irq else 0
        self._command(self.CLEAR_IRQ, b"\xff\xff")
        if not flags & self.IRQ_RX_DONE: self.start_receive(); return None
        status = self._command(self.GET_RX_STATUS, b"\x00", 2)
        length, offset = status[0], status[1]
        packet = self._command(self.READ_BUFFER, bytes((offset, 0)), length)
        quality = self._command(self.GET_PACKET_STATUS, b"\x00", 3)
        if quality:
            self.last_rssi = -quality[0] / 2
            snr = quality[1] if quality[1] < 128 else quality[1] - 256
            self.last_snr = snr / 4
        self.rx_packets += 1; self.start_receive()
        return packet

    def status(self):
        return {"frequency": self.frequency, "rx_packets": self.rx_packets,
                "tx_packets": self.tx_packets, "errors": self.errors,
                "rssi": self.last_rssi, "snr": self.last_snr}


def from_settings(settings):
    """Create and initialize the configured hardware radio lazily."""
    from machine import SPI, Pin
    spi = SPI(settings.lora_spi_id, baudrate=8000000, polarity=0, phase=0,
              sck=Pin(settings.lora_sck_pin), mosi=Pin(settings.lora_mosi_pin),
              miso=Pin(settings.lora_miso_pin))
    radio = SX1262(spi, Pin(settings.lora_cs_pin, Pin.OUT),
                   Pin(settings.lora_reset_pin, Pin.OUT),
                   Pin(settings.lora_busy_pin, Pin.IN),
                   Pin(settings.lora_dio1_pin, Pin.IN),
                   Pin(settings.lora_rf_switch_pin, Pin.OUT),
                   settings.lora_frequency, settings.lora_spreading_factor,
                   settings.lora_bandwidth, settings.lora_coding_rate,
                   settings.lora_tx_power)
    radio.begin()
    return radio
