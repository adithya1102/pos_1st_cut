import 'dart:convert';

import 'package:flutter/foundation.dart';
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

/// The request failed at the transport — no connection, DNS failure, or a
/// timeout. It never reached a reply, so the server's opinion is unknown.
///
/// Distinct from a plain [ApiException], which means the server DID answer and
/// said no. The distinction is load-bearing twice over: only this one is safe
/// to retry, and only this one can be classified into "offline" versus
/// "timeout" — which needs [cause], the original error, kept rather than
/// stringified.
class NetworkException extends ApiException {
  NetworkException(this.cause)
      : super('Network error: unable to reach server. ($cause)');

  /// The original TimeoutException / SocketException / whatever it was.
  /// For classification and logs — never shown to a customer.
  final Object cause;
}

/// The stored session is no longer usable — expired, malformed, or issued by a
/// DIFFERENT backend (a token signed with another SECRET_KEY fails to decode).
///
/// Separate from [ApiException] so a caller can tell "you are logged out" from
/// "that request failed", and so a screen does not render an auth error as a
/// retryable network problem.
class AuthExpiredException extends ApiException {
  AuthExpiredException(super.message) : super(statusCode: 401);
}

/// Thin HTTP wrapper that behaves like an interceptor: it holds the bearer
/// token, attaches it to every request, and centralizes JSON decoding.
class ApiClient {
  ApiClient({http.Client? client}) : _client = client ?? http.Client();

  static const _tokenKey = 'carevo_access_token';

  final http.Client _client;
  String? _token;

  /// Bumped every time a request is rejected as unauthenticated. The app root
  /// listens and routes to login; AuthState listens and drops its cached
  /// customer.
  ///
  /// A notifier rather than a callback so several listeners can react to the
  /// same event without one of them having to chain the others — and because
  /// the failure can surface from any screen, on any request, at any time.
  final ValueNotifier<int> authFailures = ValueNotifier<int>(0);

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
    // dynamic values, not String: Uri.replace accepts either a String or an
    // Iterable<String> per key, and an Iterable becomes a REPEATED parameter
    // (`?city=A&city=B`) — which is what the multi-select city filter sends.
    //
    // A plain `v.toString()` on a List would have produced the single literal
    // param `city=[A, B]`, i.e. one nonexistent city, silently returning the
    // wrong outlets rather than failing.
    final qp = <String, dynamic>{};
    if (query != null) {
      query.forEach((k, v) {
        if (v == null) return;
        if (v is Iterable) {
          final values = v.map((e) => e.toString()).toList();
          if (values.isNotEmpty) qp[k] = values;
        } else {
          qp[k] = v.toString();
        }
      });
    }
    return Uri.parse('$base$normalized').replace(
      queryParameters: qp.isEmpty ? null : qp,
    );
  }

  /// A read, with ONE silent retry on a transport failure.
  ///
  /// GET only, and that restriction is the whole safety argument: a read can be
  /// repeated with no consequence, whereas retrying a POST could place a second
  /// order for a request that actually succeeded and only lost its reply. The
  /// other verbs below deliberately get no retry.
  ///
  /// This is where the cold-start bug is fixed. See [AppConfig.coldRetryTimeout]
  /// for the measurements: the first attempt fails fast for a warm server, and
  /// the retry is patient enough to outlast a sleeping one, so the customer
  /// sees a spinner rather than an error they have to dismiss themselves.
  Future<dynamic> get(String path, {Map<String, dynamic>? query}) async {
    try {
      return await _send(() => _client
          .get(_uri(path, query), headers: _headers())
          .timeout(AppConfig.requestTimeout));
    } on NetworkException catch (e) {
      // ONLY a transport failure is retried. An ApiException (4xx/5xx) means
      // the server answered and repeating the call would just get the same
      // answer more slowly.
      if (kDebugMode) {
        debugPrint('GET $path failed at the transport (${e.cause}); '
            'retrying once with a ${AppConfig.coldRetryTimeout.inSeconds}s '
            'budget for a cold backend.');
      }
      return await _send(() => _client
          .get(_uri(path, query), headers: _headers())
          .timeout(AppConfig.coldRetryTimeout));
    }
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
      // The CAUSE is preserved rather than flattened into a message string.
      // It used to be interpolated into "Network error: unable to reach
      // server. ($e)" — which both threw away the type the error classifier
      // needs to tell a timeout from being offline, AND put a raw
      // TimeoutException in front of the customer.
      throw NetworkException(e);
    }

    final body = res.body.isEmpty ? null : _tryDecode(res.body);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return body;
    }

    // A dead session, handled ONCE here rather than per call site.
    //
    // Before this, a stale token was kept forever: every request 401'd while
    // isAuthenticated stayed true, so the app sat on a permanently empty
    // screen and never offered a way back to login. That is exactly what a
    // token from another environment does — one signed with a different
    // SECRET_KEY cannot be decoded by this backend, so EVERY endpoint 401s.
    //
    // 401 ONLY, deliberately. This API also returns 403 for ordinary
    // authorisation denials ("Not your order", "Simulation disabled") where
    // the session is perfectly valid — clearing it there would sign people out
    // for a permission error they could not have avoided.
    if (res.statusCode == 401) {
      await clearToken();
      authFailures.value++;
      throw AuthExpiredException(
        body is Map && body['detail'] != null
            ? body['detail'].toString()
            : 'Your session has expired. Please sign in again.',
      );
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

  void dispose() {
    authFailures.dispose();
    _client.close();
  }
}
