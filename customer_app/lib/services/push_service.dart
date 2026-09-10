import 'dart:async';
import 'dart:io' show Platform;

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'api_client.dart';

/// Handles a push that arrives while the app is backgrounded or killed.
///
/// ## What this does NOT do
///
/// It does not make the notification appear. The backend sends a `notification`
/// block alongside its `data` (see PushService._transmit), and Android renders
/// that from the system tray without running any Dart at all. Deleting this
/// function would not stop a single notification from being shown.
///
/// What it buys is a place to react to the `data` half while the app is not
/// running — the only hook where that is possible.
///
/// ## Why it looks the way it does
///
/// FCM runs this in a SEPARATE ISOLATE with its own memory. Nothing built in
/// `main()` exists here: no providers, no ApiClient, no Firebase app. Hence:
///
///   * `@pragma('vm:entry-point')`, or tree-shaking removes it from release
///     builds and the callback silently never fires — a bug that cannot be
///     reproduced in debug;
///   * top-level, not a method or closure, because the entry point is looked
///     up by name across the isolate boundary;
///   * `Firebase.initializeApp()` again, since this isolate has no app yet.
///
/// Deliberately does almost nothing else. Work here competes with a process
/// Android is trying to keep cheap, and anything touching app state would be
/// writing to an isolate that the UI cannot see. The app re-reads its data on
/// resume anyway, which is the correct place for it.
@pragma('vm:entry-point')
Future<void> customerBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
  if (kDebugMode) {
    debugPrint('[push/bg] ${message.data['kind']} '
        'order=${message.data['order_id']}');
  }
}

/// Why the last registration attempt ended the way it did.
///
/// Exists because every one of these outcomes used to be a bare `return`. In
/// production that made "no token stored" indistinguishable from "never tried",
/// and the database could not tell us which — 45 customers and 9 staff sat at
/// NULL for a month with nothing anywhere saying why.
enum PushRegistrationStatus {
  /// No attempt since app start.
  notAttempted,

  /// Token reached the backend.
  registered,

  /// FCM had no token to give. On iOS this is the normal consequence of a
  /// declined permission, since APNs issues no token without one.
  noToken,

  /// A token existed but the POST failed (offline, 401, 5xx, cold start).
  /// Retried on the next login or app start.
  sendFailed,

  /// Firebase itself was unreachable — no Play Services, no Firebase app.
  unavailable,
}

/// Firebase Cloud Messaging registration for the signed-in customer.
///
/// Responsibilities, in order:
///   1. ask the OS for notification permission (so alerts can be DISPLAYED)
///   2. fetch this device's FCM registration token
///   3. hand it to the backend, which stores it on the customer row
///   4. keep it fresh when FCM rotates it
///
/// Everything here is best-effort. A customer who declines notifications, or a
/// device where FCM is unavailable (no Play Services), must still be able to
/// order — so nothing in this class throws into the caller.
///
/// ## Why permission no longer gates registration
///
/// This used to `return` early whenever permission was not granted, which meant
/// a single tap on "Don't allow" permanently prevented the token from ever
/// reaching the backend. That was wrong on two counts:
///
///   * On Android, POST_NOTIFICATIONS governs whether a notification is
///     DISPLAYED. FCM still issues a token and still delivers data messages
///     without it. Refusing to register threw away a token the platform was
///     perfectly willing to give.
///   * It was unrecoverable. Android stops showing the permission dialog after
///     two dismissals, so `requestPermission()` returns denied immediately
///     forever after — and the early return meant every subsequent login took
///     the same silent path. A customer who later enabled notifications in
///     system settings would still never be registered, because nothing
///     re-attempted.
///
/// So permission is still requested (it is the only way alerts get shown, and
/// on iOS it is genuinely required before APNs will mint a token), but a denial
/// no longer stops the registration attempt. If the token comes back null we
/// record [PushRegistrationStatus.noToken] and move on.
class PushService {
  /// [requestPermission], [fetchToken] and [tokenRefreshes] are injectable so
  /// the registration logic is testable without a Firebase app. Production
  /// passes none of them and gets the real FirebaseMessaging calls.
  PushService(
    this._api, {
    Future<bool> Function()? requestPermission,
    Future<String?> Function()? fetchToken,
    Stream<String> Function()? tokenRefreshes,
  })  : _requestPermission = requestPermission ?? _firebaseRequestPermission,
        _fetchToken = fetchToken ?? _firebaseFetchToken,
        _tokenRefreshes = tokenRefreshes ?? _firebaseTokenRefreshes;

  final ApiClient _api;
  final Future<bool> Function() _requestPermission;
  final Future<String?> Function() _fetchToken;
  final Stream<String> Function() _tokenRefreshes;

  static FirebaseMessaging get _fm => FirebaseMessaging.instance;

  static Future<bool> _firebaseRequestPermission() async {
    final settings = await _fm.requestPermission();
    return settings.authorizationStatus == AuthorizationStatus.authorized ||
        settings.authorizationStatus == AuthorizationStatus.provisional;
  }

  static Future<String?> _firebaseFetchToken() => _fm.getToken();

  static Stream<String> _firebaseTokenRefreshes() => _fm.onTokenRefresh;

  /// True once the OS has granted (or provisionally granted) permission.
  /// Reflects whether alerts can be DISPLAYED — not whether the token was
  /// registered. The two are independent; see the class doc.
  bool _granted = false;
  bool get granted => _granted;

  /// Outcome of the most recent attempt. A ValueNotifier so a diagnostics
  /// screen could surface it later without this class knowing about the UI —
  /// and so tests can assert an outcome rather than scrape log output.
  final ValueNotifier<PushRegistrationStatus> status =
      ValueNotifier<PushRegistrationStatus>(PushRegistrationStatus.notAttempted);

  /// Set after a successful register; used to avoid re-POSTing an unchanged
  /// token. Cleared on failure so the next attempt genuinely retries.
  String? _lastRegistered;

  /// Guards against stacking a second rotation listener every time
  /// registration runs. Without it, logging in twice in one process meant two
  /// listeners and two POSTs per rotation.
  StreamSubscription<String>? _refreshSub;

  /// True while an attempt is in flight, so a login landing next to an
  /// app-start attempt cannot run two registrations concurrently.
  bool _inFlight = false;

  /// Ask for permission and register the token. Call AFTER sign-in — the
  /// backend stores the token against the authenticated customer, so doing this
  /// earlier would have nowhere to put it.
  ///
  /// Deliberately NOT called at app start with a prompt: prompting before the
  /// customer has done anything is the classic way to get a permanent denial.
  Future<void> registerAfterLogin() => _attempt(askPermission: true);

  /// Re-attempt registration for a session that was RESTORED rather than freshly
  /// created — the app-start path for someone already signed in.
  ///
  /// This closes the gap that kept every long-lived session unregistered:
  /// registration only ever ran inside the two login methods, but a customer
  /// logs in once and then stays signed in for weeks (the session renews itself
  /// rather than expiring). Nothing re-attempted in between, so a single failed
  /// or skipped registration was permanent for the life of that session.
  ///
  /// Does NOT prompt: the OS dialog belongs to a deliberate moment, not to app
  /// start. If permission was granted before, the token is fetched and sent as
  /// usual; if it was not, this still registers the token on Android and simply
  /// records [PushRegistrationStatus.noToken] on a platform that withholds one.
  Future<void> ensureRegistered() {
    if (!_api.isAuthenticated) return Future<void>.value();
    if (status.value == PushRegistrationStatus.registered) {
      return Future<void>.value();
    }
    return _attempt(askPermission: false);
  }

  Future<void> _attempt({required bool askPermission}) async {
    if (_inFlight) return;
    _inFlight = true;
    try {
      if (askPermission) {
        try {
          _granted = await _requestPermission();
          if (!_granted) {
            // Not a failure any more, and no longer a silent one. Registration
            // continues; only the DISPLAY of alerts is affected.
            _log('notification permission denied — registering token anyway '
                '(alerts will not be shown until it is granted)');
          }
        } catch (e) {
          _log('permission request failed, continuing to token fetch: $e');
        }
      }

      String? token;
      try {
        token = await _fetchToken();
      } catch (e) {
        // No Play Services, no Firebase app, no network at init time.
        _log('getToken() threw — no token to register: $e');
        status.value = PushRegistrationStatus.unavailable;
        return;
      }

      if (token == null || token.isEmpty) {
        // Normal on iOS when permission was declined (APNs mints no token).
        // Previously an invisible dead end; now at least it says so.
        _log('getToken() returned ${token == null ? 'null' : 'empty'} — '
            'nothing to register (permission granted: $_granted)');
        status.value = PushRegistrationStatus.noToken;
        return;
      }

      await _sendToken(token);

      // FCM rotates tokens (app reinstall, restore, periodic refresh). Without
      // this the server would keep pushing to a dead token forever. Subscribed
      // once per instance, not once per attempt.
      _refreshSub ??= _tokenRefreshes().listen(
        (t) {
          if (t.isNotEmpty) unawaited(_sendToken(t));
        },
        onError: (Object e) => _log('token refresh stream error: $e'),
      );
    } catch (e) {
      // Anything unforeseen. Notifications are an enhancement, not a
      // prerequisite — but it is no longer invisible when they break.
      _log('registration attempt failed: $e');
      status.value = PushRegistrationStatus.unavailable;
    } finally {
      _inFlight = false;
    }
  }

  Future<void> _sendToken(String token) async {
    if (token == _lastRegistered) return;
    try {
      await _api.post('/customer/push/register', body: {'fcm_token': token});
      _lastRegistered = token;
      status.value = PushRegistrationStatus.registered;
    } catch (e) {
      // Catches ApiException AND transport failures the client did not wrap.
      // _lastRegistered is deliberately left unset so the next login or app
      // start re-sends this token rather than treating it as done.
      _log('token registration POST failed (will retry on next login/start): '
          '${e is ApiException ? e.message : e}');
      status.value = PushRegistrationStatus.sendFailed;
    }
  }

  /// Drop the token server-side on logout, so a shared device stops receiving
  /// notifications for an account that is no longer signed in.
  Future<void> unregister() async {
    _lastRegistered = null;
    _granted = false;
    status.value = PushRegistrationStatus.notAttempted;
    await _refreshSub?.cancel();
    _refreshSub = null;
    try {
      await _api.delete('/customer/push/register');
    } catch (e) {
      _log('unregister skipped: $e');
    }
    try {
      // Also invalidate locally so a re-login mints a fresh token.
      if (!kIsWeb && (Platform.isAndroid || Platform.isIOS)) {
        await _fm.deleteToken();
      }
    } catch (_) {
      // Non-fatal: the server-side clear above is what actually stops sends.
    }
  }

  /// Deliberately NOT wrapped in `kDebugMode`. The whole failure this class was
  /// fixed for was invisible precisely because it only ever happened on real
  /// release builds on real devices.
  void _log(String message) => debugPrint('[PushService] $message');
}
