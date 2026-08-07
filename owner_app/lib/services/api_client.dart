import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/app_config.dart';

/// Thrown for any non-2xx response. Carries the HTTP [statusCode] so callers
/// can react to specific situations (e.g. 423 pickup lockout) with readable
/// staff-facing text instead of leaking raw error codes to the UI.
class ApiException implements Exception {
  final int statusCode;
  final String message;
  final Map<String, dynamic>? body;

  ApiException(this.statusCode, this.message, {this.body});

  @override
  String toString() => 'ApiException($statusCode): $message';
}

const String _tokenKey = 'gusto_owner_access_token';

/// Thin HTTP wrapper that transparently attaches the stored Bearer token to
/// every request (the "token interceptor") and decodes JSON responses.
class ApiClient {
  final http.Client _http;

  ApiClient({http.Client? httpClient}) : _http = httpClient ?? http.Client();

  // --- token persistence ---------------------------------------------------

  Future<void> saveToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);
  }

  Future<String?> readToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_tokenKey);
  }

  Future<void> clearToken() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
  }

  // --- header assembly (interceptor) ---------------------------------------

  Future<Map<String, String>> _headers({bool json = true}) async {
    final token = await readToken();
    return {
      if (json) 'Content-Type': 'application/json',
      'Accept': 'application/json',
      if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
    };
  }

  Uri _uri(String path) => Uri.parse('${AppConfig.baseUrl}$path');

  // --- verbs ---------------------------------------------------------------

  Future<dynamic> get(String path) async {
    final res = await _http.get(_uri(path), headers: await _headers());
    return _decode(res);
  }

  Future<dynamic> post(String path, {Object? body}) async {
    final res = await _http.post(
      _uri(path),
      headers: await _headers(),
      body: body == null ? null : jsonEncode(body),
    );
    return _decode(res);
  }

  Future<dynamic> put(String path, {Object? body}) async {
    final res = await _http.put(
      _uri(path),
      headers: await _headers(),
      body: body == null ? null : jsonEncode(body),
    );
    return _decode(res);
  }

  Future<dynamic> patch(String path, {Object? body}) async {
    final res = await _http.patch(
      _uri(path),
      headers: await _headers(),
      body: body == null ? null : jsonEncode(body),
    );
    return _decode(res);
  }

  Future<dynamic> delete(String path) async {
    final res = await _http.delete(_uri(path), headers: await _headers());
    return _decode(res);
  }

  /// Sends an OAuth2 form-encoded POST (used by the staff login endpoint).
  Future<dynamic> postForm(String path, Map<String, String> fields) async {
    final res = await _http.post(
      _uri(path),
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
      },
      body: fields,
    );
    return _decode(res);
  }

  // --- response handling ---------------------------------------------------

  dynamic _decode(http.Response res) {
    final isJson = (res.headers['content-type'] ?? '').contains('json');
    dynamic parsed;
    if (res.body.isNotEmpty && isJson) {
      try {
        parsed = jsonDecode(res.body);
      } catch (_) {
        parsed = null;
      }
    }

    if (res.statusCode >= 200 && res.statusCode < 300) {
      return parsed;
    }

    final detail = parsed is Map<String, dynamic>
        ? (parsed['detail']?.toString() ?? parsed.toString())
        : (res.body.isNotEmpty ? res.body : 'Request failed');

    throw ApiException(
      res.statusCode,
      detail,
      body: parsed is Map<String, dynamic> ? parsed : null,
    );
  }
}
