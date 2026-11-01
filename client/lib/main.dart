// Package Buddy Redux client: one code base for web, Android and Linux desktop.
import 'package:flutter/material.dart';

import 'screens/home.dart';
import 'screens/login.dart';
import 'notify.dart';
import 'screens/detail.dart';
import 'state.dart';
import 'theme.dart';
import 'widgets/common.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  app.init();
  onOpenPackage = _openPackage;
  initNotifications().then((_) {
    final id = pendingOpenPackage;
    pendingOpenPackage = null;
    if (id != null) _openPackage(id);
  });
  runApp(const PackageBuddyApp());
}

void _openPackage(int id) {
  void go() {
    final nav = navigatorKey.currentState;
    if (nav == null || !app.ready || app.user == null) {
      Future.delayed(const Duration(milliseconds: 300), go);
      return;
    }
    nav.push(MaterialPageRoute(builder: (_) => DetailScreen(packageId: id)));
  }
  go();
}

class PackageBuddyApp extends StatelessWidget {
  const PackageBuddyApp({super.key});
  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: app,
      builder: (context, _) => MaterialApp(
        title: 'Package Buddy Redux',
        navigatorKey: navigatorKey,
        debugShowCheckedModeBanner: false,
        theme: buildTheme(Brightness.light),
        darkTheme: buildTheme(Brightness.dark),
        themeMode: app.themeMode,
        home: !app.ready
            ? const Scaffold(body: Center(child: AppLogo(size: 150)))
            : app.user == null
                ? const LoginScreen()
                : HomeScreen(key: ValueKey(app.user!.id), initialTab: _initialTab()),
      ),
    );
  }

  /// '#history' or '#sending' in the address opens that tab (handy for bookmarks).
  int _initialTab() {
    final f = Uri.base.fragment;
    return f.contains('history') ? 2 : (f.contains('sending') ? 1 : 0);
  }
}
