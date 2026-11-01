// App-wide state: server URL, login token, theme. Saved with shared_preferences.
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'models.dart';
import 'notify.dart';

class AppState extends ChangeNotifier {
  late SharedPreferences _prefs;
  late Api api;
  bool ready = false;
  UserInfo? user;
  ThemeMode themeMode = ThemeMode.dark; // dark by default
  String serverUrl = '';

  /// Bumped whenever packages change, so every list reloads.
  final ValueNotifier<int> revision = ValueNotifier(0);
  void packagesChanged() => revision.value++;

  /// On the web the app is served by the server itself, so it talks to its own origin.
  static String get sameOrigin {
    final u = Uri.base.removeFragment().replace(query: '');
    var s = u.resolve('.').toString();
    if (s.endsWith('?')) s = s.substring(0, s.length - 1);
    return s.endsWith('/') ? s.substring(0, s.length - 1) : s;
  }

  bool get needsServerUrl => !kIsWeb;

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
    themeMode = switch (_prefs.getString('theme')) {
      'light' => ThemeMode.light,
      'system' => ThemeMode.system,
      _ => ThemeMode.dark,
    };
    serverUrl = _prefs.getString('server_url') ?? (kIsWeb ? sameOrigin : '');
    api = Api(baseUrl: serverUrl, token: _prefs.getString('token'));
    if (api.token != null && serverUrl.isNotEmpty) {
      try {
        user = await api.me();
      } on ApiException catch (e) {
        if (e.unauthorized) await _clearToken();
      } catch (_) {
        // offline: keep the token, the login screen will offer to retry
      }
    }
    ready = true;
    notifyListeners();
  }

  Future<void> setTheme(ThemeMode m) async {
    themeMode = m;
    await _prefs.setString('theme', m.name);
    notifyListeners();
  }

  Future<void> setServerUrl(String url) async {
    var u = url.trim();
    while (u.endsWith('/')) {
      u = u.substring(0, u.length - 1);
    }
    if (u.isNotEmpty && !u.startsWith('http')) u = 'http://$u';
    serverUrl = u;
    api.baseUrl = u;
    await _prefs.setString('server_url', u);
    notifyListeners();
  }

  Future<void> login(String username, String password) async {
    final device = kIsWeb ? 'Web browser' : 'Package Buddy Redux app (${defaultTargetPlatform.name})';
    final token = await api.login(username, password, device);
    await _prefs.setString('token', token);
    user = await api.me();
    await _prefs.remove(kNotifyCursor); // new session: start notifications from now
    if (notificationsSupported) checkForUpdates(refreshFirst: false);
    notifyListeners();
  }

  Future<void> logout() async {
    await api.logout();
    await _clearToken();
    notifyListeners();
  }

  Future<void> _clearToken() async {
    api.token = null;
    user = null;
    await _prefs.remove('token');
  }

  /// Called when any request comes back 401 (token expired or revoked).
  Future<void> sessionExpired() async {
    await _clearToken();
    notifyListeners();
  }
}

final app = AppState();
