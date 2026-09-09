import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';

import 'api_client.dart';

/// Endpoint that re-exchanges a Firebase identity for a CareVo session.
///
/// Both are the ordinary sign-in routes. Neither is first-login-only:
/// `verify_firebase_token` looks the customer up and only inserts when none is
/// found, returning `is_new_account: false` for someone who already exists. So
/// re-exchange is the same operation login performs, not a special case.
const _phoneExchange = '/customer/auth/firebase';
const _googleExchange = '/customer/auth/google';

/// Trade the still-live Firebase session for a fresh CareVo token.
///
/// Returns the new token, or NULL to mean "sign this person out" — which the
/// caller treats exactly as an expiry, so every path that used to log out
/// still logs out.
///
/// ## Why this exists
///
/// The CareVo JWT lives 24h (ACCESS_TOKEN_EXPIRE_MINUTES=1440) and there is no
/// refresh token anywhere in the system. Firebase's own session, meanwhile,
/// persists across restarts and mints fresh ID tokens on demand. The app was
/// exchanging that once at sign-in and never again, so a durable identity was
/// being thrown away every 24h and the customer was asked to log in again for
/// no reason other than bookkeeping.
///
/// ## Routing
///
/// `currentUser` alone does not say HOW someone signed in, and the two
/// endpoints verify different token types — handing a Google token to the
/// phone route fails. [User.providerData] is the authority.
///
/// EXACTLY ONE recognised provider is required. Both linked, or neither, is
/// ambiguous: there is no way to choose without guessing, and guessing wrong
/// logs the person out anyway after a failed exchange. Ambiguity therefore
/// returns null and takes the ordinary logout path, which is correct rather
/// than merely safe — nothing is lost that was not already lost.
Future<String?> refreshCareVoSession(ApiClient api) async {
  final user = FirebaseAuth.instance.currentUser;
  if (user == null) {
    // No Firebase session: this is a genuine expiry. Nothing to refresh from.
    return null;
  }

  final providers = user.providerData.map((p) => p.providerId).toSet();
  final hasPhone = providers.contains('phone');
  final hasGoogle = providers.contains('google.com');

  final String endpoint;
  if (hasPhone && !hasGoogle) {
    endpoint = _phoneExchange;
  } else if (hasGoogle && !hasPhone) {
    endpoint = _googleExchange;
  } else {
    if (kDebugMode) {
      debugPrint('session refresh: ambiguous providers $providers — '
          'falling back to logout');
    }
    return null;
  }

  // force: true so a token that expired alongside the CareVo one is actually
  // renewed. Without it Firebase may hand back the same cached ID token, the
  // exchange rejects it, and the refresh fails for a session that was fine.
  final idToken = await user.getIdToken(true);
  if (idToken == null || idToken.isEmpty) return null;

  // postWithoutRefresh, not post: refreshing in order to refresh is a loop.
  final res = await api.postWithoutRefresh(endpoint, body: {'id_token': idToken});
  final token = (res is Map) ? res['access_token'] : null;
  if (token is! String || token.isEmpty) return null;
  return token;
}
