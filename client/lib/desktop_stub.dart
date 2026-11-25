import 'package:flutter/widgets.dart';

const desktopSupported = false;
bool get launchedMinimized => false;

Future<void> initDesktop() async {}
Future<void> showDesktopWindow() async {}
Future<void> quitDesktop() async {}

Future<(bool closeToTray, bool autostart, bool startMinimized)> loadDesktopSettings() async =>
    (true, true, true);

Future<void> saveDesktopSettings({bool? closeToTray, bool? autostart, bool? startMinimized}) async {}

class DesktopSettings extends StatelessWidget {
  const DesktopSettings({super.key});
  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
