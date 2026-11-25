import 'dart:io';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'version.dart';

enum InstallResult { okRestart, openedInstaller, needInstallPermission, openedPage, failed }

const _install = MethodChannel('packagebuddy/install');

Future<InstallResult> downloadAndInstall(AppRelease release, {required void Function(double? p) onProgress}) async {
  final url = Platform.isAndroid ? release.apkUrl : release.debUrl;
  final name = Platform.isAndroid ? release.apkName : release.debName;
  if (url == null || name == null) return InstallResult.openedPage;
  final dir = await getTemporaryDirectory();
  final file = File(p.join(dir.path, name));
  final client = http.Client();
  try {
    final req = http.Request('GET', Uri.parse(url));
    req.headers['User-Agent'] = 'PackageBuddyRedux/$kClientVersion';
    final res = await client.send(req);
    if (res.statusCode != 200) return InstallResult.failed;
    final total = res.contentLength ?? 0;
    final sink = file.openWrite();
    var got = 0;
    await for (final chunk in res.stream) {
      sink.add(chunk);
      got += chunk.length;
      if (total > 0) onProgress(got / total);
    }
    await sink.close();
    onProgress(null);
    if (Platform.isAndroid) return await _installApk(file.path);
    if (Platform.isLinux) return await _installDeb(file.path);
    return InstallResult.openedPage;
  } finally {
    client.close();
  }
}

Future<InstallResult> _installApk(String path) async {
  try {
    final can = await _install.invokeMethod<bool>('canInstall') ?? false;
    if (!can) {
      await _install.invokeMethod('requestInstallPermission');
      return InstallResult.needInstallPermission;
    }
    await _install.invokeMethod('installApk', path);
    return InstallResult.openedInstaller;
  } catch (_) {
    return InstallResult.failed;
  }
}

Future<InstallResult> _installDeb(String path) async {
  final pkexec = await _which('pkexec');
  if (pkexec == null) return InstallResult.openedPage;
  final r = await Process.run(pkexec, ['apt-get', 'install', '-y', path], runInShell: false);
  if (r.exitCode == 0) return InstallResult.okRestart;
  return InstallResult.failed;
}

Future<String?> _which(String name) async {
  final r = await Process.run('which', [name]);
  if (r.exitCode != 0) return null;
  final s = (r.stdout as String).trim();
  return s.isEmpty ? null : s;
}

Future<void> restartApp() async {
  final exe = Platform.resolvedExecutable;
  await Process.start(exe, const [], mode: ProcessStartMode.detached, environment: Map.of(Platform.environment));
  exit(0);
}
