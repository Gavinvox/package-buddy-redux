// Package update notifications without Firebase.
// Android: WorkManager runs a periodic background check (survives reboot).
// Linux desktop: a timer while the app is open. Web: not used.
// Both remember the last seen change id ("cursor") so nothing is shown twice.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:workmanager/workmanager.dart';

import 'desktop.dart';
import 'widgets/common.dart';

const kNotifyEnabled = 'notify_enabled';
const kNotifyHours = 'notify_hours'; // 6, 12, 24 (0 = off)
const kNotifyCursor = 'notify_cursor';
const kDefaultHours = 6;
const _taskName = 'pb-check-updates';

bool get _isAndroid => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
bool get _isLinux => !kIsWeb && defaultTargetPlatform == TargetPlatform.linux;
bool get notificationsSupported => _isAndroid || _isLinux;

final FlutterLocalNotificationsPlugin _plugin = FlutterLocalNotificationsPlugin();
final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();
void Function(int packageId)? onOpenPackage;
int? pendingOpenPackage;

Future<bool> _initPlugin({bool foreground = false}) async {
  if (!notificationsSupported) return false;
  try {
    await _plugin.initialize(
      settings: InitializationSettings(
        android: const AndroidInitializationSettings('ic_stat_pb'),
        linux: LinuxInitializationSettings(
            defaultActionName: 'Open package', defaultIcon: ThemeLinuxIcon('net.packagebuddy.selfhosted.packagebuddy')),
      ),
      onDidReceiveNotificationResponse: foreground ? _onTap : null,
    );
    return true;
  } catch (_) {
    return false;
  }
}

void _onTap(NotificationResponse r) {
  final id = int.tryParse(r.payload ?? '');
  if (id == null) return;
  showDesktopWindow();
  if (onOpenPackage != null) {
    onOpenPackage!(id);
  } else {
    pendingOpenPackage = id;
  }
}

/// Called from main(): set up the plugin, remember a launch-from-notification tap,
/// and (re)register the background job with the saved interval.
Future<void> initNotifications() async {
  if (!notificationsSupported) return;
  await _initPlugin(foreground: true);
  try {
    final launch = await _plugin.getNotificationAppLaunchDetails();
    if (launch?.didNotificationLaunchApp ?? false) {
      pendingOpenPackage = int.tryParse(launch!.notificationResponse?.payload ?? '');
    }
  } catch (_) {}
  if (_isAndroid) {
    await Workmanager().initialize(callbackDispatcher);
  }
  await applySchedule();
  final p = await SharedPreferences.getInstance();
  if (p.getInt(kNotifyCursor) == null) checkForUpdates(refreshFirst: false);
}

Future<(bool, int)> loadNotifySettings() async {
  final p = await SharedPreferences.getInstance();
  return (p.getBool(kNotifyEnabled) ?? true, p.getInt(kNotifyHours) ?? kDefaultHours);
}

Future<void> saveNotifySettings({bool? enabled, int? hours}) async {
  final p = await SharedPreferences.getInstance();
  if (enabled != null) await p.setBool(kNotifyEnabled, enabled);
  if (hours != null) await p.setInt(kNotifyHours, hours);
  await applySchedule();
}

Timer? _desktopTimer;
Timer? _desktopSoon;

Future<void> applySchedule() async {
  final (enabled, hours) = await loadNotifySettings();
  final on = enabled && hours > 0;
  if (_isAndroid) {
    if (on) {
      await Workmanager().registerPeriodicTask(_taskName, _taskName,
          frequency: Duration(hours: hours),
          initialDelay: const Duration(minutes: 15),
          constraints: Constraints(networkType: NetworkType.connected),
          existingWorkPolicy: ExistingPeriodicWorkPolicy.update);
      await enqueueImmediateCheck();
    } else {
      await Workmanager().cancelByUniqueName(_taskName);
    }
  } else if (_isLinux) {
    _desktopTimer?.cancel();
    _desktopTimer = null;
    _desktopSoon?.cancel();
    _desktopSoon = null;
    if (on) {
      _desktopTimer = Timer.periodic(Duration(hours: hours), (_) => checkForUpdates());
      // check shortly after start (and when hidden in the tray) too
      _desktopSoon = Timer(const Duration(seconds: 20), () => checkForUpdates());
    }
  }
}

/// Android 13+ runtime permission. Returns true if allowed.
Future<bool> requestPermission() async {
  if (!_isAndroid) return true;
  final a = _plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
  return await a?.requestNotificationsPermission() ?? true;
}

Future<bool> permissionGranted() async {
  if (!_isAndroid) return true;
  final a = _plugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
  return await a?.areNotificationsEnabled() ?? true;
}

const _battery = MethodChannel('packagebuddy/battery');
Future<bool> batteryUnrestricted() async {
  if (!_isAndroid) return true;
  try {
    return await _battery.invokeMethod<bool>('isIgnoring') ?? false;
  } catch (_) {
    return false;
  }
}

Future<void> openBatterySettings() async {
  if (!_isAndroid) return;
  try {
    await _battery.invokeMethod('request');
  } catch (_) {}
}


/// Re-register background work after login and seed the cursor.
Future<void> afterLogin() async {
  if (!notificationsSupported) return;
  await applySchedule();
}

/// One-off WorkManager job so the first check does not wait for the 6-hour interval
/// (or the 15-minute minimum of a periodic task).
Future<void> enqueueImmediateCheck() async {
  if (!_isAndroid) return;
  final (enabled, hours) = await loadNotifySettings();
  if (!(enabled && hours > 0)) return;
  final p = await SharedPreferences.getInstance();
  await p.reload();
  if ((p.getString('token') ?? '').isEmpty) return;
  try {
    await Workmanager().registerOneOffTask('pb-check-once', _taskName,
        constraints: Constraints(networkType: NetworkType.connected),
        existingWorkPolicy: ExistingWorkPolicy.replace);
  } catch (_) {}
}

const kAskedNotifyPerm = 'asked_notify_permission';
const kAskedBattery = 'asked_battery_exemption';

/// After login (or on first launch of 0.4.0): ask for notification permission
/// and, once, for the battery exemption. Then make sure work is scheduled.
Future<void> runNotificationOnboarding(BuildContext context) async {
  if (!notificationsSupported) return;
  if (_isAndroid) {
    await _maybeAskNotifyPermission(context);
    if (!context.mounted) return;
    await applySchedule();
    if (!context.mounted) return;
    await _maybeAskBatteryExemption(context);
  } else {
    await applySchedule();
  }
}

Future<void> _maybeAskNotifyPermission(BuildContext context) async {
  if (await permissionGranted()) return;
  final p = await SharedPreferences.getInstance();
  if (p.getBool(kAskedNotifyPerm) ?? false) return;
  if (!context.mounted) return;
  final ok = await confirm(
    context,
    'Get package updates',
    'Package Buddy Redux can notify you when a package moves or is delivered. '
        'It checks your own server in the background (no Google account or cloud messaging). '
        'Allow notifications?',
    ok: 'Allow',
    cancel: 'Not now',
  );
  await p.setBool(kAskedNotifyPerm, true);
  if (ok) await requestPermission();
}

Future<void> _maybeAskBatteryExemption(BuildContext context) async {
  if (await batteryUnrestricted()) return;
  final p = await SharedPreferences.getInstance();
  if (p.getBool(kAskedBattery) ?? false) return;
  if (!context.mounted) return;
  final ok = await confirm(
    context,
    'Allow background checks',
    'Some phones (including Nokia) stop apps from running in the background to save battery, '
        'so package notifications may never arrive. Allow Package Buddy Redux to run unrestricted? '
        'You can change this later in Settings.',
    ok: 'Allow',
    cancel: 'Not now',
  );
  await p.setBool(kAskedBattery, true);
  if (ok) await openBatterySettings();
}

/// Shared by the background job and the desktop timer.
/// Returns the number of notifications shown.
Future<int> checkForUpdates({bool refreshFirst = true}) async {
  final p = await SharedPreferences.getInstance();
  await p.reload();
  final enabled = p.getBool(kNotifyEnabled) ?? true;
  final base = (p.getString('server_url') ?? '').replaceAll(RegExp(r'/+$'), '');
  final token = p.getString('token');
  if (!enabled || base.isEmpty || token == null) return 0;
  final h = {'Accept': 'application/json', 'Authorization': 'Bearer $token'};
  Uri u(String path, [Map<String, String>? q]) => Uri.parse('$base/api/v1$path').replace(queryParameters: q);
  final client = http.Client();
  try {
    final cursor = p.getInt(kNotifyCursor);
    if (cursor == null) {
      // first run: start from "now" so old history is not replayed
      final r = await client.get(u('/changes/latest'), headers: h).timeout(const Duration(seconds: 30));
      if (r.statusCode == 200) {
        await p.setInt(kNotifyCursor, (jsonDecode(r.body)['latest_id'] as num).toInt());
      } else if (r.statusCode == 404) {
        await p.setInt(kNotifyCursor, 0); // older server without /changes/latest
      }
      return 0;
    }
    if (refreshFirst) {
      try {
        await client.post(u('/packages/refresh'), headers: h).timeout(const Duration(seconds: 90));
      } catch (_) {}
    }
    final r = await client
        .get(u('/changes', {'since_id': '$cursor', 'limit': '500'}), headers: h)
        .timeout(const Duration(seconds: 30));
    if (r.statusCode != 200) return 0;
    final rows = (jsonDecode(utf8.decode(r.bodyBytes)) as List).cast<Map<String, dynamic>>();
    if (rows.isEmpty) return 0;
    var maxId = cursor;
    final byPkg = <int, List<Map<String, dynamic>>>{};
    for (final c in rows) {
      final id = (c['id'] as num).toInt();
      if (id > maxId) maxId = id;
      final kind = c['kind'];
      if ((kind == 'status' || kind == 'new_events') && c['package_id'] != null) {
        byPkg.putIfAbsent((c['package_id'] as num).toInt(), () => []).add(c);
      }
    }
    var shown = 0;
    if (byPkg.isNotEmpty && await _initPlugin()) {
      for (final e in byPkg.entries) {
        Map<String, dynamic>? pkg;
        try {
          final pr = await client.get(u('/packages/${e.key}'), headers: h).timeout(const Duration(seconds: 30));
          if (pr.statusCode == 200) pkg = jsonDecode(utf8.decode(pr.bodyBytes)) as Map<String, dynamic>;
        } catch (_) {}
        await showPackageNotification(e.key, pkg, e.value.last);
        shown++;
      }
    }
    await p.setInt(kNotifyCursor, maxId);
    return shown;
  } catch (_) {
    return 0;
  } finally {
    client.close();
  }
}

String _s(dynamic v) => v == null ? '' : '$v';

Future<void> showPackageNotification(int packageId, Map<String, dynamic>? pkg, Map<String, dynamic> change) async {
  final number = _s(pkg?['tracking_number'] ?? change['tracking_number']);
  final desc = _s(pkg?['description']);
  final title = desc.isNotEmpty ? desc : number;
  final evText = _s(pkg?['status_text'] ?? change['message']);
  final loc = _s(pkg?['last_location']);
  final status = _s(pkg?['state_label'] ?? change['new_state']);
  final body = [
    if (status.isNotEmpty && change['kind'] == 'status') status,
    if (evText.isNotEmpty) evText else if (change['kind'] != 'status') status,
    if (loc.isNotEmpty) loc,
  ].join(' — ');
  final carrier = _s(pkg?['carrier_name']);
  await _plugin.show(
    id: packageId,
    title: title,
    body: body.isEmpty ? 'Tracking updated' : body,
    payload: '$packageId',
    notificationDetails: NotificationDetails(
      android: AndroidNotificationDetails('package_updates', 'Package updates',
          channelDescription: 'New tracking events, status changes and deliveries',
          importance: Importance.defaultImportance,
          priority: Priority.defaultPriority,
          color: const Color(0xFF1565C0),
          subText: carrier.isEmpty ? null : carrier,
          styleInformation: BigTextStyleInformation(body.isEmpty ? 'Tracking updated' : body,
              contentTitle: title, summaryText: carrier.isEmpty ? null : carrier),
          category: AndroidNotificationCategory.status,
          when: DateTime.now().millisecondsSinceEpoch,
          showWhen: true),
      linux: const LinuxNotificationDetails(defaultActionName: 'Open package'),
    ),
  );
}

@pragma('vm:entry-point')
void callbackDispatcher() {
  Workmanager().executeTask((task, input) async {
    WidgetsFlutterBinding.ensureInitialized();
    await checkForUpdates();
    return true;
  });
}
