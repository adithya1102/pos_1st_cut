import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/app_config.dart';

/// Thrown for any non-2xx response or transport failure.
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});
  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

/// Thin HTTP wrapper that behaves like an interceptor: it holds the bearer
/// token, attaches it to every request, and centralizes JSON decoding.
class ApiClient {
  ApiClient({http.Client? client}) : _client = client ?? http.Client();

  static const _tokenKey = 'carevo_access_token';

  final http.Client _client;
  String? _token;

  String? get token => _token;
  bool get isAuthenticated => _token != null && _token!.isNotEmpty;

  /// Restore a persisted token at startup.
  Future<void> loadToken() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString(_tokenKey);
  }

  Future<void> setToken(String token) async {
    _token = token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);
  }

  Future<void> clearToken() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
  }

  Map<String, String> _headers() => {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        if (isAuthenticated) 'Authorization': 'Bearer $_token',
      };

  Uri _uri(String path, [Map<String, dynamic>? query]) {
    final base = AppConfig.baseUrl.endsWith('/')
        ? AppConfig.baseUrl.substring(0, AppConfig.baseUrl.length - 1)
        : AppConfig.baseUrl;
    final normalized = path.startsWith('/') ? path : '/$path';
    final qp = <String, String>{};
    if (query != null) {
      query.forEach((k, v) {
        if (v != null) qp[k] = v.toString();
      });
    }
    return Uri.parse('$base$normalized').replace(
      queryParameters: qp.isEmpty ? null : qp,
    );
  }

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) async {
    return _send(() =>
        _client.get(_uri(path, query), headers: _headers()).timeout(AppConfig.requestTimeout));
  }

  Future<dynamic> post(String path, {Object? body}) async {
    return _send(() => _client
        .post(_uri(path), headers: _headers(), body: jsonEncode(body ?? {}))
        .timeout(AppConfig.requestTimeout));
  }

  Future<dynamic> delete(String path) async {
    return _send(() =>
        _client.delete(_uri(path), headers: _headers()).timeout(AppConfig.requestTimeout));
  }

  Future<dynamic> patch(String path, {Object? body}) async {
    return _send(() => _client
        .patch(_uri(path), headers: _headers(), body: jsonEncode(body ?? {}))
        .timeout(AppConfig.requestTimeout));
  }

  Future<dynamic> _send(Future<http.Response> Function() run) async {
    http.Response res;
    try {
      res = await run();
    } catch (e) {
      throw ApiException('Network error: unable to reach server. ($e)');
    }

    final body = res.body.isEmpty ? null : _tryDecode(res.body);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return body;
    }

    final detail = body is Map && body['detail'] != null
        ? body['detail'].toString()
        : (body is Map && body['message'] != null
            ? body['message'].toString()
            : 'Request failed (${res.statusCode}).');
    throw ApiException(detail, statusCode: res.statusCode);
  }

  dynamic _tryDecode(String s) {
    try {
      return jsonDecode(s);
    } catch (_) {
      return s;
    }
  }

  void dispose() => _client.close();
}
