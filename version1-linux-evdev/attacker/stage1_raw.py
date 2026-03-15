#!/usr/bin/env python3
"""
STAGE 1 — Raw Keycode Viewer
============================
What this does:
  - Opens your keyboard device directly at the kernel level
  - Reads raw input_event structs (type, code, value)
  - Prints every keypress with timestamp LIVE

This is what the kernel sees before Wayland/X11 touches it.
Run this in Terminal 2 (the "hacker view") while you type in Terminal 1.

Usage:
  sudo python3 stage1_raw.py
"""

import evdev
import sys
from datetime import datetime

# ── Config ──────────────────────────────────────────
KEYBOARD_DEVICE = "/dev/input/event3"   # AT Translated Set 2 keyboard
# If you use the wireless keyboard, also try /dev/input/event6
# ────────────────────────────────────────────────────

RED     = "\033[91m"
YELLOW  = "\033[93m"
GREEN   = "\033[92m"
CYAN    = "\033[96m"
MAGENTA = "\033[95m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RESET   = "\033[0m"

BANNER = f"""
{RED}{BOLD}
██╗  ██╗ █████╗  ██████╗██╗  ██╗███████╗██████╗     ██╗   ██╗██╗███████╗██╗    ██╗
██║  ██║██╔══██╗██╔════╝██║ ██╔╝██╔════╝██╔══██╗    ██║   ██║██║██╔════╝██║    ██║
███████║███████║██║     █████╔╝ █████╗  ██████╔╝    ██║   ██║██║█████╗  ██║ █╗ ██║
██╔══██║██╔══██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗    ╚██╗ ██╔╝██║██╔══╝  ██║███╗██║
██║  ██║██║  ██║╚██████╗██║  ██╗███████╗██║  ██║     ╚████╔╝ ██║███████╗╚███╔███╔╝
╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝      ╚═══╝  ╚═╝╚══════╝ ╚══╝╚══╝
{RESET}
{DIM}  STAGE 1 — Raw Kernel Input Feed | Device: {KEYBOARD_DEVICE}{RESET}
{DIM}  Every keypress your kernel sees — before Wayland touches it{RESET}
{RED}  ──────────────────────────────────────────────────────────{RESET}
  {YELLOW}EVENT TYPE LEGEND:{RESET}
  {GREEN}▶ value=1{RESET}  KEY PRESS      ← key went down
  {CYAN}▶ value=0{RESET}  KEY RELEASE    ← key came up
  {MAGENTA}▶ value=2{RESET}  KEY REPEAT     ← held down, auto-repeat
{RED}  ──────────────────────────────────────────────────────────{RESET}
  Listening on {BOLD}{KEYBOARD_DEVICE}{RESET} ... {DIM}(Ctrl+C to stop){RESET}
"""

def main():
    print(BANNER)

    try:
        device = evdev.InputDevice(KEYBOARD_DEVICE)
    except PermissionError:
        print(f"{RED}[ERROR]{RESET} Permission denied — run with: {BOLD}sudo python3 stage1_raw.py{RESET}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"{RED}[ERROR]{RESET} Device {KEYBOARD_DEVICE} not found.")
        sys.exit(1)

    print(f"{DIM}  Device: {device.name}{RESET}")
    print(f"{DIM}  Phys:   {device.phys}{RESET}\n")

    event_count = 0

    try:
        for event in device.read_loop():
            # We only care about key events (type == EV_KEY == 1)
            if event.type != evdev.ecodes.EV_KEY:
                continue

            key = evdev.categorize(event)
            ts  = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            event_count += 1

            # value: 1=press, 0=release, 2=repeat
            if event.value == 1:
                action = f"{GREEN}PRESS  {RESET}"
                arrow  = f"{GREEN}▶{RESET}"
            elif event.value == 0:
                action = f"{CYAN}RELEASE{RESET}"
                arrow  = f"{CYAN}▷{RESET}"
            else:
                action = f"{MAGENTA}REPEAT {RESET}"
                arrow  = f"{MAGENTA}↻{RESET}"

            keyname = key.keycode if isinstance(key.keycode, str) else str(key.keycode)

            print(
                f"  {DIM}[{ts}]{RESET}  "
                f"{arrow} {action}  "
                f"{BOLD}{YELLOW}{keyname:<20}{RESET}  "
                f"{DIM}code={event.code:<4} value={event.value}{RESET}"
            )

    except KeyboardInterrupt:
        print(f"\n{RED}  ──────────────────────────────────────────{RESET}")
        print(f"  {BOLD}Session ended.{RESET} {event_count} events captured.")
        print(f"{RED}  ──────────────────────────────────────────{RESET}\n")


if __name__ == "__main__":
    main()
