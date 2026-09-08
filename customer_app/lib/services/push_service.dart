import 'dart:io' show Platform;

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'api_client.dart';

/// Firebase Cloud Messaging registration for the signed-in customer.
///
/// Responsibilities, in order:
///   1. ask the OS for notification permission (REQUIRED on Android 13+ / iOS)
///   2. fetch this device's FCM registration token
///   3. hand it to the backend, which stores it on the customer row
///   4. keep it fresh when FCM rotates it
///
/// Everything here is best-effort. A customer who declines notifications, or a
/// device where FCM is unavailable (no Play Services), must still be able to
/// order — so nothing in this class throws into the caller.
class PushService {
  PushService(this._api);

  final ApiClient _api;

  FirebaseMessaging get _fm => FirebaseMessaging.instance;

  /// True once the OS has granted (or provisionally granted) permission.
  bool _granted = false;
  bool get granted => _granted;

  /// Set after a successful register; used to avoid re-POSTing an unchanged
  /// token on every app start.
  String? _lastRegistered;

  /// Ask for permission and register the token. Call AFTER sign-in — the
  /// backend stores the token against the authenticated customer, so doing this
  /// earlier would have nowhere to put it.
  ///
  /// Deliberately NOT called at app start: prompting before the customer has
  /// done anything is the classic way to get a permanent denial.
  Future<void> registerAfterLogin() async {
    try {
      final settings = await _fm.requestPermission();
      _granted = settings.authorizationStatus == AuthorizationStatus.authorized ||
          settings.authorizationStatus == AuthorizationStatus.provisional;
      if (!_granted) return;

      // APNs on iOS can briefly have no token right after permission is
      // granted; getToken() returning null is normal there, not an error.
      final token = await _fm.getToken();
      if (token != null && token.isNotEmpty) {
        await _sendToken(token);
      }

      // FCM rotates tokens (app reinstall, restore, periodic refresh). Without
      // this the server would keep pushing to a dead token forever.
      _fm.onTokenRefresh.listen((t) {
        if (t.isNotEmpty) _sendToken(t);
      });
    } catch (e) {
      // No Play Services, no network, permission plugin failure — all
      // non-fatal. Notifications are an enhancement, not a prerequisite.
      debugPrint('PushService.registerAfterLogin skipped: $e');
    }
  }

  Future<void> _sendToken(String token) async {
    if (token == _lastRegistered) return;
    try {
      await _api.post('/customer/push/register', body: {'fcm_token': token});
      _lastRegistered = token;
    } on ApiException catch (e) {
      debugPrint('PushService: token registration failed: ${e.message}');
    }
  }

  /// Drop the token server-side on logout, so a shared device stops receiving
  /// notifications for an account that is no longer signed in.
  Future<void> unregister() async {
    _lastRegistered = null;
    _granted = false;
    try {
      await _api.delete('/customer/push/register');
    } catch (e) {
      debugPrint('PushService.unregister skipped: $e');
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
}
