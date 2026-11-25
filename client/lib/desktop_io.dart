// Linux desktop: tray icon, close-to-tray, autostart and start-minimized.
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:tray_manager/tray_manager.dart';
import 'package:window_manager/window_manager.dart';

import 'notify.dart';
import 'widgets/common.dart';

const kCloseToTray = 'close_to_tray';
const kAutostart = 'autostart';
const kStartMinimized = 'start_minimized';

bool get desktopSupported => !kIsWeb && defaultTargetPlatform == TargetPlatform.linux;

bool get launchedMinimized =>
    desktopSupported && Platform.executableArguments.contains('--minimized');

final _controller = _DesktopController();

Future<void> initDesktop() async {
  if (!desktopSupported) return;
  await _controller.init();
}

Future<void> showDesktopWindow() async {
  if (!desktopSupported) return;
  await _controller.show();
}

Future<void> quitDesktop() async {
  if (!desktopSupported) return;
  await _controller.quit();
}

Future<(bool closeToTray, bool autostart, bool startMinimized)> loadDesktopSettings() async {
  final p = await SharedPreferences.getInstance();
  return (p.getBool(kCloseToTray) ?? true, p.getBool(kAutostart) ?? true, p.getBool(kStartMinimized) ?? true);
}

Future<void> saveDesktopSettings({bool? closeToTray, bool? autostart, bool? startMinimized}) async {
  final prefs = await SharedPreferences.getInstance();
  if (closeToTray != null) await prefs.setBool(kCloseToTray, closeToTray);
  if (autostart != null) await prefs.setBool(kAutostart, autostart);
  if (startMinimized != null) await prefs.setBool(kStartMinimized, startMinimized);
  await _controller.applyWindowPolicy();
  await _controller.applyAutostart();
}

class _DesktopController with TrayListener, WindowListener {
  bool _ready = false;

  Future<void> init() async {
    try {
      await windowManager.ensureInitialized();
      windowManager.addListener(this);
      await applyWindowPolicy();
      await windowManager.setTitle('Package Buddy Redux');
    } catch (_) {}
    try {
      await applyAutostart();
    } catch (_) {}
    try {
      await _initTray();
    } catch (_) {}
    _ready = true;
  }

  Future<void> applyWindowPolicy() async {
    final (closeToTray, _, _) = await loadDesktopSettings();
    await windowManager.setPreventClose(closeToTray);
  }

  Future<void> show() async {
    await windowManager.show();
    await windowManager.focus();
  }

  Future<void> quit() async {
    try {
      await windowManager.setPreventClose(false);
      if (_ready) {
        trayManager.removeListener(this);
        await trayManager.destroy();
      }
    } catch (_) {}
    try {
      await windowManager.destroy();
    } catch (_) {}
    exit(0);
  }

  Future<void> _initTray() async {
    trayManager.addListener(this);
    final icon = _trayIconPath();
    if (icon != null) {
      await trayManager.setIcon(icon);
    }
    // setToolTip is not implemented on Linux; skip it so the menu still installs.
    await trayManager.setContextMenu(Menu(items: [
      MenuItem(key: 'open', label: 'Open'),
      MenuItem(key: 'check', label: 'Check now'),
      MenuItem.separator(),
      MenuItem(key: 'quit', label: 'Quit'),
    ]));
  }

  String? _trayIconPath() {
    final exeDir = File(Platform.resolvedExecutable).parent.path;
    for (final c in [
      p.join(exeDir, 'data', 'flutter_assets', 'assets', 'icon', 'tray.png'),
      p.join(exeDir, 'data', 'flutter_assets', 'assets', 'icon', 'logo.png'),
      '/usr/share/icons/hicolor/48x48/apps/net.packagebuddy.selfhosted.packagebuddy.png',
    ]) {
      if (File(c).existsSync()) return c;
    }
    return null;
  }

  Future<void> applyAutostart() async {
    final ( _, enabled, minimized) = await loadDesktopSettings();
    final file = File(p.join(Platform.environment['HOME'] ?? Directory.current.path, '.config', 'autostart',
        'packagebuddy-redux.desktop'));
    if (!enabled) {
      if (await file.exists()) await file.delete();
      return;
    }
    await file.parent.create(recursive: true);
    final exe = Platform.resolvedExecutable;
    final exec = minimized ? '"$exe" --minimized' : '"$exe"';
    await file.writeAsString('''
[Desktop Entry]
Type=Application
Name=Package Buddy Redux
Comment=Track your packages with your own Package Buddy Redux server
Exec=$exec
Icon=net.packagebuddy.selfhosted.packagebuddy
Terminal=false
Categories=Utility;Office;
X-GNOME-Autostart-enabled=true
StartupNotify=false
''');
  }

  @override
  void onWindowClose() {
    loadDesktopSettings().then((s) async {
      if (s.$1) {
        await windowManager.hide();
      } else {
        await quit();
      }
    });
  }

  @override
  void onTrayIconMouseDown() {
    // Left-click: open the window. On some desktops this also opens the menu.
    show();
  }

  @override
  void onTrayIconRightMouseDown() {
    trayManager.popUpContextMenu();
  }

  @override
  void onTrayMenuItemClick(MenuItem item) async {
    switch (item.key) {
      case 'open':
        await show();
      case 'check':
        await show();
        await checkForUpdates();
      case 'quit':
        await quit();
    }
  }
}

class DesktopSettings extends StatefulWidget {
  const DesktopSettings({super.key});
  @override
  State<DesktopSettings> createState() => _DesktopSettingsState();
}

class _DesktopSettingsState extends State<DesktopSettings> {
  bool closeToTray = true, autostart = true, startMinimized = true, loaded = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final s = await loadDesktopSettings();
    if (mounted) {
      setState(() {
        closeToTray = s.$1;
        autostart = s.$2;
        startMinimized = s.$3;
        loaded = true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!desktopSupported || !loaded) return const SizedBox.shrink();
    return Column(children: [
      const SectionHeader('Desktop'),
      SwitchListTile(
        secondary: const Icon(Icons.inventory_2_outlined),
        title: const Text('Close the window to the tray'),
        subtitle: const Text('The app stays running and can still notify you about packages'),
        value: closeToTray,
        onChanged: (v) async {
          await saveDesktopSettings(closeToTray: v);
          _load();
        },
      ),
      SwitchListTile(
        secondary: const Icon(Icons.login),
        title: const Text('Start at login'),
        subtitle: const Text('Launch Package Buddy Redux when you sign in to the computer'),
        value: autostart,
        onChanged: (v) async {
          await saveDesktopSettings(autostart: v);
          _load();
        },
      ),
      SwitchListTile(
        secondary: const Icon(Icons.visibility_off_outlined),
        title: const Text('Start minimized to the tray'),
        subtitle: const Text('Only when the app starts with the computer, not when you open it yourself'),
        value: startMinimized,
        onChanged: autostart
            ? (v) async {
                await saveDesktopSettings(startMinimized: v);
                _load();
              }
            : null,
      ),
    ]);
  }
}
