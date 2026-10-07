import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'order_alert_notifications.dart';
import 'order_service.dart';

/// Push kinds the backend sends to staff. Mirrors PushService's KIND_* values.
class StaffPushKind {
  static const newOrder = 'STAFF_NEW_ORDER';
  /// Addendum Item 1: "start this one now", derived from a train order's
  /// declared arrival. Purely a prompt — it moves no status.
  static const trainStartDue = 'TRAIN_START_DUE';
}

/// Why the last registration attempt ended the way it did. Mirrors
/// customer_app's PushRegistrationStatus.
enum StaffPushStatus {
  notAttempted,
  registered,
  noToken,
  sendFailed,
  unavailable,
}

/// Handles a staff push that arrives while the app is backgrounded or killed.
///
/// ## Two kinds of push arrive here, and they are NOT alike
///
/// `STAFF_NEW_ORDER` and `TRAIN_START_DUE` still carry a `notification` block
/// (PushService._transmit), so Android draws them from the system tray without
/// running any Dart. For those, this function is only the one hook that can see
/// the `data` half while the app is not running — removing it would not silence
/// a single one of them.
///
/// `NEW_ORDER_PENDING` and `ORDER_RESOLVED` (manual acceptance, migration 032)
/// are the opposite: they are sent DATA-ONLY, with no notification block, and
/// Android draws NOTHING for them on its own. For those this function IS the
/// alert — it raises a local notification and, on resolution, cancels it. If it
/// does not run, a manual-acceptance restaurant is never told an order is
/// waiting.
///
/// That asymmetry is deliberate on the server side: the insistent behaviour
/// (repeating sound, un-swipeable, and above all withdrawable when another
/// device settles the order) all requires code, and a system-rendered
/// notification cannot be withdrawn by us.
///
/// ## Why it looks the way it does
///
/// FCM runs this in a SEPARATE ISOLATE with its own memory. Nothing built in
/// `main()` exists here — no providers, no OrdersState, no ApiClient, no
/// Firebase app. Hence:
///
///   * `@pragma('vm:entry-point')`, or tree-shaking drops it from release
///     builds and the callback silently never fires — a failure that cannot be
///     reproduced in debug;
///   * top-level, not a method, because the entry point is resolved by name
///     across the isolate boundary;
///   * `Firebase.initializeApp()` again, since this isolate has no app yet, and
///     wrapped for the same reason main() wraps it: a tablet without Play
///     Services must still run the restaurant.
///
/// It deliberately does NOT touch OrdersState or try to raise the in-app
/// NewOrderAlert. That state lives in the UI isolate and is unreachable from
/// here; more importantly the in-app alert is already driven by the order poll,
/// so reaching across would be the double-notification this app has to avoid.
/// A system notification is a different surface and does not collide with it.

/// Push kinds this handler acts on ITSELF. Mirrors the backend constants in
/// `app/modules/push/service.py`; both are sent DATA-ONLY precisely so this
/// handler runs.
const String kindNewOrderPending = 'NEW_ORDER_PENDING';
const String kindOrderResolved = 'ORDER_RESOLVED';

@pragma('vm:entry-point')
Future<void> staffBackgroundHandler(RemoteMessage message) async {
  try {
    await Firebase.initializeApp();
  } catch (_) {
    // No Play Services / no Firebase app: nothing to do but return quietly.
    return;
  }
  if (kDebugMode) {
    debugPrint('[staff-push/bg] ${message.data['kind']} '
        'order=${message.data['order_id']}');
  }

  // ACCEPTANCE ALERTS (migration 032) are handled HERE, in the background
  // isolate, and that is the whole reason the server sends them data-only: a
  // message carrying a `notification` block is rendered by the system tray
  // and this function is never invoked for it.
  //
  // A LOCAL notification is raised rather than relying on the push itself,
  // because everything that makes this alert useful needs code: FLAG_INSISTENT
  // so the sound repeats, ongoing so it cannot be swiped away, and — the part
  // nothing else can do — CANCELLATION when another device settles the order.
  //
  // Still deliberately narrow. It does NOT touch OrdersState or try to raise
  // the in-app modal: that state lives in the UI isolate and is unreachable
  // from here, and the modal is already driven by the order poll, so reaching
  // across would produce the double-alert this app has to avoid.
  final kind = message.data['kind'];
  if (kind != kindNewOrderPending && kind != kindOrderResolved) return;

  try {
    final notifications = OrderAlertNotifications();
    await notifications.init();
    if (kind == kindOrderResolved) {
      await notifications.cancelPending();
      return;
    }
    await notifications.showPending(
      // Title/body travel as DATA for these kinds, since there is no
      // notification block to carry them.
      title: (message.data['title'] as String?)?.trim().isNotEmpty == true
          ? message.data['title'] as String
          : 'Accept this order?',
      body: (message.data['body'] as String?) ?? 'Tap to accept or reject.',
      orderId: message.data['order_id'] as String?,
    );
  } catch (e) {
    // A failure here must not crash the isolate. The order does not depend on
    // the notification: it expires on the server's clock either way, and the
    // foreground poll raises the modal as soon as the app is opened.
    if (kDebugMode) debugPrint('[staff-push/bg] alert failed: $e');
  }
}

/// FCM registration for the signed-in STAFF user (migration 017).
///
/// Mirrors customer_app's PushService deliberately — same shape, same
/// best-effort contract — but posts to `/pos/push/register`, which stores the
/// token on `users.fcm_token` rather than `customers.fcm_token`.
///
/// Why staff need this at all: there is no Accept step on an order. A paid
/// order goes straight to RECEIVED, so nothing blocks waiting for someone to
/// look at the tablet. This notification is the entire mechanism by which staff
/// find out in time to REJECT an order they cannot make.
///
/// Everything here is best-effort. An owner who declines notifications, or a
/// device with no Play Services, must still be able to run their restaurant —
/// so nothing in this class throws into the caller.
///
/// ## Why permission no longer gates registration
///
/// This used to `return` early whenever permission was not granted. On Android
/// POST_NOTIFICATIONS controls whether a notification is DISPLAYED — FCM still
/// issues a token without it — so the early return threw away a usable token,
/// and did it permanently: Android stops showing the dialog after two
/// dismissals, so every later login took the same silent path. `users.fcm_token`
/// was NULL for all nine staff accounts for a month with nothing logged.
///
/// Permission is still requested, because it is the only way an alert gets
/// shown. A denial now records itself and registration continues.
class StaffPushService {
  /// [requestPermission], [fetchToken] and [tokenRefreshes] are injectable so
  /// registration is testable without a Firebase app. Production passes none of
  /// them and gets the real FirebaseMessaging calls.
  StaffPushService(
    this._orders, {
    Future<bool> Function()? requestPermission,
    Future<String?> Function()? fetchToken,
    Stream<String> Function()? tokenRefreshes,
  })  : _requestPermission = requestPermission ?? _firebaseRequestPermission,
        _fetchToken = fetchToken ?? _firebaseFetchToken,
        _tokenRefreshes = tokenRefreshes ?? _firebaseTokenRefreshes;

  final OrderService _orders;
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

  /// Reflects whether alerts can be DISPLAYED — not whether the token was
  /// registered. The two are independent; see the class doc.
  bool _granted = false;
  bool get granted => _granted;

  /// Outcome of the most recent attempt, so a failure is assertable in tests
  /// and inspectable at runtime instead of vanishing.
  final ValueNotifier<StaffPushStatus> status =
      ValueNotifier<StaffPushStatus>(StaffPushStatus.notAttempted);

  /// Avoids re-POSTing an unchanged token. Cleared on failure so the next
  /// attempt genuinely retries.
  String? _lastRegistered;

  /// One rotation listener per instance, not one per attempt.
  StreamSubscription<String>? _refreshSub;

  bool _inFlight = false;

  /// Set when a staff push is TAPPED. HomeScreen watches this and switches to
  /// the existing Orders tab — no new screen, and no navigation logic living
  /// inside a service.
  ///
  /// A ValueNotifier rather than a stream because the payload is one nullable
  /// id and a late listener should still see the pending value: a push that
  /// launched the app from cold arrives before HomeScreen has mounted.
  final ValueNotifier<String?> openOrderId = ValueNotifier<String?>(null);

  void _handleTap(RemoteMessage? m) {
    if (m == null) return;
    final kind = m.data['kind'];
    if (kind != StaffPushKind.newOrder && kind != StaffPushKind.trainStartDue) {
      return;
    }
    openOrderId.value = m.data['order_id'] as String?;
  }

  /// Wire tap handling. Safe to call before login — it only listens.
  Future<void> attachTapRouting() async {
    try {
      // App opened FROM a notification while backgrounded.
      FirebaseMessaging.onMessageOpenedApp.listen(_handleTap);
      // App launched cold by a notification: the message is waiting.
      _handleTap(await _fm.getInitialMessage());
    } catch (e) {
      _log('attachTapRouting: $e');
    }
  }

  /// Ask for permission and register the token. Call AFTER login — the backend
  /// stores it against the authenticated staff user, so earlier has nowhere to
  /// put it.
  Future<void> registerAfterLogin() => _attempt(askPermission: true);

  /// Re-attempt for a session that was RESTORED rather than freshly created.
  ///
  /// Called from HomeScreen, which only mounts when already authenticated. This
  /// closes the same gap customer_app had: registration ran only inside the
  /// login screen, but staff log into a tablet once and it stays logged in for
  /// weeks. Nothing re-attempted in between, so one failed registration was
  /// permanent — which is exactly how all nine staff rows stayed NULL.
  ///
  /// Does not prompt: the OS dialog belongs to the login moment.
  Future<void> ensureRegistered() {
    if (status.value == StaffPushStatus.registered) {
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
        _log('getToken() threw — no token to register: $e');
        status.value = StaffPushStatus.unavailable;
        return;
      }

      if (token == null || token.isEmpty) {
        _log('getToken() returned ${token == null ? 'null' : 'empty'} — '
            'nothing to register (permission granted: $_granted)');
        status.value = StaffPushStatus.noToken;
        return;
      }

      await _send(token);

      // FCM rotates tokens (reinstall, restore, periodic refresh). Without this
      // the server keeps pushing to a dead token forever, and the outlet
      // silently stops being told about new orders.
      _refreshSub ??= _tokenRefreshes().listen(
        (t) {
          if (t.isNotEmpty) unawaited(_send(t));
        },
        onError: (Object e) => _log('token refresh stream error: $e'),
      );
    } catch (e) {
      _log('registration attempt failed: $e');
      status.value = StaffPushStatus.unavailable;
    } finally {
      _inFlight = false;
    }
  }

  Future<void> _send(String token) async {
    if (token == _lastRegistered) return;
    try {
      await _orders.registerPushToken(token);
      _lastRegistered = token;
      status.value = StaffPushStatus.registered;
    } catch (e) {
      // A failed registration must never block using the app. _lastRegistered
      // stays unset so the next login or app start re-sends rather than
      // treating this token as done.
      _log('token registration POST failed (will retry on next login/start): $e');
      status.value = StaffPushStatus.sendFailed;
    }
  }

  /// Called on logout: stop this device receiving orders for an outlet whose
  /// staff member has signed out. Deleting the FCM token is the local half;
  /// the server row is overwritten by whoever registers next on this device.
  Future<void> clear() async {
    _lastRegistered = null;
    _granted = false;
    status.value = StaffPushStatus.notAttempted;
    await _refreshSub?.cancel();
    _refreshSub = null;
    try {
      await _fm.deleteToken();
    } catch (e) {
      _log('clear: $e');
    }
  }

  /// Deliberately NOT wrapped in `kDebugMode`. Every debugPrint in this class
  /// used to be, which is why a failure that only ever happened on the real
  /// release build on the real tablet left no trace anywhere.
  void _log(String message) => debugPrint('[StaffPushService] $message');
}
