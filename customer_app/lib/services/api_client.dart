import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/app_config.dart';
// Logging only — carries no Firebase dependency, so ApiClient stays
// constructible in tests and in any context with no Firebase app.
import 'session_log.dart';

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

/// Mints a fresh CareVo session token from whatever identity the app still
/// holds, or returns null when that identity is genuinely gone.
///
/// A callback rather than a direct dependency so [ApiClient] never imports
/// Firebase: the client stays constructible in tests and in any context with
/// no Firebase app initialised. See `session_refresher.dart` for the real one
/// and `main.dart` for the wiring.
typedef SessionRefresher = Future<String?> Function();

/// Thin HTTP wrapper that behaves like an interceptor: it holds the bearer
/// token, attaches it to every request, and centralizes JSON decoding.
class ApiClient {
  ApiClient({http.Client? client}) : _client = client ?? http.Client();

  static const _tokenKey = 'carevo_access_token';

  final http.Client _client;
  String? _token;

  /// Set once at startup. NULL means "no way to refresh", and every 401 then
  /// behaves exactly as it did before this existed — which is what keeps the
  /// existing tests honest rather than accidentally passing.
  SessionRefresher? sessionRefresher;

  /// The one in-flight refresh, so concurrent 401s share it.
  ///
  /// Home alone fires several requests at once, and they expire together
  /// because they carry the same token. Without this each would mint its own
  /// Firebase token and its own exchange — a burst of identical logins, with
  /// the last write deciding which token survives.
  Future<bool>? _refreshInFlight;

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

  /// POST that will NOT try to refresh the session on a 401.
  ///
  /// Exists for the exchange call itself: refreshing in order to refresh is a
  /// loop. The exchange endpoints are unauthenticated anyway, so a 401 from
  /// one of them means the identity really is dead.
  Future<dynamic> postWithoutRefresh(String path, {Object? body}) {
    return _send(
      () => _client
          .post(_uri(path), headers: _headers(), body: jsonEncode(body ?? {}))
          .timeout(AppConfig.requestTimeout),
      allowRefresh: false,
    );
  }

  /// Mint a new session, collapsing concurrent callers onto one attempt.
  ///
  /// Same shape as LocationService's in-flight guard, and for the same reason.
  Future<bool> _refreshSession() {
    final pending = _refreshInFlight;
    if (pending != null) return pending;

    late final Future<bool> call;
    call = _doRefresh().whenComplete(() {
      if (identical(_refreshInFlight, call)) _refreshInFlight = null;
    });
    _refreshInFlight = call;
    return call;
  }

  Future<bool> _doRefresh() async {
    // The attempt itself, stamped. Half of the evidence for the race
    // hypothesis: this line's elapsed time compared against the
    // 'firebase user restored' line says whether the refresh beat Firebase's
    // async restore or whether currentUser was already there and something
    // else failed. Logged here rather than at the 401 site because
    // _refreshSession coalesces a burst of concurrent 401s onto ONE attempt,
    // and this is that attempt.
    sessionLog('refresh triggered by a 401');

    final refresher = sessionRefresher;
    if (refresher == null) {
      // DEFENSIVE ONLY. _send checks `sessionRefresher != null` before calling
      // here, so this is unreachable on the 401 path — the real "no refresher"
      // log lives there, at the decision point. Kept because _doRefresh is not
      // private to that one caller forever, and a silently-false return is what
      // this whole change exists to stop.
      sessionLog('refresh UNAVAILABLE: no refresher wired (via _doRefresh)');
      return false;
    }
    try {
      final fresh = await refresher();
      if (fresh == null || fresh.isEmpty) {
        // The refresher already logged its own specific reason; this records
        // that the decision reached the client and is about to become a
        // logout, so the two halves can be matched up in a device log.
        sessionLog('refresh FAILED: refresher returned '
            '${fresh == null ? 'null' : 'an empty token'} — signing out');
        return false;
      }
      await setToken(fresh);
      sessionLog('refresh SUCCEEDED: session renewed, replaying the request');
      return true;
    } catch (e) {
      // A refresh that throws is a refresh that failed. Swallowed so the
      // caller falls through to the ordinary expiry path rather than showing
      // a Firebase error to someone who only asked to see their orders.
      //
      // NO LONGER kDebugMode-gated. This was the single line that could have
      // explained a forced re-login, and it printed nothing in exactly the
      // build where the failure happens — the same way the FCM registration
      // failure hid. getIdToken throwing (offline, Firebase internal) and the
      // exchange POST timing out both land here.
      sessionLog('refresh THREW: $e — signing out');
      return false;
    }
  }

  /// [allowRefresh] false on the retry, so one 401 can cost at most one
  /// refresh and one replay — never a loop.
  Future<dynamic> _send(
    Future<http.Response> Function() run, {
    bool allowRefresh = true,
  }) async {
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
      // BEFORE giving up: the CareVo token lives 24h and has no refresh of its
      // own, but the Firebase session behind it persists indefinitely. So an
      // expired token usually means "this JWT aged out", not "this person is
      // logged out" — and the old code could not tell those apart, which is
      // why people were signed out roughly daily.
      //
      // Replaying `run()` is safe for EVERY verb, not just GET. A 401 comes
      // from get_current_customer, a FastAPI dependency that only decodes the
      // JWT and SELECTs the customer; it raises before the handler body runs,
      // so nothing was processed and there is nothing to double-apply. That is
      // checked, not assumed — see deps.py.
      //
      // `run()` rebuilds its headers when called, so the replay picks up the
      // token setToken() just wrote, with no plumbing.
      if (allowRefresh && sessionRefresher == null) {
        // THE decision point for "there is no way to refresh" — not the
        // matching guard inside _doRefresh, which this short-circuit means is
        // never reached from here. Logged at the place the choice is actually
        // made, so the log cannot claim something the code did not do.
        //
        // Reachable when Firebase auth is off (USE_FIREBASE_AUTH=false) or the
        // wiring in main() was missed. From the outside it is indistinguishable
        // from a genuine expiry, which is exactly why it needs a name.
        sessionLog('refresh UNAVAILABLE: no refresher wired '
            '(AppConfig.useFirebaseAuth false, or wiring missed) — signing out');
      }
      if (allowRefresh && sessionRefresher != null) {
        if (await _refreshSession()) {
          return _send(run, allowRefresh: false);
        }
      } else if (!allowRefresh) {
        // The replay after a successful refresh 401'd as well. The identity is
        // genuinely dead rather than merely stale, and looping would only
        // hammer the exchange endpoint.
        sessionLog('replay after refresh STILL 401 — session really is dead');
      }

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
