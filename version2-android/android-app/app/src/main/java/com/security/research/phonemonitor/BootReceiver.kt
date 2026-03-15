package com.security.research.phonemonitor

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * BootReceiver.kt
 * ================
 * Fires when the phone boots. Re-enables the accessibility service
 * context. In practice, Android restores accessibility services
 * automatically after reboot — this just ensures any cleanup happens.
 *
 * Real spyware uses this to restart background services that were
 * killed, since Android may kill background processes to save battery.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            // Accessibility services auto-restart on boot if enabled
            // This receiver exists to demonstrate the persistence mechanism
        }
    }
}
