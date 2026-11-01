import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api.dart';
import '../state.dart';

void toast(BuildContext context, String msg) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(msg)));
}

/// Shows an error; logs out if the session has expired.
void showError(BuildContext context, Object e) {
  if (e is ApiException && e.unauthorized) {
    app.sessionExpired();
    return;
  }
  final msg = e is ApiException ? e.message : 'Could not reach the server ($e)';
  if (context.mounted) toast(context, msg);
}

Future<bool> confirm(BuildContext context, String title, String body, {String ok = 'OK', bool danger = false}) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(title),
      content: Text(body),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
        FilledButton(
          style: danger ? FilledButton.styleFrom(backgroundColor: Theme.of(c).colorScheme.error) : null,
          onPressed: () => Navigator.pop(c, true),
          child: Text(ok),
        ),
      ],
    ),
  );
  return r ?? false;
}

Future<void> openUrl(BuildContext context, String url) async {
  final ok = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication, webOnlyWindowName: '_blank');
  if (!ok && context.mounted) toast(context, 'Could not open $url');
}

class AppLogo extends StatelessWidget {
  const AppLogo({super.key, this.size = 32});
  final double size;
  @override
  Widget build(BuildContext context) => Image.asset('assets/icon/logo.png',
      width: size, height: size, fit: BoxFit.contain, filterQuality: FilterQuality.high, semanticLabel: 'Package Buddy Redux');
}

/// Content width limit so forms don't stretch across a desktop screen.
class Constrained extends StatelessWidget {
  const Constrained({super.key, required this.child, this.maxWidth = 720});
  final Widget child;
  final double maxWidth;
  @override
  Widget build(BuildContext context) =>
      Align(alignment: Alignment.topCenter, child: ConstrainedBox(constraints: BoxConstraints(maxWidth: maxWidth), child: child));
}

class SectionHeader extends StatelessWidget {
  const SectionHeader(this.text, {super.key});
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme.primary;
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 20, 16, 6),
      padding: const EdgeInsets.only(bottom: 4),
      decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.withValues(alpha: 0.6), width: 1.5))),
      child: Text(text.toUpperCase(),
          style: TextStyle(fontFamily: 'RobotoCondensed', fontWeight: FontWeight.w700, color: c, letterSpacing: 0.6)),
    );
  }
}
