import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'order_service.dart';

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
class StaffPushService {
  StaffPushService(this._orders);

  final OrderService _orders;

  FirebaseMessaging get _fm => FirebaseMessaging.instance;

  bool _granted = false;
  bool get granted => _granted;

  /// Avoids re-POSTing an unchanged token on every app start.
  String? _lastRegistered;

  /// Ask for permission and register the token. Call AFTER login — the backend
  /// stores it against the authenticated staff user, so earlier has nowhere to
  /// put it.
  Future<void> registerAfterLogin() async {
    try {
      final settings = await _fm.requestPermission();
      _granted = settings.authorizationStatus == AuthorizationStatus.authorized ||
          settings.authorizationStatus == AuthorizationStatus.provisional;
      if (!_granted) return;

      final token = await _fm.getToken();
      if (token != null && token.isNotEmpty) {
        await _send(token);
      }

      // FCM rotates tokens (reinstall, restore, periodic refresh). Without this
      // the server keeps pushing to a dead token forever, and the outlet
      // silently stops being told about new orders.
      _fm.onTokenRefresh.listen((t) {
        if (t.isNotEmpty) _send(t);
      });
    } catch (e) {
      if (kDebugMode) debugPrint('StaffPushService.registerAfterLogin: $e');
    }
  }

  Future<void> _send(String token) async {
    if (token == _lastRegistered) return;
    try {
      await _orders.registerPushToken(token);
      _lastRegistered = token;
    } catch (e) {
      // A failed registration must never block using the app. Retried on the
      // next login or token refresh.
      if (kDebugMode) debugPrint('StaffPushService._send: $e');
    }
  }

  /// Called on logout: stop this device receiving orders for an outlet whose
  /// staff member has signed out. Deleting the FCM token is the local half;
  /// the server row is overwritten by whoever registers next on this device.
  Future<void> clear() async {
    _lastRegistered = null;
    try {
      await _fm.deleteToken();
    } catch (e) {
      if (kDebugMode) debugPrint('StaffPushService.clear: $e');
    }
  }
}
