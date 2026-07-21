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

  Future<void> logout() async {
    await _auth.logout();
    _loggedIn = false;
    notifyListeners();
  }
}
