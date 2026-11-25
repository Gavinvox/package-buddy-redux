// In-app update check against GitHub Releases.
import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'updater_env_stub.dart' if (dart.library.io) 'updater_env_io.dart' as env;
import 'updater_install_stub.dart' if (dart.library.io) 'updater_install.dart' as install;
import 'version.dart';
import 'widgets/common.dart';

const kUpdateCheckEnabled = 'update_check_enabled';
const kSkippedVersion = 'update_skipped_version';
const kLastUpdateCheck = 'update_last_check_ms';

bool get updatesSupported => !kIsWeb && (defaultTargetPlatform == TargetPlatform.android || defaultTargetPlatform == TargetPlatform.linux);

/// Compare dotted versions like 0.4.0 / v0.3.0. Returns true if [latest] is newer than [current].
bool isNewerVersion(String latest, String current) {
  List<int> parts(String v) {
    final s = v.trim();
    final t = s.startsWith('v') || s.startsWith('V') ? s.substring(1) : s;
    final nums = t.split(RegExp(r'[^0-9]+')).where((e) => e.isNotEmpty).map(int.parse).toList();
    while (nums.length < 3) {
      nums.add(0);
    }
    return nums;
  }

  final a = parts(latest);
  final b = parts(current);
  for (var i = 0; i < 3; i++) {
    if (a[i] != b[i]) return a[i] > b[i];
  }
  return false;
}

Future<bool> loadUpdateCheckEnabled() async {
  final p = await SharedPreferences.getInstance();
  return p.getBool(kUpdateCheckEnabled) ?? true;
}

Future<void> saveUpdateCheckEnabled(bool v) async {
  final p = await SharedPreferences.getInstance();
  await p.setBool(kUpdateCheckEnabled, v);
}

Future<AppRelease?> fetchLatestRelease() async {
  final r = await http.get(Uri.parse(kGithubLatestApi), headers: {
    'Accept': 'application/vnd.github+json',
    'User-Agent': 'PackageBuddyRedux/$kClientVersion',
  }).timeout(const Duration(seconds: 20));
  if (r.statusCode != 200) return null;
  final j = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
  final tag = '${j['tag_name'] ?? j['name'] ?? ''}';
  final version = tag.startsWith('v') || tag.startsWith('V') ? tag.substring(1) : tag;
  String? apkUrl, apkName, debUrl, debName;
  for (final a in (j['assets'] as List? ?? const [])) {
    if (a is! Map) continue;
    final name = '${a['name'] ?? ''}';
    final url = '${a['browser_download_url'] ?? ''}';
    if (url.isEmpty) continue;
    if (name == kApkAssetName || (name.startsWith('packagebuddy-redux-arm64') && name.endsWith('.apk'))) {
      apkUrl = url;
      apkName = name;
    }
    if (RegExp(kDebAssetPattern).hasMatch(name)) {
      debUrl = url;
      debName = name;
    }
  }
  return AppRelease(
    version: version,
    notes: (j['body'] as String?)?.trim() ?? '',
    htmlUrl: '${j['html_url'] ?? kGithubReleasesUrl}',
    apkUrl: apkUrl,
    apkName: apkName,
    debUrl: debUrl,
    debName: debName,
  );
}

/// Called shortly after the home screen is shown. Checks at most once a day.
Future<void> maybeCheckForAppUpdates(BuildContext context, {bool force = false}) async {
  if (!updatesSupported) return;
  if (env.envValue('PB_FAKE_UPDATE') == '1') {
    if (context.mounted) {
      await showUpdateDialog(
          context,
          AppRelease(
            version: '9.9.9',
            notes: 'This is a sample update prompt (PB_FAKE_UPDATE).',
            htmlUrl: kGithubReleasesUrl,
          ));
    }
    return;
  }
  if (!force && !await loadUpdateCheckEnabled()) return;
  final prefs = await SharedPreferences.getInstance();
  if (!force) {
    final last = prefs.getInt(kLastUpdateCheck) ?? 0;
    if (DateTime.now().millisecondsSinceEpoch - last < const Duration(days: 1).inMilliseconds) return;
  }
  try {
    final latest = await fetchLatestRelease();
    await prefs.setInt(kLastUpdateCheck, DateTime.now().millisecondsSinceEpoch);
    if (latest == null || !isNewerVersion(latest.version, kClientVersion)) {
      if (force && context.mounted) toast(context, 'You are up to date (v$kClientVersion).');
      return;
    }
    if (!force && prefs.getString(kSkippedVersion) == latest.version) return;
    if (context.mounted) await showUpdateDialog(context, latest);
  } catch (_) {
    if (force && context.mounted) toast(context, 'Could not check for updates.');
  }
}

Future<void> showUpdateDialog(BuildContext context, AppRelease release) async {
  final action = await showDialog<String>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text('Version ${release.version} is available'),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('You have v$kClientVersion. A newer release is on GitHub.', style: Theme.of(c).textTheme.bodyMedium),
            if (release.notes.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(release.notes, style: Theme.of(c).textTheme.bodySmall),
            ],
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, 'skip'), child: const Text('Skip this version')),
        TextButton(onPressed: () => Navigator.pop(c, 'later'), child: const Text('Later')),
        FilledButton(onPressed: () => Navigator.pop(c, 'now'), child: const Text('Update now')),
      ],
    ),
  );
  if (action == 'skip') {
    final p = await SharedPreferences.getInstance();
    await p.setString(kSkippedVersion, release.version);
    return;
  }
  if (action != 'now' || !context.mounted) return;
  await installAndPrompt(context, release);
}

Future<void> installAndPrompt(BuildContext context, AppRelease release) async {
  if ((defaultTargetPlatform == TargetPlatform.android ? release.apkUrl : release.debUrl) == null) {
    await openUrl(context, release.htmlUrl);
    return;
  }
  final progress = ValueNotifier<double?>(0);
  var closed = false;
  showDialog(
    context: context,
    barrierDismissible: false,
    builder: (c) => PopScope(
      canPop: false,
      child: AlertDialog(
        title: const Text('Downloading update'),
        content: ValueListenableBuilder<double?>(
          valueListenable: progress,
          builder: (context, v, child) => Column(mainAxisSize: MainAxisSize.min, children: [
            LinearProgressIndicator(value: v),
            const SizedBox(height: 12),
            Text(v == null ? 'Installing…' : '${((v) * 100).clamp(0, 100).toStringAsFixed(0)}%'),
          ]),
        ),
      ),
    ),
  );
  try {
    final result = await install.downloadAndInstall(
      release,
      onProgress: (p) => progress.value = p,
    );
    if (context.mounted && !closed) {
      Navigator.of(context, rootNavigator: true).pop();
      closed = true;
    }
    if (!context.mounted) return;
    if (result == install.InstallResult.okRestart) {
      final restart = await confirm(context, 'Update installed', 'Restart Package Buddy Redux to use the new version.',
          ok: 'Restart now', cancel: 'Later');
      if (restart) await install.restartApp();
    } else if (result == install.InstallResult.openedInstaller) {
      toast(context, 'Follow the installer to finish the update.');
    } else if (result == install.InstallResult.needInstallPermission) {
      toast(context, 'Allow this app to install updates, then try again.');
    } else if (result == install.InstallResult.openedPage) {
      await openUrl(context, release.htmlUrl);
    } else if (result == install.InstallResult.failed) {
      if (await confirm(context, 'Could not install the update', 'Open the release page instead?', ok: 'Open page', cancel: 'Cancel') &&
          context.mounted) {
        await openUrl(context, release.htmlUrl);
      }
    }
  } catch (_) {
    if (context.mounted && !closed) {
      Navigator.of(context, rootNavigator: true).pop();
      if (await confirm(context, 'Could not download the update', 'Open the release page instead?', ok: 'Open page', cancel: 'Cancel') &&
          context.mounted) {
        await openUrl(context, release.htmlUrl);
      }
    }
  }
}

class UpdateSettings extends StatefulWidget {
  const UpdateSettings({super.key});
  @override
  State<UpdateSettings> createState() => _UpdateSettingsState();
}

class _UpdateSettingsState extends State<UpdateSettings> {
  bool enabled = true, loaded = false, checking = false;

  @override
  void initState() {
    super.initState();
    loadUpdateCheckEnabled().then((v) {
      if (mounted) setState(() { enabled = v; loaded = true; });
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!updatesSupported || !loaded) return const SizedBox.shrink();
    return Column(children: [
      const SectionHeader('Updates'),
      SwitchListTile(
        secondary: const Icon(Icons.system_update_alt),
        title: const Text('Check for updates'),
        subtitle: const Text('Look on GitHub at startup and once a day, and offer to install a new release'),
        value: enabled,
        onChanged: (v) async {
          await saveUpdateCheckEnabled(v);
          setState(() => enabled = v);
        },
      ),
      ListTile(
        leading: const Icon(Icons.refresh),
        title: const Text('Check for updates'),
        subtitle: Text('Current version is $kClientVersion'),
        trailing: checking ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) : null,
        onTap: checking
            ? null
            : () async {
                setState(() => checking = true);
                await maybeCheckForAppUpdates(context, force: true);
                if (mounted) setState(() => checking = false);
              },
      ),
    ]);
  }
}
