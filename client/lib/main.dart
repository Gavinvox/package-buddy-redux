// Package Buddy Redux client: one code base for web, Android and Linux desktop.
import 'package:flutter/material.dart';

import 'screens/home.dart';
import 'screens/login.dart';
import 'desktop.dart';
import 'notify.dart';
import 'screens/detail.dart';
import 'state.dart';
import 'theme.dart';
import 'updater.dart';
import 'widgets/common.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await app.init();
  onOpenPackage = _openPackage;
  await initNotifications();
  await initDesktop();
  final id = pendingOpenPackage;
  pendingOpenPackage = null;
  runApp(const PackageBuddyApp());
  if (id != null) _openPackage(id);
}

void _openPackage(int id) {
  showDesktopWindow();
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
                : StartupHooks(child: HomeScreen(key: ValueKey(app.user!.id), initialTab: _initialTab())),
      ),
    );
  }

  /// '#history' or '#sending' in the address opens that tab (handy for bookmarks).
  int _initialTab() {
    final f = Uri.base.fragment;
    return f.contains('history') ? 2 : (f.contains('sending') ? 1 : 0);
  }
}


/// Runs once after a successful login or when a saved session is restored:
/// notification / battery prompts, then the daily update check.
class StartupHooks extends StatefulWidget {
  const StartupHooks({super.key, required this.child});
  final Widget child;
  @override
  State<StartupHooks> createState() => _StartupHooksState();
}

class _StartupHooksState extends State<StartupHooks> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _run());
  }

  Future<void> _run() async {
    await runNotificationOnboarding(context);
    if (!mounted) return;
    await Future<void>.delayed(const Duration(seconds: 1));
    if (!mounted) return;
    await maybeCheckForAppUpdates(context);
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
