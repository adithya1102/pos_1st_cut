import 'package:flutter/foundation.dart';

import '../services/api_client.dart';
import '../services/auth_service.dart';

class AuthState extends ChangeNotifier {
  final AuthService _auth;

  AuthState(this._auth);

  bool _loading = false;
  bool _loggedIn = false;
  String? _error;

  bool get loading => _loading;
  bool get loggedIn => _loggedIn;
  String? get error => _error;

  /// Restores session on app start if a token is already stored.
  Future<void> bootstrap() async {
    _loggedIn = await _auth.hasToken();
    notifyListeners();
  }

  Future<bool> login(String username, String password) async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      await _auth.login(username.trim(), password);
      _loggedIn = true;
      return true;
    } on ApiException catch (e) {
      _error = e.statusCode == 401
          ? 'Incorrect username or password.'
          : 'Could not sign in. Please try again.';
      return false;
    } catch (_) {
      _error = 'Could not reach the server. Check your connection.';
      return false;
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  /// Cities selectable at signup, from the canonical list (migration 013).
  Future<List<String>> fetchCities() => _auth.fetchCities();

  /// Owner self-signup. Returns null on success, or a staff-facing error.
  /// Does not log in — the outlet is pending admin verification.
  Future<String?> register({
    required String restaurantName,
    String? city,
    String? requestedCity,
    required String phoneNumber,
    required String username,
    required String password,
    required String upiId,
  }) async {
    try {
      await _auth.register(
        restaurantName: restaurantName.trim(),
        city: city,
        requestedCity: requestedCity,
        phoneNumber: phoneNumber,
        username: username.trim(),
        password: password,
        upiId: upiId,
      );
      return null;
    } on ApiException catch (e) {
      if (e.statusCode == 409) return 'That username is already taken.';
      if (e.statusCode == 429) return 'Too many attempts. Please try again later.';
      if (e.statusCode == 422) return 'Please check your details and try again.';
      return 'Could not register. Please try again.';
    } catch (_) {
      return 'Could not reach the server. Check your connection.';
    }
  }

  Future<void> logout() async {
    await _auth.logout();
    _loggedIn = false;
    notifyListeners();
  }
}
