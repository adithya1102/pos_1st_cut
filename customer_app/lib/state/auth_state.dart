import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/customer.dart';
import '../services/api_client.dart';
import '../services/google_auth_service.dart';
import '../services/otp_auth_service.dart';
import '../services/push_service.dart';

/// Holds session state and drives the two login flows: phone OTP through
/// [OtpAuthService], and Google through [GoogleAuthService].
class AuthState extends ChangeNotifier {
  AuthState(this._api, this._otp, this._google, this._push);

  final ApiClient _api;
  final OtpAuthService _otp;
  final GoogleAuthService _google;
  final PushService _push;

  Customer? _customer;
  Customer? get customer => _customer;

  /// Register for push AFTER authentication, since the backend stores the
  /// token against the signed-in customer. Not awaited — a permission prompt
  /// must never gate getting into the app.
  void _registerPush() {
    unawaited(_push.registerAfterLogin());
  }

  /// Replace the cached customer after a profile edit, so screens reading the
  /// session copy don't show a stale name until the next sign-in.
  void setCustomer(Customer customer) {
    _customer = customer;
    notifyListeners();
  }

  bool get isAuthenticated => _api.isAuthenticated;

  bool _busy = false;
  bool get busy => _busy;

  String? _error;
  String? get error => _error;

  String _pendingPhone = '';
  String get pendingPhone => _pendingPhone;

  String? _requestId;
  String? get requestId => _requestId;

  void _setBusy(bool v) {
    _busy = v;
    notifyListeners();
  }

  /// Step 1 of login: request an OTP for [phone].
  Future<bool> requestOtp(String phone) async {
    _error = null;
    _pendingPhone = phone;
    _setBusy(true);
    try {
      _requestId = await _otp.requestOtp(phone);
      return true;
    } on ApiException catch (e) {
      _error = e.message;
      return false;
    } catch (e) {
      _error = 'Something went wrong. Please try again.';
      return false;
    } finally {
      _setBusy(false);
    }
  }

  /// Step 2 of login: verify [otp] against the pending phone.
  Future<bool> verifyOtp(String otp) async {
    _error = null;
    _setBusy(true);
    try {
      final result = await _otp.verifyOtp(_pendingPhone, otp);
      _customer = result.customer;
      _registerPush();
      notifyListeners();
      return true;
    } on ApiException catch (e) {
      _error = e.message;
      return false;
    } catch (e) {
      _error = 'Invalid code. Please try again.';
      return false;
    } finally {
      _setBusy(false);
    }
  }

  /// Google sign-in. Returns false on failure AND on a plain cancel — the
  /// caller distinguishes them by whether [error] was set.
  Future<bool> signInWithGoogle() async {
    _error = null;
    _setBusy(true);
    try {
      final result = await _google.signIn();
      // null == the user dismissed the picker: no error to show.
      if (result == null) return false;
      _customer = result.customer;
      _registerPush();
      notifyListeners();
      return true;
    } on ApiException catch (e) {
      _error = e.message;
      return false;
    } catch (e) {
      _error = 'Could not sign in with Google. Please try again.';
      return false;
    } finally {
      _setBusy(false);
    }
  }

  Future<void> logout() async {
    // Clear the device token BEFORE dropping the session token — unregistering
    // is an authenticated call, so it has to happen while still signed in.
    await _push.unregister();
    await _api.clearToken();
    // Drop the cached Google account too, so the next sign-in shows the picker
    // instead of silently reusing whoever was signed in before.
    await _google.signOut();
    _customer = null;
    _pendingPhone = '';
    _requestId = null;
    notifyListeners();
  }
}
