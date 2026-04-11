#!/usr/bin/env python3
"""
flasher.py - Automates flashing DuckLogger onto a MicroPython board.
Run from the root of the duckLogger directory.
"""

import subprocess
import sys
import os
import shutil
import gzip


def run(cmd, desc=""):
    print(f"  {desc or cmd}")
    r = subprocess.run(cmd, shell=True, text=True)
    if r.returncode != 0:
        print(f"\nFailed: {cmd}")
        sys.exit(1)


def require(tool):
    if shutil.which(tool) is None:
        print(f"'{tool}' not found. Please install it and try again.")
        sys.exit(1)


def compress(src, dst):
    with open(src, "rb") as f_in, gzip.open(dst, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def step(title):
    print(f"\n\033[32m-- {title}\033[0m")


def wait_for_board():
    """Try to run a no-op on the board to confirm real MicroPython connection."""
    while True:
        r = subprocess.run(
            "mpremote exec pass",
            shell=True, text=True, capture_output=True
        )
        if r.returncode == 0:
            print("  Board ready.")
            break
        print("  No board detected. Unplug and replug your board, then press Enter to retry...")
        input()


# Install mpremote
step("Install mpremote")
run(f"{sys.executable} -m pip install mpremote --quiet", "Installing mpremote")
require("mpremote")

# Detect board
step("Detect board")
wait_for_board()

# Install packages on board
step("Install MicroPython packages")
run("mpremote mip install usb-device",          "usb-device")
run("mpremote mip install usb-device-keyboard", "usb-device-keyboard")

# Compress index.html
step("Compress index.html")
compress("index.html", "index.html.gz")
print("  index.html -> index.html.gz")

# Copy files to board
step("Copy files to board")
run("mpremote cp -r lib/* :/lib/", "lib/* -> /lib/")
run("mpremote cp index.html.gz :",  "index.html.gz -> /")
run("mpremote cp settings.json :", "settings.json -> /")
run("mpremote cp main.py :",       "main.py -> /")

# Cleanup
step("Cleanup")
os.remove("index.html.gz")
print("  Removed index.html.gz")

# Reboot
step("Reboot board")
run("mpremote reset", "Resetting board")

print("\nDone.")
