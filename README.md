# 🔐 Input Capture Security Research
### Linux evdev Keylogger + Android Accessibility Keylogger
#### A complete attack/defence security research project — MITRE ATT&CK T1056.001 & T1056.002

> **⚠ Legal Disclaimer:** All research was conducted exclusively on hardware owned by the author. No third-party devices were used. Deploying this on any device without explicit owner consent is a criminal offence under §202a StGB (Germany) and equivalent laws globally. This project exists solely for security research and educational purposes.

---

## 📁 Project Structure

```
keylogger-lab/                          ← VERSION 1: Linux evdev
├── attacker/
│   ├── stage1_raw.py                   raw kernel keycodes
│   ├── stage2_mapped.py                character mapping + buffer
│   ├── stage3_context.py               app + window context (Hyprland IPC)
│   ├── stage4_keylogger.py             silent daemon + hidden log
│   └── stage4_viewer.py                live keystroke feed viewer
├── defender/
│   └── detector.py                     3-method keylogger detector
├── logs/
│   └── .keylog                         log placeholder
└── report/
    └── writeup.md                      full security research paper

keylogger-lab-v2/                       ← VERSION 2: Android
├── android-app/                        Android Studio project
│   └── app/src/main/
│       ├── java/com/security/research/phonemonitor/
│       │   ├── KeyloggerService.kt     Accessibility Service core
│       │   ├── MainActivity.kt         status UI
│       │   └── BootReceiver.kt         persistence on reboot
│       ├── res/
│       │   ├── xml/accessibility_service_config.xml
│       │   ├── layout/activity_main.xml
│       │   └── values/
│       └── AndroidManifest.xml
├── receiver/
│   └── receiver.py                     Python WebSocket receiver
└── report/
    └── writeup_v2.md                   full security research paper
```

---

## 🖥 Version 1 — Linux evdev Keylogger

### Concept

On Linux, the kernel exposes raw input events at `/dev/input/event*` via the **evdev** subsystem. Every keypress exists here as an `input_event` struct — before Wayland, before X11, before any application sees it. A process with root access (or `input` group membership) can read this device file directly, capturing all keyboard input regardless of which compositor or application is running.

```
Physical Keyboard
      ↓
Linux Kernel (evdev driver)
      ↓
/dev/input/event3   ← WE READ HERE (below everything)
      ↓
Wayland Compositor  ← enforces per-client isolation above this line only
      ↓
Application
```

**Key finding:** Wayland's input isolation model does NOT protect against kernel-level input capture. This was verified on Arch Linux with Hyprland 0.47.2.

---

### Environment

| Component | Details |
|---|---|
| OS | Arch Linux x86_64 |
| Kernel | Linux 6.13.6-arch1-1 |
| Compositor | Hyprland 0.47.2 (Wayland) |
| Shell | zsh 5.9 |
| Python | 3.12+ |
| Keyboard device | `/dev/input/event3` (AT Translated Set 2) |

---

### Setup

```bash
# Install dependency
sudo pip install evdev --break-system-packages

# Create project structure
mkdir -p ~/keylogger-lab/{attacker,defender,logs,report}

# Find your keyboard device
sudo python3 -c "
import evdev
for path in evdev.list_devices():
    d = evdev.InputDevice(path)
    print(d.path, d.name)
"
```

---

### Stage 1 — Raw Kernel Keycodes

**File:** `attacker/stage1_raw.py`

**What it does:** Opens `/dev/input/event3` directly and reads raw `input_event` structs from the kernel. Prints every keypress with timestamp, keycode, and event type (PRESS/RELEASE/REPEAT).

**Run:**
```bash
sudo python3 attacker/stage1_raw.py
```

**What you learn:**
- The kernel tracks 3 states per key: press (value=1), release (value=0), repeat (value=2)
- Fast typing causes key overlaps — Key N+1 pressed before Key N released
- This is the raw data below all software abstractions
- Keystroke dynamics (timing, overlap) are fully visible — used in behavioural biometrics

**Sample output:**
```
[20:05:29.961]  ▶ PRESS    KEY_H    code=35   value=1
[20:05:30.104]  ▷ RELEASE  KEY_H    code=35   value=0
[20:05:30.213]  ▶ PRESS    KEY_E    code=18   value=1
```

---

### Stage 2 — Character Mapping

**File:** `attacker/stage2_mapped.py`

**What it does:** Maps raw keycodes to readable characters using a full keycode→char lookup table. Tracks Shift and CapsLock state for accurate capitalisation and special characters. Builds a live text buffer — on Enter, displays the full captured line.

**Run:**
```bash
sudo python3 attacker/stage2_mapped.py
```

**What you learn:**
- Shift state tracked via KEY_LEFTSHIFT/KEY_RIGHTSHIFT press/release events
- CapsLock uses XOR logic (CapsLock inverts shift for letter keys)
- Backspace correctly removes the previous character from the buffer
- The buffer reconstructs user intent, not raw keystrokes

**Sample output:**
```
▶ KEY_H    → h    buffer: h█
▶ KEY_E    → e    buffer: he█
⌫ BACKSPACE  (removed: 'e')
↵  hello there
─────────────────────────────
```

---

### Stage 3 — Context-Aware Capture

**File:** `attacker/stage3_context.py`

**What it does:** Adds application context to every captured line by querying the **Hyprland IPC socket** at `/run/user/1000/hypr/<signature>/.socket.sock`. Each Enter event is tagged with the active application name and window title. Includes a password scoring heuristic (0–100) based on character class diversity.

**Dependencies:**
```bash
sudo pacman -S socat
```

**Run:**
```bash
sudo python3 attacker/stage3_context.py
```

**Key technical detail:** The keylogger runs as root but the Hyprland socket is owned by the user session. The IPC query must be delegated back to the user context via `sudo -u #1000` to access the socket correctly.

**Sample output:**
```
╔══ CAPTURED ══════════════════════════════════════════════
║  time :  2026-03-14 20:56:50
║  app  :  firefox
║  title:  YouTube — Original profile — Mozilla Firefox
║  text :  funny videos
╚══════════════════════════════════════════════════════════

╔══ CAPTURED ══════════════════════════════════════════════
║  time :  2026-03-14 20:57:18
║  app  :  firefox
║  title:  Gmail — Mozilla Firefox
║  text :  MyP@ssword123
║  score:  ⚠ HIGH LIKELIHOOD PASSWORD  (90/100)
╚══════════════════════════════════════════════════════════
```

---

### Stage 4 — Silent Daemon

**Files:** `attacker/stage4_keylogger.py`, `attacker/stage4_viewer.py`

**What it does:** Transforms the keylogger into a realistic threat actor tool:

- **Double-fork daemonisation** — detaches from terminal completely, survives terminal close, no visible output
- **Hidden log files** — writes to `~/.local/share/.syslog` (structured line log) and `~/.local/share/.ksraw` (per-keystroke live feed)
- **Separate viewer** — `stage4_viewer.py` tails the raw keystroke log, reconstructing text character-by-character in real time
- **Credential detection** — flags captured strings scoring ≥80 with `⚠ CREDENTIAL` alert
- **Auto-rotation** — rotates log file at 10MB

**Run (3 terminals):**
```bash
# Terminal 1 — start daemon silently
sudo python3 attacker/stage4_keylogger.py
# Returns to prompt immediately — running invisibly in background

# Terminal 2 — live viewer
sudo python3 attacker/stage4_viewer.py

# Terminal 3 — use your computer normally
# Everything you type appears in Terminal 2
```

**Control commands:**
```bash
sudo python3 attacker/stage4_keylogger.py --status   # check running + log size
sudo python3 attacker/stage4_keylogger.py --stop     # kill daemon
sudo python3 attacker/stage4_viewer.py --dump        # show all captured entries
sudo python3 attacker/stage4_viewer.py --passwords   # show only likely credentials
```

**Sample viewer output:**
```
── foot ──────────────────────────────
▶ [21:25:15.123]  h   → h█
▶ [21:25:15.234]  e   → he█
▶ [21:25:15.312]  l   → hel█
▶ [21:25:15.401]  l   → hell█
▶ [21:25:15.489]  o   → hello█
  ↵  hello there
  ───────────────────────────────────────────────

  ↵  Admin@123  ⚠  CREDENTIAL
  ───────────────────────────────────────────────
```

---

### Defender — Keylogger Detector

**File:** `defender/detector.py`

**What it does:** Detects active keyloggers using 3 independent methods. Successfully detected the running Stage 4 daemon with zero false positives after tuning.

**Run:**
```bash
sudo python3 defender/detector.py           # single scan
sudo python3 defender/detector.py --watch   # continuous scan every 5s
```

#### Method 1 — /proc File Descriptor Scan

Iterates all PIDs in `/proc/*/fd/` and resolves symlinks to find any process with a `/dev/input/*` file descriptor open. Cross-references against a safe list of known legitimate processes (systemd, Hyprland, systemd-logind, upowerd). Reports suspicious processes with PID, name, user, command, and kill command.

```
✓  PID      1  systemd         reading 13 device(s)  (safe)
✓  PID    765  systemd-logind  reading 20 device(s)  (safe)
✓  PID   1417  Hyprland        reading 13 device(s)  (safe)

!  SUSPICIOUS PROCESS READING INPUT DEVICE
║  PID     : 41595
║  Name    : python3
║  User    : root
║  Devices : /dev/input/event3
║  Command : python3 stage4_keylogger.py
║  Kill it: sudo kill -9 41595
```

#### Method 2 — Input Group Membership Audit

Enumerates `/etc/group` for `input` group members. Flags users with interactive shells (as opposed to service accounts with nologin shells). Lists all `/dev/input/*` device permissions.

#### Method 3 — Hidden File Scanner

Scans `/root`, `/home`, `/tmp`, `/var/tmp`, `/dev/shm` for hidden files matching suspicious patterns: `.syslog`, `.ksraw`, `.klog`, `.keylog`, `.keys`, `.capture`. Shows file size, modification time, and content preview.

```
!  SUSPICIOUS HIDDEN FILE FOUND
║  Path    : /root/.local/share/.ksraw
║  Size    : 12643 bytes
║  Preview : 21:21:03|firefox|[CTRL+C] 21:21:07|foot|hello...
║  Delete:   rm /root/.local/share/.ksraw
```

**Final summary:**
```
⚠ KEYLOGGER ACTIVITY DETECTED
  Suspicious processes : 1
  Suspicious files     : 2
  sudo kill -9 41595
  rm /root/.local/share/.ksraw
  rm /root/.local/share/.syslog
```

---

## 📱 Version 2 — Android Accessibility Keylogger

### Concept

Android's Accessibility Service API was designed for screen readers and assistive tools. It provides system-sanctioned access to all UI text events across all applications. When abused, it captures every keystroke in every app — including end-to-end encrypted apps like WhatsApp — because the text is intercepted **before** encryption occurs.

```
User types on keyboard
        ↓
Android IME (Input Method Editor)
        ↓
Accessibility Service fires event   ← WE INTERCEPT HERE
        ↓
Application receives text
        ↓
WhatsApp E2E encryption             ← network sniffing useless below this
        ↓
Encrypted packet
```

**Key finding:** End-to-end encryption provides zero protection against Accessibility Service-based keylogging. This was verified against WhatsApp on Android 13.

---

### Environment

| Component | Details |
|---|---|
| Phone | Vivo Android device |
| Android version | 13+ |
| Connection | USB via ADB reverse tunnel |
| Receiver | Python 3.14, websockets 16.0 |
| Build system | Android Studio, AGP 8.3.0, Kotlin 1.9.22 |
| Laptop | Arch Linux, same machine as Version 1 |

---

### Setup

#### Laptop (receiver)

```bash
# Install websockets
pip install websockets --break-system-packages

# Create project directory
mkdir -p ~/keylogger-lab-v2/receiver

# Start receiver
python3 ~/keylogger-lab-v2/receiver/receiver.py
```

#### Phone

```bash
# Install ADB
sudo pacman -S android-tools

# Enable Developer Mode on phone:
# Settings → About Phone → tap Build Number 7 times

# Enable USB Debugging:
# Settings → Developer Options → USB Debugging → ON

# Verify connection
adb devices
# Should show: XXXXXXXXX  device

# Set up ADB reverse tunnel (phone → laptop via USB)
adb reverse tcp:9999 tcp:9999
adb reverse --list
# Should show: UsbFfs tcp:9999 tcp:9999

# Build APK in Android Studio → Build → Build APK(s)

# Install APK
adb install ~/keylogger-lab-v2/android-app/app/build/outputs/apk/debug/app-debug.apk
```

#### Enable Accessibility Service on phone

```
Open "System Service" app
→ Tap "Enable Accessibility Service"
→ Settings → Accessibility → Downloaded Apps → System Service → ON
→ Tap Allow
```

---

### Android App Components

#### KeyloggerService.kt — Core capture engine

Extends `AccessibilityService`. Registers for `TYPE_VIEW_TEXT_CHANGED` and `TYPE_WINDOW_STATE_CHANGED` events across all applications. On each text change event, extracts the package name and text content, serialises to JSON, and sends over WebSocket to the laptop receiver.

Implements automatic WebSocket reconnection with 3-second delay using Kotlin coroutines — connection survives network interruptions and app restarts.

#### MainActivity.kt — Status UI

Minimal activity showing whether the Accessibility Service is currently enabled. Provides a button to open Android Accessibility Settings directly. Checks service status via `Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES`.

#### BootReceiver.kt — Persistence

Registers for `ACTION_BOOT_COMPLETED` broadcast. Android automatically restores enabled Accessibility Services after reboot — this receiver handles any additional startup logic.

#### network_security_config.xml — Cleartext permission

Android 9+ blocks cleartext (non-HTTPS) traffic by default. This config explicitly permits cleartext WebSocket (`ws://`) connections, required for the local development receiver.

---

### Receiver — receiver.py

Python asyncio WebSocket server listening on `0.0.0.0:9999`. For each connected device:

- Parses incoming JSON events
- Resolves package names to friendly app names and categories
- Applies password scoring heuristic
- Flags banking/payment apps as high priority
- Displays colour-coded live feed in terminal
- Writes structured log to `~/.local/share/.phonelog`

**App category map includes:** WhatsApp, Telegram, Instagram, Twitter, Gmail, Chrome, Firefox, HDFC Bank, SBI, ICICI, PhonePe, Paytm, GPay, Amazon, and 20+ others.

**Sample output:**
```
[+] Phone connected: 127.0.0.1:54821

  ┌─ 💬 Messaging  WhatsApp  [13:16:04]
  ║  pkg  : com.whatsapp
  ║  text : hello what are you doing
  └───────────────────────────────────────────────────────

  ╔══ 💬 Messaging  WhatsApp  [13:16:30]
  ║  pkg  : com.whatsapp
  ║  text : Secret1@
  ║  ⚠ CREDENTIAL — score 100/100
  ╚═══════════════════════════════════════════════════════

  ╔══ 🏦 BANKING  HDFC Bank  [13:17:42]
  ║  pkg  : com.hdfc.bank
  ║  text : mpin1234
  ║  ⚠ CREDENTIAL — score 80/100
  ║  🏦 HIGH PRIORITY — financial app
  ╚═══════════════════════════════════════════════════════
```

---

### Build Notes

**Key issues encountered and resolved:**

| Issue | Fix |
|---|---|
| `Namespace not specified` | Added `namespace "com.security.research.phonemonitor"` to `app/build.gradle` |
| Theme color attributes not found | Changed parent theme from Material3 to `Theme.AppCompat.DayNight.NoActionBar` |
| `mipmap/ic_launcher not found` | Generated PNG icons for all density buckets using Python |
| Cleartext traffic blocked | Added `network_security_config.xml` with `cleartextTrafficPermitted="true"` |
| gradlew permission denied | `chmod +x gradlew` |
| Gradle version mismatch (9.4 vs 8.x) | Used Android Studio's internal Gradle instead of system Gradle |
| Phone unreachable over WiFi | Used `adb reverse tcp:9999 tcp:9999` to tunnel over USB cable |
| `ws://` connection refused | Used `127.0.0.1` as C2 host with ADB reverse instead of LAN IP |

---

## 🔬 MITRE ATT&CK Coverage

| Version | Tactic | Technique | Sub-technique |
|---|---|---|---|
| V1 | Collection | Input Capture (T1056) | Keylogging (T1056.001) |
| V2 | Collection | Input Capture (T1056) | GUI Input Capture (T1056.002) |
| V2 | Persistence | Boot Autostart (T1398) | — |
| V2 | Defense Evasion | Masquerading (T1655) | — |
| V2 | Exfiltration | Exfil Over C2 (T1041) | — |

---

## 🛡 Detection Summary

| Version | Method | Result |
|---|---|---|
| V1 | /proc fd scan | ✅ Detected python3 reading event3 |
| V1 | input group audit | ✅ Flagged unexpected group members |
| V1 | hidden file scan | ✅ Found .ksraw and .syslog |
| V2 | Accessibility service audit | ✅ Shows in Settings → Accessibility |
| V2 | ADB dumpsys | ✅ `adb shell dumpsys accessibility` |
| V2 | Logcat monitoring | ✅ `adb logcat \| grep PhoneMonitor` |

---

## 🚀 Quick Start

### Version 1

```bash
# Clone and setup
git clone <repo> keylogger-lab && cd keylogger-lab
sudo pip install evdev --break-system-packages

# Run attacker (4 progressive stages)
sudo python3 attacker/stage1_raw.py        # raw keycodes
sudo python3 attacker/stage2_mapped.py     # readable chars
sudo python3 attacker/stage3_context.py    # app context
sudo python3 attacker/stage4_keylogger.py  # silent daemon
sudo python3 attacker/stage4_viewer.py     # live viewer

# Run defender
sudo python3 defender/detector.py          # detect keylogger
sudo python3 defender/detector.py --watch  # continuous monitor
```

### Version 2

```bash
# Setup
pip install websockets --break-system-packages
adb reverse tcp:9999 tcp:9999

# Start receiver
python3 receiver/receiver.py

# Install and run Android app (build in Android Studio first)
adb install android-app/app/build/outputs/apk/debug/app-debug.apk
# Enable Accessibility Service on phone
# Type in any app — see output in receiver terminal
```

---

## 📄 Research Papers

- `keylogger-lab/report/writeup.md` — Linux evdev keylogger research
- `keylogger-lab-v2/report/writeup_v2.md` — Android Accessibility keylogger research

Both papers cover: technical breakdown, MITRE ATT&CK mapping, detection methodology, mitigation recommendations.

---

## 👤 Author

**Darshith**
Security Research | Arch Linux | Android | Python | Kotlin
March 2026

---

*This project was built as part of a cybersecurity portfolio for internship applications in Germany.*
*All research conducted on personal hardware. Never deployed on third-party devices.*
