// REST client for the Package Buddy server (/api/v1).
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'models.dart';

class ApiException implements Exception {
  ApiException(this.status, this.message);
  final int status;
  final String message;
  bool get unauthorized => status == 401;
  @override
  String toString() => message;
}

class Api {
  Api({required this.baseUrl, this.token});

  String baseUrl; // e.g. "" (same origin on web) or "http://192.168.1.50:8765"
  String? token;
  final http.Client _http = http.Client();

  Uri _u(String path, [Map<String, dynamic>? q]) {
    final base = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
    final params = q?.map((k, v) => MapEntry(k, '$v'))
      ?..removeWhere((k, v) => v == 'null' || v.isEmpty);
    return Uri.parse('$base/api/v1$path').replace(queryParameters: (params?.isEmpty ?? true) ? null : params);
  }

  Map<String, String> get _headers => {
        'Accept': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  dynamic _decode(http.Response r) {
    final text = utf8.decode(r.bodyBytes);
    if (r.statusCode >= 200 && r.statusCode < 300) {
      return text.isEmpty ? null : jsonDecode(text);
    }
    var msg = 'Server error ${r.statusCode}';
    try {
      final j = jsonDecode(text);
      final d = j is Map ? j['detail'] : null;
      if (d is String) {
        msg = d;
      } else if (d is List && d.isNotEmpty) {
        msg = d.map((e) => e is Map ? '${(e['loc'] as List?)?.last ?? ''}: ${e['msg']}' : '$e').join('\n');
      }
    } catch (_) {}
    throw ApiException(r.statusCode, msg);
  }

  Future<dynamic> get(String path, [Map<String, dynamic>? q]) async =>
      _decode(await _http.get(_u(path, q), headers: _headers));

  Future<dynamic> post(String path, [Object? body, Map<String, dynamic>? q]) async => _decode(await _http.post(
      _u(path, q),
      headers: {..._headers, 'Content-Type': 'application/json'},
      body: body == null ? null : jsonEncode(body)));

  Future<dynamic> patch(String path, Object body) async => _decode(await _http.patch(_u(path),
      headers: {..._headers, 'Content-Type': 'application/json'}, body: jsonEncode(body)));

  Future<dynamic> delete(String path) async => _decode(await _http.delete(_u(path), headers: _headers));

  Future<dynamic> upload(String path, String field, String filename, Uint8List bytes, Map<String, dynamic> q) async {
    final req = http.MultipartRequest('POST', _u(path, q))
      ..headers.addAll(_headers)
      ..files.add(http.MultipartFile.fromBytes(field, bytes, filename: filename));
    final streamed = await _http.send(req);
    return _decode(await http.Response.fromStream(streamed));
  }

  // ---- auth
  Future<Map<String, dynamic>> health() async => (await get('/health')) as Map<String, dynamic>;

  Future<String> login(String user, String pass, String device) async {
    final j = await post('/auth/login', {'username': user, 'password': pass, 'device_name': device});
    token = j['token'] as String;
    return token!;
  }

  Future<void> logout() async {
    try {
      await post('/auth/logout');
    } catch (_) {}
    token = null;
  }

  Future<UserInfo> me() async => UserInfo.fromJson(await get('/me'));

  Future<void> changePassword(String current, String next) =>
      post('/me/password', {'current_password': current, 'new_password': next});

  // ---- packages
  Future<List<Pkg>> packages({required String view, String? direction}) async {
    final j = await get('/packages', {'view': view, 'direction': direction});
    return (j as List).map((e) => Pkg.fromJson(e)).toList();
  }

  Future<Pkg> package(int id) async => Pkg.fromJson(await get('/packages/$id'));

  Future<(Pkg, String)> addPackage(
      {required String number, Object? carrier, String description = '', String direction = 'receiving', bool track = true}) async {
    final j = await post('/packages', {
      'tracking_number': number,
      'carrier': carrier,
      'description': description,
      'direction': direction,
      'track': track,
    });
    return (Pkg.fromJson(j['package']), j['outcome'] as String);
  }

  Future<Pkg> updatePackage(int id, Map<String, dynamic> changes) async =>
      Pkg.fromJson(await patch('/packages/$id', changes));

  Future<void> deletePackage(int id) => delete('/packages/$id');

  Future<Pkg> refreshPackage(int id) async => Pkg.fromJson(await post('/packages/$id/refresh'));

  Future<Map<String, dynamic>> refreshAll() async => (await post('/packages/refresh')) as Map<String, dynamic>;

  Future<(Pkg, String)> startTracking(int id) async {
    final j = await post('/packages/$id/track');
    return (Pkg.fromJson(j['package']), j['outcome'] as String);
  }

  // ---- carriers
  Future<List<Carrier>> carriers(String q, {bool all = false}) async {
    final j = await get('/carriers', {'q': q, 'all': all, 'limit': 80});
    return (j as List).map((e) => Carrier.fromJson(e)).toList();
  }

  Future<Detection> detect(String number) async => Detection.fromJson(await get('/carriers/detect', {'number': number}));

  // ---- import/export
  /// Old-app backup XML, packagebuddy_db, or an adb backup (.ab); the server detects which.
  Future<Map<String, dynamic>> importFile(
      {required String filename, required Uint8List bytes, required bool trackActive, required bool dryRun}) async {
    final j = await upload('/import', 'file', filename, bytes, {'track_active': trackActive, 'dry_run': dryRun});
    return (j as Map).cast<String, dynamic>();
  }

  Future<Uint8List> exportJson() async {
    final r = await _http.get(_u('/export'), headers: _headers);
    if (r.statusCode != 200) _decode(r);
    return r.bodyBytes;
  }

  // ---- admin
  Future<List<UserInfo>> users() async => ((await get('/admin/users')) as List).map((e) => UserInfo.fromJson(e)).toList();
  Future<void> createUser(String username, String password, bool isAdmin, int? limit) => post('/admin/users',
      {'username': username, 'password': password, 'is_admin': isAdmin, 'monthly_new_limit': limit});
  Future<void> patchUser(int id, Map<String, dynamic> body) => patch('/admin/users/$id', body);
  Future<void> deleteUser(int id) => delete('/admin/users/$id');
  Future<Map<String, dynamic>> quota() async => (await get('/admin/quota')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> patchSettings(Map<String, dynamic> body) async =>
      (await patch('/admin/settings', body)) as Map<String, dynamic>;
  Future<List<Pkg>> approvals() async => ((await get('/admin/approvals')) as List).map((e) => Pkg.fromJson(e)).toList();
  Future<String> approve(int id) async => (await post('/admin/approvals/$id/approve'))['outcome'] as String;
  Future<void> reject(int id) => post('/admin/approvals/$id/reject');
  Future<Map<String, dynamic>> pollNow() async => (await post('/admin/poll-now')) as Map<String, dynamic>;
}
