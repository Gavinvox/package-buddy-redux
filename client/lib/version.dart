// Keep in sync with client/pubspec.yaml (version: x.y.z+n).
const kClientVersion = '0.4.0';
const kGithubRepo = 'Gavinvox/package-buddy-redux';
const kGithubReleasesUrl = 'https://github.com/Gavinvox/package-buddy-redux/releases/latest';
const kGithubLatestApi = 'https://api.github.com/repos/Gavinvox/package-buddy-redux/releases/latest';

/// Stable release asset names the in-app updater looks for.
const kApkAssetName = 'packagebuddy-redux-arm64.apk';
const kDebAssetPattern = r'^packagebuddy-redux_.*_amd64\.deb$';
const kServerTarballName = 'packagebuddy-server.tar.gz';


class AppRelease {
  AppRelease({required this.version, required this.notes, required this.htmlUrl, this.apkUrl, this.debUrl, this.apkName, this.debName});
  final String version;
  final String notes;
  final String htmlUrl;
  final String? apkUrl;
  final String? debUrl;
  final String? apkName;
  final String? debName;
}
