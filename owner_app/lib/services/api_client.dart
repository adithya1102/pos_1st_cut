import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/app_config.dart';

/// Thrown for any non-2xx response. Carries the HTTP [statusCode] so callers
/// can react to specific situations (e.g. 423 pickup lockout) with readable
/// staff-facing text instead of leaking raw error codes to the UI.
///
/// An ApiException means THE SERVER ANSWERED AND SAID NO. That is a completely
/// different situation from [NetworkException], and the two must never be
/// reported to the owner with the same words.
class ApiException implements Exception {
  final int statusCode;
  final String message;
  final Map<String, dynamic>? body;

  ApiException(this.statusCode, this.message, {this.body});

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// Thrown when the request never produced an HTTP response at all: no
/// connectivity, DNS failure, TLS handshake failure, connection refused, or it
/// timed out waiting.
///
/// Exists because collapsing this into a bare `catch (_)` is what made a
/// missing INTERNET permission look identical to a wrong password — every
/// login, right or wrong, reported "could not reach the server".
class NetworkException implements Exception {
  NetworkException(this.message, {this.timedOut = false});

  final String message;

  /// True when we waited out [ApiClient.requestTimeout] without an answer, as
  /// opposed to failing to connect at all. Renders free tier sleeps after
  /// inactivity, so this is usually a cold start rather than a dead server.
  final bool timedOut;

  @override
  String toString() => 'NetworkException: $message';
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

  /// Ceiling for a single request.
  ///
  /// Sized for Render's FREE tier, which spins the service down after ~15
  /// minutes idle and then takes 40-80s to cold start. A conventional 10-30s
  /// timeout would abort mid-wake and report a dead server that is merely
  /// booting. 90s clears the documented window with headroom; past that,
  /// something really is wrong.
  ///
  /// Previously there was NO timeout at all — a stalled request hung forever
  /// behind a spinner with no way out.
  static const Duration requestTimeout = Duration(seconds: 90);

  /// Runs one request, converting transport failures into [NetworkException]
  /// and leaving [ApiException] (a real server answer) untouched.
  ///
  /// Every verb goes through here so no call site can accidentally keep the
  /// old undifferentiated behaviour.
  Future<dynamic> _send(Future<http.Response> Function() request) async {
    try {
      return _decode(await request().timeout(requestTimeout));
    } on TimeoutException {
      throw NetworkException(
        'The server did not respond within ${requestTimeout.inSeconds}s.',
        timedOut: true,
      );
    } on SocketException catch (e) {
      // Also what a missing INTERNET permission looks like from Dart.
      throw NetworkException('Cannot reach the server (${e.osError?.message ?? 'no connection'}).');
    } on HandshakeException {
      throw NetworkException('Secure connection to the server failed.');
    } on http.ClientException catch (e) {
      throw NetworkException('Connection to the server failed (${e.message}).');
    }
  }

  // --- verbs ---------------------------------------------------------------

  Future<dynamic> get(String path) async =>
      _send(() async => _http.get(_uri(path), headers: await _headers()));

  Future<dynamic> post(String path, {Object? body}) async =>
      _send(() async => _http.post(
            _uri(path),
            headers: await _headers(),
            body: body == null ? null : jsonEncode(body),
          ));

  Future<dynamic> put(String path, {Object? body}) async =>
      _send(() async => _http.put(
            _uri(path),
            headers: await _headers(),
            body: body == null ? null : jsonEncode(body),
          ));

  Future<dynamic> patch(String path, {Object? body}) async =>
      _send(() async => _http.patch(
            _uri(path),
            headers: await _headers(),
            body: body == null ? null : jsonEncode(body),
          ));

  Future<dynamic> delete(String path) async =>
      _send(() async => _http.delete(_uri(path), headers: await _headers()));

  /// Sends an OAuth2 form-encoded POST (used by the staff login endpoint).
  Future<dynamic> postForm(String path, Map<String, String> fields) async =>
      _send(() async => _http.post(
            _uri(path),
            headers: {
              'Content-Type': 'application/x-www-form-urlencoded',
              'Accept': 'application/json',
            },
            body: fields,
          ));

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
