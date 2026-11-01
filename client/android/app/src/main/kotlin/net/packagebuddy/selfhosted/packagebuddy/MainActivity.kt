package net.packagebuddy.selfhosted.packagebuddy

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "packagebuddy/battery").setMethodCallHandler { call, result ->
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            when (call.method) {
                "isIgnoring" -> result.success(pm.isIgnoringBatteryOptimizations(packageName))
                "request" -> {
                    try {
                        startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
                    } catch (e: Exception) {
                        try { startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) } catch (_: Exception) {}
                    }
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }
}
