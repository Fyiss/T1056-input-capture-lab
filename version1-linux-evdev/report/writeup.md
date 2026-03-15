# Linux Input Layer Keylogger & Detection Research
### Security Research | Arch Linux | Wayland/Hyprland | evdev | Python

> **Disclaimer:** This research was conducted entirely on personal hardware in a controlled environment. All code was written and executed exclusively on the author's own machine. This document is intended for educational purposes and defensive security awareness.

---

## Executive Summary

This project investigates a class of keylogger attack that operates below the Wayland display protocol by reading raw input events directly from the Linux kernel's evdev interface. Unlike traditional keyloggers that exploit X11's permissive input model, this implementation captures all keyboard input regardless of the active compositor or window manager — including Wayland-based environments such as Hyprland — by accessing `/dev/input/event*` device files at the kernel level.

The research produced two artifacts: a staged keylogger demonstrating the attack in four progressive phases, and a defensive detection tool using three independent detection methods. The keylogger was successfully detected by scanning `/proc` file descriptors, auditing `input` group membership, and scanning the filesystem for hidden log files. Together, these artifacts demonstrate both the attack surface and practical mitigations available to system administrators and security engineers.

---

## 1. Background & Motivation

### 1.1 The X11 Problem

On systems running the X Window System, any unprivileged process can read global keyboard input using the `XQueryKeymap()` API. This is a well-known, longstanding vulnerability — keylogging on X11 requires no elevated privileges and no kernel access. It is trivially exploitable.

### 1.2 The Wayland Promise

Wayland was designed, in part, to fix this. Its security model enforces **per-client input isolation** — a Wayland compositor only delivers input events to the currently focused window. No client application can spy on another application's keystrokes through the Wayland protocol. This is a genuine security improvement.

### 1.3 The Gap Below Wayland

However, Wayland's isolation only applies at the protocol layer. Below it, the Linux kernel exposes raw input events through the **evdev** subsystem at `/dev/input/event*`. These device files are readable by any process with sufficient permissions — specifically, any process running as `root` or belonging to the `input` group.

```
Physical Keyboard
       ↓
Linux Kernel (evdev driver)
       ↓
/dev/input/eventX   ← attack surface — no Wayland isolation here
       ↓
Wayland Compositor  ← reads from here, enforces per-client isolation above
       ↓
Application Window
```

A keylogger operating at the evdev layer captures all input **before** Wayland processes it. The compositor's security model is simply irrelevant.

---

## 2. MITRE ATT&CK Mapping

| Field | Value |
|---|---|
| **Tactic** | Collection (TA0009) |
| **Technique** | Input Capture (T1056) |
| **Sub-technique** | Keylogging (T1056.001) |
| **Platform** | Linux |
| **Permissions Required** | root or `input` group membership |
| **Defense Bypassed** | Wayland input isolation |

**Kill Chain Position:** This technique is typically employed post-initial-access, during the credential access phase. An attacker who has achieved root access (via privilege escalation, compromised service, or physical access) can deploy a keylogger as a persistent credential harvesting mechanism.

---

## 3. Technical Implementation

The keylogger was built in four progressive stages, each adding a layer of capability.

### 3.1 Stage 1 — Raw Kernel Input (stage1_raw.py)

The first stage opens the keyboard device file directly and reads `input_event` structs from the kernel:

```c
struct input_event {
    struct timeval time;   // timestamp
    __u16 type;            // EV_KEY = 1
    __u16 code;            // KEY_A = 30, KEY_ENTER = 28, etc.
    __s32 value;           // 1=press, 0=release, 2=repeat
};
```

This stage demonstrated the fundamental principle: the kernel exposes three event states per key (press, release, repeat), each with a microsecond-precision timestamp. Keystroke dynamics — typing speed, key overlap, hold duration — are fully visible at this layer.

**Key observation:** When typing quickly, consecutive keypresses overlap. Key N+1 is pressed before Key N is released. This is normal typing behaviour, and the kernel captures it precisely. This data can be used for behavioural biometric profiling.

### 3.2 Stage 2 — Character Mapping (stage2_mapped.py)

Stage 2 added a keycode-to-character translation table mapping all 47 printable keys with both normal and shifted variants. Modifier state (Shift, CapsLock) was tracked explicitly to reconstruct accurate text output.

A text buffer was maintained in memory. On `KEY_ENTER`, the buffer was flushed and displayed as a captured line. `KEY_BACKSPACE` correctly removed the previous character from the buffer, accurately reconstructing the user's intended input rather than their raw keystrokes.

### 3.3 Stage 3 — Context-Aware Capture (stage3_context.py)

Stage 3 added application context by querying the Hyprland IPC socket at `/run/user/1000/hypr/<signature>/.socket.sock` using `socat`. On each Enter event, the captured text was tagged with:

- Active application class (e.g., `firefox`, `foot`, `vesktop`)
- Window title (e.g., `Gmail — Mozilla Firefox`, `arch@arch:~`)
- Timestamp

This transforms a raw keystroke log into actionable credential intelligence. A captured string of `hunter2` is unremarkable. The same string tagged with `app: firefox | title: Gmail — Sign in` is a credential.

**Note on root vs user socket access:** The keylogger runs as root but the Hyprland socket is owned by the user session. The window query must be delegated back to the user context via `sudo -u #1000` to access the socket correctly.

### 3.4 Stage 4 — Silent Daemon (stage4_keylogger.py + stage4_viewer.py)

Stage 4 transformed the keylogger into a realistic threat:

**Daemonisation** using the Unix double-fork pattern:
```python
pid = os.fork()
if pid > 0: sys.exit(0)   # parent exits
os.setsid()               # become session leader
pid = os.fork()
if pid > 0: sys.exit(0)   # second parent exits
# redirect stdin/stdout/stderr to /dev/null
```
After the double-fork, the process has no controlling terminal, survives terminal close, and produces no visible output.

**Two hidden log files:**
- `~/.local/share/.syslog` — structured line log (timestamp|app|title|text|score)
- `~/.local/share/.ksraw` — per-keystroke live feed (timestamp|app|char)

**Password scoring heuristic** rated each captured line 0–100 based on character class diversity and length. Lines scoring ≥80 were flagged as likely credentials, enabling prioritised exfiltration in a real attack scenario.

**Separate viewer** (`stage4_viewer.py`) tailed the raw keystroke log in real time, reconstructing the text buffer character-by-character as the victim typed, with colour-coded credential alerts on Enter.

---

## 4. Detection Methodology

The detector (`defender/detector.py`) implements three independent detection methods. All three fired successfully against the running keylogger.

### 4.1 Method 1 — /proc File Descriptor Scan

Every open file descriptor for every running process is listed under `/proc/<pid>/fd/` as symlinks to their targets. By iterating all PIDs and resolving all fd symlinks, any process with `/dev/input/*` open can be identified.

```python
for fd in Path(f"/proc/{pid}/fd").iterdir():
    target = os.readlink(fd)
    if "/dev/input/" in target:
        # flag as suspicious if not in known-safe list
```

**Safe list rationale:** Several system processes legitimately hold input device handles:
- `systemd` (PID 1) — udev event management
- `Hyprland` — compositor reads all input devices
- `systemd-logind` — session management, lid switch, power button
- `upowerd` — battery/power state via input events

The keylogger was correctly identified as `python3` reading `/dev/input/event3` (the keyboard) — distinct from the compositor which reads all devices.

**Result:** `python3 /home/arch/keylogger-lab/attacker/stage4_keylogger.py` — PID 41595 — flagged with kill command.

### 4.2 Method 2 — Input Group Membership Audit

The `input` group controls read access to `/dev/input/*` for non-root processes. Membership should be limited to the primary interactive user and system compositor accounts.

The detector enumerates `/etc/group` membership and cross-references each member's login shell. Service accounts (shell = `/usr/bin/nologin`) are expected. Interactive users with a real shell warrant verification.

**Result:** `arch` (shell: `/usr/bin/zsh`) flagged for verification — expected finding for the primary user on a personal machine. On a server, any interactive user in the `input` group would be a high-severity finding.

### 4.3 Method 3 — Hidden File Scan

The detector scans known staging directories (`/root`, `/home`, `/tmp`, `/var/tmp`, `/dev/shm`) for hidden files matching suspicious naming patterns: `.syslog`, `.ksraw`, `.klog`, `.keylog`, `.keys`, `.capture`.

**Result:** Both keylogger log files detected:
- `/root/.local/share/.ksraw` (12,643 bytes) — live keystroke log
- `/root/.local/share/.syslog` (4,742 bytes) — structured capture log

Preview of `.syslog` showed structured captured data including app context and timestamps, confirming active credential harvesting.

---

## 5. Detection Results

| Method | Finding | Severity |
|---|---|---|
| /proc fd scan | `python3` (PID 41595) reading `/dev/input/event3` | **CRITICAL** |
| input group audit | `arch` in `input` group with interactive shell | LOW (expected on personal machine) |
| Hidden file scan | `.ksraw` 12KB, `.syslog` 4.7KB in `/root/.local/share/` | **HIGH** |

All three methods successfully contributed to detection. Method 1 alone is sufficient for real-time detection of an active keylogger. Method 3 detects residual evidence even after the process is killed.

---

## 6. Mitigation Recommendations

### For System Administrators

**1. Enforce the principle of least privilege for root access.**
This entire attack requires root. Limit sudo access, audit sudoers regularly, and use PAM restrictions.

**2. Monitor /proc fd in real time.**
Deploy auditd rules to log any `open()` syscall targeting `/dev/input/*` from unexpected processes:
```
-a always,exit -F arch=b64 -S open,openat -F path=/dev/input/event3 -k input_access
```

**3. Audit input group membership.**
No user who does not need to run GUI applications on physical hardware should be in the `input` group. On servers, the `input` group should have no members.

**4. Run the detector regularly.**
Add `detector.py --watch` as a systemd service or cron job to catch keyloggers within seconds of deployment.

### For End Users

**5. Wayland does not protect you from root.**
If an attacker achieves root on your machine, Wayland's input isolation provides no protection against kernel-level input capture. Physical security and privilege escalation prevention are the real defences.

**6. Keep your system updated.**
Kernel and compositor patches occasionally address input handling vulnerabilities.

---

## 7. Limitations & Future Work

**Current limitations:**
- The keylogger requires root or `input` group membership — it cannot run as an unprivileged user
- Window context detection requires `socat` and a running Hyprland instance — fails gracefully on other compositors
- The detector does not catch in-memory keyloggers that write no files (Method 3 would miss these)

**Potential extensions:**
- Kernel module (LKM) implementation for deeper stealth — would require signing bypass on systems with Secure Boot
- eBPF-based detector using `bpftrace` to hook `read()` syscalls on input device file descriptors — harder to evade than procfs scanning
- FCM/webhook exfiltration channel to simulate real C2 communication
- Integration with the existing SOC agent for automated alert dispatch

---

## 8. Conclusion

This project demonstrated that Wayland's input isolation model, while a genuine improvement over X11, does not protect against kernel-level input capture. An attacker with root access can silently log all keystrokes, tag them with application context, score them for credential likelihood, and exfil them — all from a process indistinguishable from any other Python script.

The defensive side demonstrated that this attack is detectable through standard Linux observability primitives: `/proc`, group membership, and filesystem scanning. No specialised tools are required. The attack surface is well-defined and the mitigations are practical.

Building both sides of this attack — the keylogger and the detector — produced a concrete understanding of Linux input architecture, process isolation boundaries, daemon programming, and endpoint detection methodology that would not have been achievable through reading alone.

---

## References

- Linux kernel evdev documentation: https://www.kernel.org/doc/html/latest/input/input.html
- MITRE ATT&CK T1056.001: https://attack.mitre.org/techniques/T1056/001/
- Hyprland IPC documentation: https://wiki.hyprland.org/IPC/
- Python evdev library: https://python-evdev.readthedocs.io/
- Wayland security model: https://wayland.freedesktop.org/architecture.html

---

*Research conducted on: Arch Linux x86_64 | Linux 6.13.6-arch1-1 | Hyprland 0.47.2 | Python 3.12*
*Author: Darshith Thalipady Nagesh | Date: March 2026*
