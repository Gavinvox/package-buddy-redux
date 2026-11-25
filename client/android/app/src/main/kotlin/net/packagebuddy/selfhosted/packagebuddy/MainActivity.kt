package net.packagebuddy.selfhosted.packagebuddy

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

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
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "packagebuddy/install").setMethodCallHandler { call, result ->
            when (call.method) {
                "canInstall" -> {
                    val can = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                        packageManager.canRequestPackageInstalls() else true
                    result.success(can)
                }
                "requestInstallPermission" -> {
                    try {
                        startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
                    } catch (_: Exception) {}
                    result.success(null)
                }
                "installApk" -> {
                    val path = call.arguments as String
                    try {
                        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", File(path))
                        val intent = Intent(Intent.ACTION_VIEW).apply {
                            setDataAndType(uri, "application/vnd.android.package-archive")
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        startActivity(intent)
                        result.success(null)
                    } catch (e: Exception) {
                        result.error("install", e.message, null)
                    }
                }
                else -> result.notImplemented()
            }
        }
    }
}
