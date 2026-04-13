# DuckLogger

<img width="2559" height="1060" alt="image" src="https://github.com/user-attachments/assets/d3178370-de53-4aaa-916b-64b3155cc503" />

DuckLogger is an ESP32-S3–based USB Key Logger. It logs keystrokes in a text file, and provides wireless access to download logs through a built-in Wi-Fi access point.
Recreating this project doesn't require any custom PCB. Hardware used here is less than $10 in total on places like Aliexpress.

<img width="2560" height="1440" alt="ducklogger" src="https://github.com/user-attachments/assets/f5aa82a2-3fc4-450a-a6cb-c52042ec13ce" />


## Features

* **Keystroke Logging**: Records keystrokes and saves them to a log file in the internal flash storage.
* **Dual Wi-Fi Modes**: Supports both Wi-Fi Station mode (connect to an existing network) and Access Point (Hotspot) mode.
* **Web Command & Control Center**: Access a built-in web interface to manage your device. The control center allows you to:
  * **Download Logs**: Easily download the saved keystroke log file.
  * **Remote Live Keyboard**: Attach a live virtual keyboard and send keystrokes via WebSocket in real-time with almost no latency.
  * **DuckyScript Injection**: Inject and execute DuckyScript payloads remotely.
  * **Device Settings**: Update configurations for AP/Station mode directly from the web UI.

Access the web UI at:
```
http://192.168.4.1/
```
*(When in Access Point mode)*

<img width="1920" height="1080" alt="ducklogger_screenshot" src="https://github.com/user-attachments/assets/1397c342-2860-4b81-96e6-4d2d7c6e1da4" />

## Components Used

* ESP32-S3 SuperMini
* CH9350 HID Module
* 4 Female Jumper Wires

---

# Getting Started

## 1. Schematics

<img width="2851" height="810" alt="image" src="https://github.com/user-attachments/assets/42f63b02-d19f-4c31-832d-3051c3bb02d1" />


| ESP32-S3 | CH9350 |
| -------- | ------ |
| 5V       | 5V     |
| GND      | GND    |
| GP1      | TX     |
| GP2      | RX     |

The CH9350 supports multiple operating modes, which are configured using the onboard DIP switches.

<img width="819" height="627" alt="image" src="https://github.com/user-attachments/assets/d8060d39-abb1-4d92-9ce8-8e2043ad1c0b" />

Set `S0` to the GND position (0) and keep all other switches in the opposite position (1). This enables USB Host Mode, which converts USB keyboard inputs into serial data sent via UART at a default baud rate of 115200.

## 2. Flash MicroPython

DuckLogger is written in MicroPython. Flash your board with MicroPython firmware.
Find flashing instructions [here](https://micropython.org/download/ESP32_GENERIC_S3/).

After flashing, disconnect and reconnect the board via USB.

## 3. Clone the Repository

```bash
git clone https://github.com/Itsmmdoha/duckLogger.git
cd duckLogger
```

## 4. Install DuckLogger on the Board

Make sure your board is connected via USB, then run:

```bash
python flasher.py
```

The flasher will automatically:

* Install `mpremote` and required MicroPython packages on the board
* Compress `index.html` and copy all files to the board
* Reboot the board

---

# Usage

1. Plug the USB keyboard into the CH9350 HID module.
2. Connect the ESP32-S3 SuperMini to the target PC using a USB-C to USB-A cable.
3. The device will automatically:

   * Start logging keystrokes
   * Connect to Wi-Fi or create a Wi-Fi Access Point depending on your settings
   * Start an HTTP server

If in Access Point mode(Default), connect to the Wi-Fi Access Point (Default Password: `duckPass1234`) and open:

```
http://192.168.4.1/
```

To access the command and control center.


## Supported DuckyScript Syntax

DuckLogger currently supports a core set of DuckyScript commands for payload injection:

| Command | Description | Example |
| :--- | :--- | :--- |
| `DELAY` | Pauses execution for a specified number of milliseconds. | `DELAY 500` |
| `STRING` | Types out a sequence of characters exactly as written. | `STRING Hello, World!` |
| **Key Combos** | Sends simultaneous keystrokes. | `CTRL SHIFT ESC` or `ALT i` |
| **Single Keys** | Sends individual special keys. | `ENTER` or `TAB` |


# Repository Structure

```
.
├── flasher.py
├── index.html
├── lib
│   ├── access_point.py
│   ├── api.py
│   ├── duckyscript.py
│   ├── keyboard.py
│   ├── key_led.py
│   ├── logger.py
│   ├── mapper.py
│   ├── microdot
│   │   ├── helpers.py
│   │   ├── __init__.py
│   │   ├── microdot.py
│   │   └── websocket.py
│   ├── queue.py
│   ├── settings.py
│   ├── uart_buffer.py
│   ├── wifi.py
│   └── wifi_radio.py
├── LICENSE
├── main.py
├── README.md
├── resources.md
└── settings.json
```

## Third-Party Libraries

This project includes Microdot by Miguel Grinberg (MIT License):  
https://github.com/miguelgrinberg/microdot

---
