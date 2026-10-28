import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
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

  /// The human-readable part of a structured `detail`, or null.
  ///
  /// FastAPI's `detail` is NOT always a string. The backend raises structured
  /// details for exactly the cases an owner most needs explained —
  /// CASHFREE_LOCKED, UPI_ATTESTATION_REQUIRED, PAYMENT_NOT_RECORDED — and
  /// [message] is built by `.toString()`ing whatever `detail` was, which for a
  /// Map renders Dart's debug form straight into the UI:
  ///
  ///   {error: CASHFREE_LOCKED, message: Cashfree is currently unavailable…}
  ///
  /// Every structured detail carries a `message` written for a person, so that
  /// is preferred; `error` is the fallback for one that has none, and is at
  /// least a short code rather than a dump. A plain string detail comes back
  /// unchanged, which is the common case.
  ///
  /// customer_app has carried the same helper since the ITEM_SOLD_OUT work
  /// (its api_client._detailMessage); this is the owner-side twin.
  String? get serverMessage {
    final detail = body?['detail'];
    if (detail is Map) {
      final msg = detail['message'];
      if (msg != null && msg.toString().trim().isNotEmpty) {
        return msg.toString();
      }
      final code = detail['error'];
      if (code != null && code.toString().trim().isNotEmpty) {
        return code.toString();
      }
      // A Map with neither key is not worth dumping at the owner.
      return null;
    }
    if (detail is String && detail.trim().isNotEmpty) return detail;
    // FastAPI validation errors arrive as a LIST of per-field objects whose
    // prose is framework-speak ("field required"), so they are not rendered.
    if (detail is List) return null;
    return message.trim().isEmpty ? null : message;
  }

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
  //
  // flutter_secure_storage, not SharedPreferences. The staff JWT is a bearer
  // credential: anything holding it IS the owner for the life of the token
  // (24h, and there is no server-side revocation). SharedPreferences is a
  // world-readable-to-the-app XML file on Android and a plist on iOS — it is
  // readable on a rooted/jailbroken device, and it is swept up by adb backup
  // and by cloud backup unless allowBackup is off. Secure storage puts it in
  // the Android Keystore / iOS Keychain instead.

  static const _secure = FlutterSecureStorage(
    // encryptedSharedPreferences uses the Keystore-backed implementation
    // rather than the legacy plaintext fallback on older Android.
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );

  Future<void> saveToken(String token) async {
    await _secure.write(key: _tokenKey, value: token);
  }

  /// Reads the token, migrating it out of SharedPreferences on first run.
  ///
  /// The migration READS THEN DELETES. Simply starting to write to the new
  /// store would leave every already-signed-in owner's token sitting in the
  /// old plaintext file forever — the exact value this change exists to get
  /// out of there — while the app looked fixed. The delete is what makes it a
  /// migration rather than a second copy.
  Future<String?> readToken() async {
    final secure = await _secure.read(key: _tokenKey);
    if (secure != null && secure.isNotEmpty) return secure;

    final prefs = await SharedPreferences.getInstance();
    final legacy = prefs.getString(_tokenKey);
    if (legacy == null || legacy.isEmpty) return null;

    // Move it: write to the Keystore first, and only then drop the plaintext
    // copy, so an interruption between the two loses nothing.
    await _secure.write(key: _tokenKey, value: legacy);
    await prefs.remove(_tokenKey);
    return legacy;
  }

  Future<void> clearToken() async {
    await _secure.delete(key: _tokenKey);
    // Also clear the legacy key, so signing out on a device that never
    // happened to call readToken() still removes the plaintext copy.
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
