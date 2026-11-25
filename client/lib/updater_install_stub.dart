import 'version.dart';

enum InstallResult { okRestart, openedInstaller, needInstallPermission, openedPage, failed }

Future<InstallResult> downloadAndInstall(AppRelease release, {required void Function(double? p) onProgress}) async =>
    InstallResult.openedPage;

Future<void> restartApp() async {}
