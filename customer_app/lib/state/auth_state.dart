import 'package:flutter/foundation.dart';

import '../models/customer.dart';
import '../services/api_client.dart';
import '../services/otp_auth_service.dart';

/// Holds session state and drives the OTP login flow through
/// [OtpAuthService] (currently the backend-backed stub).
class AuthState extends ChangeNotifier {
  AuthState(this._api, this._otp);

  final ApiClient _api;
  final OtpAuthService _otp;

  Customer? _customer;
  Customer? get customer => _customer;

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

  Future<void> logout() async {
    await _api.clearToken();
    _customer = null;
    _pendingPhone = '';
    _requestId = null;
    notifyListeners();
  }
}
