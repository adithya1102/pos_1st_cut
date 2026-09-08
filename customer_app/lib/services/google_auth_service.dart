import 'package:firebase_auth/firebase_auth.dart';
import 'package:google_sign_in/google_sign_in.dart';

import '../config/app_config.dart';
import '../models/customer.dart';
import 'api_client.dart';
import 'otp_auth_service.dart';

/// Google sign-in, exchanged for a CareVo session.
///
/// A STANDALONE identity: this never asks for, sends, or infers a phone number.
/// The customer it returns has `phoneNumber == null` (rendered "—") until they
/// verify a phone through the OTP flow, which fills it in on the same row.
///
/// Flow: google_sign_in returns a Google ID token -> traded for a Firebase
/// credential -> Firebase ID token -> POST /customer/auth/google, which
/// re-verifies it against Google's public keys and reads email + uid from the
/// claims. Nothing identifying is taken from the client's word.
class GoogleAuthService {
  GoogleAuthService(this._api, {FirebaseAuth? auth}) : _authOverride = auth;

  final ApiClient _api;

  /// Resolved lazily, NOT in the constructor.
  ///
  /// `FirebaseAuth.instance` throws unless `Firebase.initializeApp()` has
  /// already run. Reading it at construction time made merely *providing* this
  /// service enough to crash — which is fine in `main()`, where Firebase is
  /// initialized first, but broke any widget test that put an [AuthState] in
  /// scope without a Firebase app. Sign-in is the only thing that needs it.
  final FirebaseAuth? _authOverride;
  FirebaseAuth get _auth => _authOverride ?? FirebaseAuth.instance;

  /// `initialize` is required once before any other call in google_sign_in 7.x
  /// and is idempotent on the plugin side; the flag just avoids the round trip.
  bool _initialized = false;

  Future<void> _ensureInitialized() async {
    if (_initialized) return;
    await GoogleSignIn.instance.initialize(
      // Android reads `default_web_client_id` (generated from
      // google-services.json) when this is null, which is the normal path.
      // The override exists for builds that need a different OAuth client.
      serverClientId: AppConfig.googleServerClientId.isEmpty
          ? null
          : AppConfig.googleServerClientId,
    );
    _initialized = true;
  }

  /// Runs the full sign-in. Returns null if the user dismissed the picker —
  /// a cancel is not an error and must not raise a red snackbar.
  Future<AuthResult?> signIn() async {
    await _ensureInitialized();

    final GoogleSignInAccount account;
    try {
      account = await GoogleSignIn.instance.authenticate(
        scopeHint: const ['email'],
      );
    } on GoogleSignInException catch (e) {
      if (e.code == GoogleSignInExceptionCode.canceled) return null;
      throw ApiException(_messageForGoogle(e));
    }

    final idToken = account.authentication.idToken;
    if (idToken == null || idToken.isEmpty) {
      // Almost always a misconfigured serverClientId: without a web OAuth
      // client the plugin returns an account but no ID token.
      throw ApiException('Google sign-in did not return an ID token.');
    }

    final UserCredential signIn;
    try {
      signIn = await _auth.signInWithCredential(
        GoogleAuthProvider.credential(idToken: idToken),
      );
    } on FirebaseAuthException catch (e) {
      throw ApiException(_messageForFirebase(e));
    }

    final firebaseToken = await signIn.user?.getIdToken();
    if (firebaseToken == null || firebaseToken.isEmpty) {
      throw ApiException('Could not obtain a Firebase token.');
    }

    final res = await _api.post(
      '/customer/auth/google',
      body: {'id_token': firebaseToken},
    );
    final map = (res as Map).cast<String, dynamic>();
    final token = map['access_token']?.toString() ?? '';
    if (token.isEmpty) {
      throw ApiException('Sign-in failed: no token returned.');
    }
    await _api.setToken(token);

    final customerJson = (map['customer'] as Map?)?.cast<String, dynamic>() ?? {};
    return AuthResult(
      accessToken: token,
      customer: Customer.fromJson(customerJson),
      isNewAccount: map['is_new_account'] == true,
    );
  }

  /// Clears the cached Google account so the next sign-in shows the picker
  /// again rather than silently reusing the last account.
  Future<void> signOut() async {
    if (!_initialized) return;
    try {
      await GoogleSignIn.instance.signOut();
    } catch (_) {
      // Never block logout on the plugin; the CareVo token is already gone.
    }
  }

  String _messageForGoogle(GoogleSignInException e) {
    switch (e.code) {
      case GoogleSignInExceptionCode.canceled:
      case GoogleSignInExceptionCode.interrupted:
        return 'Sign-in was cancelled.';
      case GoogleSignInExceptionCode.clientConfigurationError:
        return 'Google sign-in is not configured for this build.';
      case GoogleSignInExceptionCode.providerConfigurationError:
        return 'Google Play services is unavailable on this device.';
      default:
        return e.description ?? 'Google sign-in failed.';
    }
  }

  String _messageForFirebase(FirebaseAuthException e) {
    switch (e.code) {
      case 'account-exists-with-different-credential':
        return 'That email is already linked to a different sign-in method.';
      case 'invalid-credential':
        return 'Google sign-in was rejected. Please try again.';
      case 'operation-not-allowed':
        return 'Google sign-in is not enabled for this project yet.';
      case 'user-disabled':
        return 'This account has been disabled.';
      case 'network-request-failed':
        return 'Network error: unable to reach Firebase.';
      default:
        return e.message ?? 'Sign-in failed (${e.code}).';
    }
  }
}
