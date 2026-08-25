import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';

import '../config/app_config.dart';
import '../models/customer.dart';
import 'api_client.dart';
import 'otp_auth_service.dart';

/// Real phone-number OTP via Firebase Auth, exchanged for a CareVo session.
///
/// Flow: [requestOtp] starts `verifyPhoneNumber` and completes once Firebase has
/// sent the SMS, handing back the verificationId. [verifyOtp] turns the typed
/// code into a credential, signs in, and posts the resulting ID token to
/// `/customer/auth/firebase`, which verifies it server-side and returns the
/// CareVo bearer token. The 6-digit code is never trusted by our backend.
class FirebaseOtpService implements OtpAuthService {
  FirebaseOtpService(this._api, {FirebaseAuth? auth})
      : _auth = auth ?? FirebaseAuth.instance;

  final ApiClient _api;
  final FirebaseAuth _auth;

  /// Set on `codeSent`; consumed by [verifyOtp] to rebuild the credential.
  String? _verificationId;

  /// Android can auto-retrieve the SMS and hand back a ready credential before
  /// the user types anything. When that happens we prefer it over the typed
  /// code, which may never arrive.
  PhoneAuthCredential? _autoCredential;

  int? _resendToken;

  /// The number [_resendToken] belongs to. A resend token is scoped to one
  /// phone number's verification session, so it must not follow the user to a
  /// different number.
  String? _resendTokenPhone;

  /// Monotonic id for the current verification attempt.
  ///
  /// FlutterFire never cancels the EventChannel subscription it opens per
  /// `verifyPhoneNumber` call, so a superseded attempt keeps delivering
  /// callbacks forever. Its `codeAutoRetrievalTimeout` — 30s after its own
  /// `codeSent`, the plugin's default timeout — would otherwise fire *after*
  /// a resend and overwrite the live verificationId with the dead one, so the
  /// code the user just received gets checked against the wrong session and
  /// comes back "expired". Every callback captures the generation it belongs
  /// to and drops its write once a newer attempt has started.
  int _generation = 0;

  /// `setSettings` mutates the shared FirebaseAuth instance, so it only needs
  /// to land once — but it must land *before* the first verifyPhoneNumber call.
  bool _verifierConfigured = false;

  /// Selects the app verifier for this device. See
  /// [AppConfig.forceRecaptchaFlow] for why the Play Integrity default is not
  /// usable while the app is sideloaded.
  ///
  /// Android-only setting: on every other platform the call is skipped rather
  /// than passed a flag the platform ignores.
  Future<void> _configureAppVerifier() async {
    if (_verifierConfigured) return;
    _verifierConfigured = true;

    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    if (!AppConfig.forceRecaptchaFlow) return;

    try {
      await _auth.setSettings(forceRecaptchaFlow: true);
    } catch (e) {
      // Never block sign-in on this: if the setting fails to apply we still
      // want the normal (Play Integrity) attempt rather than a dead end.
      debugPrint('Could not force reCAPTCHA flow: $e');
      _verifierConfigured = false;
    }
  }

  /// Firebase requires E.164. Bare 10-digit input is assumed Indian (+91),
  /// matching the rest of the app's phone handling.
  static String toE164(String raw) {
    final trimmed = raw.trim();
    if (trimmed.startsWith('+')) {
      return '+${trimmed.substring(1).replaceAll(RegExp(r'\D'), '')}';
    }
    final digits = trimmed.replaceAll(RegExp(r'\D'), '');
    if (digits.length == 10) return '+91$digits';
    if (digits.length > 10 && digits.startsWith('91')) return '+$digits';
    return '+$digits';
  }

  @override
  Future<String> requestOtp(String phoneNumber) async {
    final e164 = toE164(phoneNumber);

    // This attempt supersedes any earlier one; its callbacks stop counting.
    final generation = ++_generation;
    bool isCurrent() => generation == _generation;

    _verificationId = null;
    _autoCredential = null;

    // Resending is only meaningful against the same number's session.
    if (_resendTokenPhone != e164) {
      _resendToken = null;
      _resendTokenPhone = e164;
    }

    await _configureAppVerifier();

    // Completed by whichever callback fires first; guarded because Firebase can
    // invoke more than one (e.g. verificationCompleted then codeSent) and
    // completing twice throws.
    final completer = Completer<String>();
    void succeed(String id) {
      if (!completer.isCompleted) completer.complete(id);
    }

    void fail(Object error) {
      if (!completer.isCompleted) completer.completeError(error);
    }

    await _auth.verifyPhoneNumber(
      phoneNumber: e164,
      forceResendingToken: _resendToken,
      verificationCompleted: (credential) {
        if (!isCurrent()) return;
        _autoCredential = credential;
        // verificationId is null on instant verification; the stored credential
        // is what verifyOtp will use.
        succeed(credential.verificationId ?? '');
      },
      verificationFailed: (e) {
        if (!isCurrent()) return;
        fail(ApiException(_messageFor(e)));
      },
      codeSent: (verificationId, resendToken) {
        if (!isCurrent()) return;
        _verificationId = verificationId;
        _resendToken = resendToken;
        _resendTokenPhone = e164;
        succeed(verificationId);
      },
      codeAutoRetrievalTimeout: (verificationId) {
        if (!isCurrent()) return;
        // Auto-retrieval window closed; the typed code is now the only route.
        _verificationId = verificationId;
        succeed(verificationId);
      },
    );

    return completer.future;
  }

  @override
  Future<AuthResult> verifyOtp(String phoneNumber, String otp) async {
    final credential = _autoCredential ??
        (_verificationId == null
            ? null
            : PhoneAuthProvider.credential(
                verificationId: _verificationId!,
                smsCode: otp,
              ));

    if (credential == null) {
      throw ApiException('No verification in progress. Please request a new code.');
    }

    final UserCredential signIn;
    try {
      signIn = await _auth.signInWithCredential(credential);
    } on FirebaseAuthException catch (e) {
      throw ApiException(_messageFor(e));
    }

    final idToken = await signIn.user?.getIdToken();
    if (idToken == null || idToken.isEmpty) {
      throw ApiException('Could not obtain a Firebase token.');
    }

    // Exchange for the CareVo session token. The backend re-verifies the token
    // against Google's public keys and reads the phone number from its claims.
    final res = await _api.post(
      '/customer/auth/firebase',
      body: {'id_token': idToken},
    );
    final map = (res as Map).cast<String, dynamic>();
    final token = map['access_token']?.toString() ?? '';
    if (token.isEmpty) {
      throw ApiException('Verification failed: no token returned.');
    }
    await _api.setToken(token);

    // Retire this attempt so its still-live callbacks (the auto-retrieval
    // timeout in particular) can't resurrect a verificationId after sign-in.
    _generation++;
    _verificationId = null;
    _autoCredential = null;

    final customerJson = (map['customer'] as Map?)?.cast<String, dynamic>() ?? {};
    return AuthResult(
      accessToken: token,
      customer: Customer.fromJson(customerJson),
      isNewAccount: map['is_new_account'] == true,
    );
  }

  /// Firebase error codes are not user-facing; map the ones a customer can
  /// actually hit and fall back to the SDK message otherwise.
  String _messageFor(FirebaseAuthException e) {
    switch (e.code) {
      case 'invalid-phone-number':
        return 'That phone number doesn\'t look right.';
      case 'invalid-verification-code':
        return 'Invalid code. Please try again.';
      case 'session-expired':
      case 'expired-action-code':
        return 'That code expired. Please request a new one.';
      case 'too-many-requests':
        return 'Too many attempts. Please try again later.';
      case 'quota-exceeded':
        return 'SMS quota exceeded. Please try again later.';
      case 'billing-not-enabled':
        return 'SMS sign-in is not enabled for this project yet.';
      case 'network-request-failed':
        return 'Network error: unable to reach Firebase.';
      // App verification was refused rather than merely unavailable — the
      // reCAPTCHA challenge was dismissed, or this build's signing key is not
      // the one registered in Firebase.
      case 'app-not-authorized':
      case 'web-context-cancelled':
        return 'Could not verify this app. Please try again.';
      default:
        return e.message ?? 'Verification failed (${e.code}).';
    }
  }
}
