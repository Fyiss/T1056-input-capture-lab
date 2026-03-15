#!/usr/bin/env python3
"""
defender/detector.py — Keylogger Detector
==========================================
Detects keyloggers running on your system using 3 methods:

  Method 1 → /proc fd scan    : finds processes with /dev/input/* open
  Method 2 → input group audit: flags unexpected members of 'input' group
  Method 3 → hidden file scan : finds suspicious hidden log files

Run this while stage4_keylogger.py is running silently.
Watch it catch itself.

Usage:
  sudo python3 defender/detector.py          # full scan once
  sudo python3 defender/detector.py --watch  # continuous monitor (every 5s)

Must be run as root to read /proc/<pid>/fd/ of other processes.
"""

import os
import sys
import time
import grp
import pwd
from pathlib import Path
from datetime import datetime

RED     = "\033[91m"
YELLOW  = "\033[93m"
GREEN   = "\033[92m"
CYAN    = "\033[96m"
MAGENTA = "\033[95m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RESET   = "\033[0m"

BANNER = f"""
{GREEN}{BOLD}
██████╗ ███████╗███████╗███████╗███╗   ██╗██████╗ ███████╗██████╗
██╔══██╗██╔════╝██╔════╝██╔════╝████╗  ██║██╔══██╗██╔════╝██╔══██╗
██║  ██║█████╗  █████╗  █████╗  ██╔██╗ ██║██║  ██║█████╗  ██████╔╝
██║  ██║██╔══╝  ██╔══╝  ██╔══╝  ██║╚██╗██║██║  ██║██╔══╝  ██╔══██╗
██████╔╝███████╗██║     ███████╗██║ ╚████║██████╔╝███████╗██║  ██║
╚═════╝ ╚══════╝╚═╝     ╚══════╝╚═╝  ╚═══╝╚═════╝ ╚══════╝╚═╝  ╚═╝
{RESET}
{DIM}  Keylogger Detection Tool | 3-method scan{RESET}
{GREEN}  ──────────────────────────────────────────────────────────{RESET}
  {CYAN}Method 1{RESET}  /proc fd scan      → processes reading /dev/input/*
  {CYAN}Method 2{RESET}  input group audit  → unexpected group members
  {CYAN}Method 3{RESET}  hidden file scan   → suspicious log files on disk
{GREEN}  ──────────────────────────────────────────────────────────{RESET}
"""

# ── Known safe processes that legitimately read input devices ────────────────
SAFE_PROCESSES = {
    "hyprland", "sway", "wlroots", "Xorg", "X", "xorg",
    "libinput", "systemd", "udevd", "systemd-udevd",
    "systemd-logind",   # manages sessions, legitimately reads input for lid/power events
    "upowerd",          # power management, reads input for battery/lid state
    "inputplug", "acpid", "triggerhappy", "xdg-desktop-por",
}

# ── Suspicious hidden file patterns ──────────────────────────────────────────
SUSPICIOUS_PATTERNS = [
    ".syslog", ".ksraw", ".klog", ".keylog", ".keys",
    ".inputlog", ".capture", ".hidden", ".log2",
]

SCAN_DIRS = [
    Path("/root/.local/share"),
    Path("/home"),
    Path("/tmp"),
    Path("/var/tmp"),
    Path("/dev/shm"),
]

findings = []


def header(title):
    print(f"\n{CYAN}{BOLD}  ┌─ {title} {'─' * (52 - len(title))}{RESET}")


def ok(msg):
    print(f"  {GREEN}✓{RESET}  {msg}")


def warn(msg):
    print(f"  {YELLOW}⚠{RESET}  {msg}")


def alert(msg):
    print(f"  {RED}{BOLD}!{RESET}  {RED}{msg}{RESET}")
    findings.append(msg)


def get_pid_info(pid):
    """Get process name, user, and cmdline for a PID."""
    try:
        name = Path(f"/proc/{pid}/comm").read_text().strip()
    except Exception:
        name = "unknown"
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        cmdline = cmdline.replace(b"\x00", b" ").decode(errors="replace").strip()
    except Exception:
        cmdline = ""
    try:
        uid  = os.stat(f"/proc/{pid}").st_uid
        user = pwd.getpwuid(uid).pw_name
    except Exception:
        user = "unknown"
    return name, user, cmdline


# ────────────────────────────────────────────────────────────────────────────
# METHOD 1 — /proc file descriptor scan
# ────────────────────────────────────────────────────────────────────────────

def scan_proc_fds():
    header("METHOD 1 — /proc fd scan  (processes reading /dev/input/*)")

    suspicious = []   # list of unique suspicious PIDs
    seen_pids  = {}   # pid -> entry (dedup)
    safe_shown = set()

    for pid_dir in Path("/proc").iterdir():
        if not pid_dir.name.isdigit():
            continue
        pid = pid_dir.name
        fd_dir = pid_dir / "fd"

        try:
            fds = list(fd_dir.iterdir())
        except PermissionError:
            continue
        except Exception:
            continue

        input_devices = []
        for fd in fds:
            try:
                target = os.readlink(fd)
            except Exception:
                continue
            if "/dev/input/" in target:
                input_devices.append(target)

        if not input_devices:
            continue

        name, user, cmdline = get_pid_info(pid)

        if name.lower() in SAFE_PROCESSES:
            # Show safe processes but only once per PID
            if pid not in safe_shown:
                safe_shown.add(pid)
                devs = ", ".join(sorted(set(input_devices)))
                ok(f"PID {pid:>6}  {name:<20} reading {len(input_devices)} device(s)  {DIM}(safe){RESET}")
        else:
            if pid not in seen_pids:
                entry = {
                    "pid":     pid,
                    "name":    name,
                    "user":    user,
                    "cmdline": cmdline,
                    "devices": sorted(set(input_devices)),
                }
                seen_pids[pid] = entry
                suspicious.append(entry)

    if suspicious:
        print()
        for e in suspicious:
            devlist = ", ".join(e["devices"])
            print(f"  {RED}{chr(9552)*60}{RESET}")
            alert(f"SUSPICIOUS PROCESS READING INPUT DEVICE")
            print(f"  {RED}║{RESET}  PID     : {BOLD}{e['pid']}{RESET}")
            print(f"  {RED}║{RESET}  Name    : {BOLD}{RED}{e['name']}{RESET}")
            print(f"  {RED}║{RESET}  User    : {e['user']}")
            print(f"  {RED}║{RESET}  Devices : {BOLD}{devlist}{RESET}")
            print(f"  {RED}║{RESET}  Command : {DIM}{e['cmdline'][:70]}{RESET}")
            print(f"  {RED}║{RESET}")
            print(f"  {RED}║{RESET}  {YELLOW}Kill it:{RESET}  sudo kill -9 {e['pid']}")
            print(f"  {RED}{chr(9552)*60}{RESET}")
    else:
        ok("No unexpected processes found reading input devices.")

    return suspicious


# ────────────────────────────────────────────────────────────────────────────
# METHOD 2 — input group membership audit
# ────────────────────────────────────────────────────────────────────────────

def scan_input_group():
    header("METHOD 2 — input group audit")

    try:
        input_group = grp.getgrnam("input")
        members     = input_group.gr_mem
        gid         = input_group.gr_gid
    except KeyError:
        warn("'input' group not found on this system.")
        return []

    print(f"  {DIM}GID {gid} — members: {members if members else '(none listed in /etc/group)'}{RESET}")

    # Also check which users have input as their primary group
    primary = []
    for p in pwd.getpwall():
        if p.pw_gid == gid:
            primary.append(p.pw_name)

    all_members = set(members) | set(primary)

    # Expected: your own user + system accounts
    # Flag anything that looks like a service account that shouldn't be there
    suspicious = []
    for member in all_members:
        try:
            info = pwd.getpwnam(member)
            shell = info.pw_shell
            # Service accounts usually have nologin shells
            if "nologin" in shell or "false" in shell:
                ok(f"  {member:<20} shell={shell}  {DIM}(service account — expected){RESET}")
            else:
                warn(f"  {member:<20} shell={shell}  — verify this user needs input access")
                suspicious.append(member)
        except Exception:
            warn(f"  {member} — could not look up user info")

    # Check /dev/input permissions
    print(f"\n  {DIM}Device permissions:{RESET}")
    for dev in sorted(Path("/dev/input").iterdir()):
        try:
            s    = dev.stat()
            mode = oct(s.st_mode)[-3:]
            grp_name = grp.getgrgid(s.st_gid).gr_name
            if s.st_gid == gid:
                print(f"  {DIM}{dev.name:<12} mode={mode}  group={grp_name}{RESET}")
        except Exception:
            pass

    return suspicious


# ────────────────────────────────────────────────────────────────────────────
# METHOD 3 — hidden file scanner
# ────────────────────────────────────────────────────────────────────────────

def scan_hidden_files():
    header("METHOD 3 — hidden file scan  (suspicious log files)")

    found = []

    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue

        # Recursively find hidden files (dot-prefixed)
        try:
            for path in scan_dir.rglob(".*"):
                if not path.is_file():
                    continue

                name = path.name.lower()

                # Check against suspicious patterns
                matched = any(pat in name for pat in SUSPICIOUS_PATTERNS)

                if matched:
                    try:
                        size  = path.stat().st_size
                        mtime = datetime.fromtimestamp(path.stat().st_mtime)
                        # Try to peek at contents
                        with open(path, "r", errors="replace") as f:
                            preview = f.read(200).replace("\n", " ")
                    except Exception:
                        size    = -1
                        mtime   = "unknown"
                        preview = "(unreadable)"

                    found.append(path)
                    print()
                    alert(f"SUSPICIOUS HIDDEN FILE FOUND")
                    print(f"  {RED}║{RESET}  Path    : {BOLD}{path}{RESET}")
                    print(f"  {RED}║{RESET}  Size    : {size} bytes")
                    print(f"  {RED}║{RESET}  Modified: {mtime}")
                    print(f"  {RED}║{RESET}  Preview : {DIM}{preview[:80]}...{RESET}")
                    print(f"  {RED}║{RESET}")
                    print(f"  {RED}║{RESET}  {YELLOW}Inspect:{RESET}  cat {path}")
                    print(f"  {RED}║{RESET}  {YELLOW}Delete: {RESET}  rm {path}")

        except PermissionError:
            continue

    if not found:
        ok(f"No suspicious hidden files found in scanned directories.")

    return found


# ────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ────────────────────────────────────────────────────────────────────────────

def print_summary(proc_findings, file_findings):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(proc_findings) + len(file_findings)

    print(f"\n{GREEN if total == 0 else RED}  {'═'*60}{RESET}")
    print(f"  {BOLD}SCAN SUMMARY{RESET}  —  {ts}")
    print(f"  {'─'*58}")

    if total == 0:
        print(f"  {GREEN}{BOLD}✓ No keylogger activity detected.{RESET}")
        print(f"  {DIM}System appears clean.{RESET}")
    else:
        print(f"  {RED}{BOLD}⚠ KEYLOGGER ACTIVITY DETECTED{RESET}")
        print(f"  {RED}  Suspicious processes : {len(proc_findings)}{RESET}")
        print(f"  {RED}  Suspicious files     : {len(file_findings)}{RESET}")
        print()
        print(f"  {YELLOW}Recommended actions:{RESET}")
        seen = set()
        for p in proc_findings:
            if p['pid'] not in seen:
                seen.add(p['pid'])
                print(f"    sudo kill -9 {p['pid']}   # kill {p['name']}")
        for f in file_findings:
            print(f"    rm {f}   # remove log file")

    print(f"{GREEN if total == 0 else RED}  {'═'*60}{RESET}\n")


# ────────────────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────────────────

def run_scan():
    print(f"  {DIM}Scan started: {datetime.now().strftime('%H:%M:%S')}{RESET}")
    proc_findings = scan_proc_fds()
    scan_input_group()
    file_findings = scan_hidden_files()
    print_summary(proc_findings, file_findings)
    return proc_findings, file_findings


def main():
    print(BANNER)

    if os.geteuid() != 0:
        print(f"{RED}[ERROR]{RESET} Must run as root to read /proc fd entries.")
        print(f"       Run: {BOLD}sudo python3 defender/detector.py{RESET}")
        sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == "--watch":
        print(f"  {CYAN}Watch mode — scanning every 5 seconds. Ctrl+C to stop.{RESET}\n")
        try:
            while True:
                run_scan()
                print(f"  {DIM}Next scan in 5 seconds...{RESET}\n")
                time.sleep(5)
        except KeyboardInterrupt:
            print(f"\n  {DIM}Watch mode stopped.{RESET}\n")
    else:
        run_scan()


if __name__ == "__main__":
    main()
