# DuckLogger

<img width="2559" height="1060" alt="image" src="https://github.com/user-attachments/assets/d3178370-de53-4aaa-916b-64b3155cc503" />

DuckLogger is an ESP32-S3–based USB Key Logger. It logs keystrokes in a text file, and provides wireless access to download logs through a built-in Wi-Fi access point.
Recreating this project doesn't require any custom PCB. Hardware used here is less than $10 in total on places like Aliexpress.

<img width="2560" height="1440" alt="ducklogger" src="https://github.com/user-attachments/assets/f5aa82a2-3fc4-450a-a6cb-c52042ec13ce" />


## Features

1. Records keystrokes and saves them to a log file in internal flash storage
2. Automatically creates a Wi-Fi Access Point
3. Download log file from web UI at:

```
http://192.168.4.1/
```

Upcoming:

4. Send Ducky scripts from the web UI
5. Remote keyboard control via browser



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

DuckLogger is written in micropython, flash your board with micropython.
Find flashing instructions [here](https://micropython.org/download/ESP32_GENERIC_S3/)


After flashing, disconnect and reconnect the board via USB.


## 3. Install mpremote

On your development machine:

```bash
pip install mpremote
```

Verify that your board is detected:

```bash
mpremote connect list
```

## 4. Install Required MicroPython Packages

Install required packages directly onto the board:

```bash
mpremote mip install usb-device
mpremote mip install usb-device-keyboard
```


## 5. Install DuckLogger on the Board

Clone the repository:

```bash
git clone https://github.com/Itsmmdoha/duckLogger.git
cd duckLogger
```

Make sure your board is connected via USB.

### Copy all library files to `/lib` on the device

```bash
mpremote cp -r lib/* :/lib/
```

### Copy web c2 files to the root of the device

```bash
mpremote cp index.html :
```

### Copy main files to the root of the device

```bash
mpremote cp main.py :
```

Reboot the board:

```bash
mpremote reset
```


# Usage

1. Plug the USB keyboard into the CH9350 HID module.
2. Connect the ESP32-S3 SuperMini to the target PC using a USB-C to USB-A cable.
3. The device will automatically:

   * Start logging keystrokes
   * Create a Wi-Fi Access Point
   * Start an HTTP server

Connect to the Wi-Fi Access Point (Password: `duckPass1234`) and open:

```
http://192.168.4.1/
```

to download the log file.


# Repository Structure

```
├── lib
│   ├── access_point.py
│   ├── api.py
│   ├── keyboard.py
│   ├── key_led.py
│   ├── logger.py
│   ├── microdot.py
│   └── uart_buffer.py
├── main.py
├── README.md
└── resources.md
```

## Third-Party Libraries

This project includes Microdot by Miguel Grinberg (MIT License):  
https://github.com/miguelgrinberg/microdot
