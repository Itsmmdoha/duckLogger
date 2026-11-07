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
import argparse
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from settings import Settings


def run(cmd, desc=""):
    print(f"  {desc or ' '.join(cmd)}")
    r = subprocess.run(cmd, text=True)
    if r.returncode != 0:
        print(f"\nFailed: {cmd}")
        sys.exit(1)


def require(tool):
    if shutil.which(tool) is None:
        print(f"'{tool}' not found. Please install it and try again.")
        sys.exit(1)


def mpremote(*command):
    prefix = ["mpremote"]
    if args.port:
        prefix.extend(("connect", args.port))
    prefix.extend(command)
    return prefix


def compress(src, dst):
    with open(src, "rb") as f_in, gzip.open(dst, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def step(title):
    print(f"\n\033[32m-- {title}\033[0m")


def copy_runtime_library():
    directories = sorted(
        path for path in Path("lib").rglob("*")
        if path.is_dir() and path.name != "__pycache__"
        and "__pycache__" not in path.parts
    )
    remote_directories = ["/lib"] + ["/" + path.as_posix() for path in directories]
    setup = "import os\n"
    for directory in remote_directories:
        setup += "\ntry: os.mkdir(%r)\nexcept OSError: pass\n" % directory
    run(mpremote("exec", setup), "create runtime directories")
    sources = sorted(
        path for path in Path("lib").rglob("*.py")
        if "__pycache__" not in path.parts
    )
    for source in sources:
        remote = ":/" + source.as_posix()
        run(mpremote("cp", str(source), remote), str(source) + " -> /" + source.as_posix())


def wait_for_board():
    """Try to run a no-op on the board to confirm real MicroPython connection."""
    while True:
        r = subprocess.run(
            mpremote("exec", "pass"),
            text=True, capture_output=True
        )
        if r.returncode == 0:
            print("  Board ready.")
            break
        print("  No board detected. Unplug and replug your board, then press Enter to retry...")
        input()


parser = argparse.ArgumentParser(description="Flash DuckLogger/MeshOps to a MicroPython board")
parser.add_argument(
    "--settings",
    default="settings.json",
    help="settings JSON to install on this board (default: settings.json)",
)
parser.add_argument(
    "--port",
    default="",
    help="exact serial port to flash, for example /dev/ttyACM0",
)
args = parser.parse_args()
settings_path = os.path.abspath(args.settings)
try:
    board = Settings(settings_path)
except ValueError as exc:
    parser.error(str(exc))

mesh_only = board.mesh_only
needs_ui = (not mesh_only) or (
    board.role == "gateway" and board.management_enabled
) or board.role == "lora_sink"


# Reuse an installed mpremote. Avoid invoking pip on externally managed Python
# environments when the required command is already available.
step("Check mpremote")
require("mpremote")

# Detect board
step("Detect board")
wait_for_board()

# Install packages and web assets only for the original HID/UI firmware.
if not mesh_only and board.role != "lora_sink":
    step("Install MicroPython packages")
    run(mpremote("mip", "install", "usb-device"), "usb-device")
    run(mpremote("mip", "install", "usb-device-keyboard"), "usb-device-keyboard")

if board.egress_enabled and "wifi" in board.egress_backends:
    step("Install egress package")
    run(mpremote("mip", "install", "urequests"), "urequests")

if needs_ui:
    step("Compress index.html")
    ui_source = "receiver.html" if board.role == "lora_sink" else "index.html"
    ui_target = "receiver.html.gz" if board.role == "lora_sink" else "index.html.gz"
    compress(ui_source, ui_target)
    print(f"  {ui_source} -> {ui_target}")

# Copy files to board
step("Copy files to board")
copy_runtime_library()
if needs_ui:
    run(mpremote("cp", ui_target, ":"), f"{ui_target} -> /")
run(mpremote("cp", settings_path, ":settings.json"),
    "%s -> /settings.json" % args.settings)
run(mpremote("cp", "main.py", ":"), "main.py -> /")

# Cleanup
step("Cleanup")
if needs_ui:
    os.remove(ui_target)
    print(f"  Removed {ui_target}")

# Reboot
step("Reboot board")
run(mpremote("reset"), "Resetting board")

print("\nDone.")
