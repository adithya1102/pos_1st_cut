import 'dart:async';

import 'package:flutter/foundation.dart';

import '../services/api_client.dart';
import '../services/auth_service.dart';

/// Why a sign-in attempt failed. The UI needs this because the three cases call
/// for three different reactions from the owner: check your typing, check your
/// connection, or wait and retry.
enum LoginFailure {
  /// The server answered 401 — the credentials are genuinely wrong.
  badCredentials,

  /// No HTTP response at all: offline, DNS/TLS failure, or connection refused.
  network,

  /// We waited out the timeout. On Render's free tier this is usually a cold
  /// start, not a dead server.
  timeout,

  /// The server answered, but with something other than 401.
  serverError,
}

class AuthState extends ChangeNotifier {
  final AuthService _auth;

  AuthState(this._auth);

  bool _loading = false;
  bool _loggedIn = false;
  String? _error;
  LoginFailure? _failure;
  bool _wakingUp = false;

  bool get loading => _loading;
  bool get loggedIn => _loggedIn;
  String? get error => _error;

  /// The kind of the last failure, so the UI can style it (or offer a retry)
  /// without string-matching the message.
  LoginFailure? get failure => _failure;

  /// True once a request has been in flight long enough that a Render cold
  /// start is the likely explanation. Drives the "waking up the server" hint
  /// DURING the wait, rather than making the owner sit on a bare spinner and
  /// then guess at a connection error.
  bool get wakingUp => _wakingUp;

  /// Restores session on app start if a token is already stored.
  Future<void> bootstrap() async {
    _loggedIn = await _auth.hasToken();
    notifyListeners();
  }

  Future<bool> login(String username, String password) async {
    _loading = true;
    _error = null;
    _failure = null;
    _wakingUp = false;
    notifyListeners();

    // A free-tier cold start takes 40-80s. Rather than leave the owner staring
    // at a spinner wondering if it is broken, say so while it happens.
    final wakeHint = Timer(const Duration(seconds: 6), () {
      _wakingUp = true;
      notifyListeners();
    });

    try {
      await _auth.login(username.trim(), password);
      _loggedIn = true;
      return true;
    } on ApiException catch (e) {
      // The server ANSWERED. Never describe this as a connection problem.
      _failure = e.statusCode == 401
          ? LoginFailure.badCredentials
          : LoginFailure.serverError;
      _error = switch (e.statusCode) {
        401 => 'Incorrect username or password.',
        403 => 'This account is not permitted to sign in here.',
        429 => 'Too many sign-in attempts. Wait a minute and try again.',
        >= 500 => 'The server hit an error (${e.statusCode}). '
            'It is not your password — try again shortly.',
        _ => 'Sign-in was rejected (${e.statusCode}): ${e.message}',
      };
      return false;
    } on NetworkException catch (e) {
      // The server never answered. Never describe this as a bad password.
      _failure = e.timedOut ? LoginFailure.timeout : LoginFailure.network;
      _error = e.timedOut
          ? 'The server is waking up — this can take up to a minute on the '
              'first try. Tap "Log in" again in a few seconds.'
          : 'Could not reach the server. Check your internet connection, '
              'then try again.';
      return false;
    } catch (e) {
      // Genuinely unexpected. Distinct from all of the above so it cannot hide
      // inside the network bucket the way it used to.
      _failure = LoginFailure.serverError;
      _error = 'Something went wrong signing in. Please try again.';
      if (kDebugMode) debugPrint('login: unexpected error: $e');
      return false;
    } finally {
      wakeHint.cancel();
      _wakingUp = false;
      _loading = false;
      notifyListeners();
    }
  }

  /// Cities selectable at signup, from the canonical list (migration 013).
  Future<List<String>> fetchCities() => _auth.fetchCities();

  /// Account state — drives the "add your email" prompt for legacy accounts.
  Future<AccountInfo> account() => _auth.account();

  Future<AccountInfo> setEmail(String email) => _auth.setEmail(email);

  /// Returns null on success, or a staff-facing error message.
  Future<String?> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    try {
      await _auth.changePassword(
        currentPassword: currentPassword, newPassword: newPassword);
      return null;
    } on ApiException catch (e) {
      if (e.statusCode == 401) return 'Your current password is incorrect.';
      return e.message;
    } catch (_) {
      return 'Could not change the password. Try again.';
    }
  }

  /// Forgot-password. The result is identical whether or not the username
  /// exists, so callers must not branch on "was it found".
  ///
  /// Throws rather than returning null on failure. Swallowing everything into
  /// `null` was the same mistake login made: it turned a dead connection, a
  /// rate-limit and a server crash into one indistinguishable outcome that the
  /// screen could only describe as "could not reach the server".
  Future<ForgotPasswordResult> forgotPassword(String username) =>
      _auth.forgotPassword(username);

  /// Owner self-signup. Returns null on success, or a staff-facing error.
  /// Does not log in — the outlet is pending admin verification.
  Future<String?> register({
    required String restaurantName,
    String? city,
    String? requestedCity,
    required String locality,
    required String phoneNumber,
    required String email,
    required String username,
    required String password,
    required String upiId,
  }) async {
    try {
      await _auth.register(
        restaurantName: restaurantName.trim(),
        city: city,
        requestedCity: requestedCity,
        locality: locality,
        phoneNumber: phoneNumber,
        email: email,
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
