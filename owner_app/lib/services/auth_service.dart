import 'api_client.dart';

/// Wraps the EXISTING staff auth endpoint. No new auth system is introduced.
class AuthService {
  final ApiClient _client;

  AuthService(this._client);

  /// Logs a staff member in via `POST /auth/login`
  /// (OAuth2PasswordRequestForm — form-encoded username/password).
  /// On success the access token is persisted and returned.
  Future<String> login(String username, String password) async {
    final data = await _client.postForm('/auth/login', {
      'username': username,
      'password': password,
    });

    final token = (data is Map) ? data['access_token']?.toString() : null;
    if (token == null || token.isEmpty) {
      throw ApiException(500, 'Login response did not include an access token.');
    }
    await _client.saveToken(token);
    return token;
  }

  /// Public owner self-signup via `POST /register`. Does NOT log the user in
  /// (the new outlet is pending admin verification). Throws [ApiException] on
  /// failure (409 username taken, 429 rate-limited, etc.).
  Future<void> register({
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
    await _client.post('/register', body: {
      'restaurant_name': restaurantName,
      // Exactly one of city / requested_city — the server rejects both-or-
      // neither. `city` must already be an approved city; `requested_city`
      // files a new-city request for admin approval.
      if (city != null && city.trim().isNotEmpty) 'city': city.trim(),
      if (requestedCity != null && requestedCity.trim().isNotEmpty)
        'requested_city': requestedCity.trim(),
      // Area within the city (migration 012). Mandatory server-side as of
      // the locality work — a signup without it is rejected with 422.
      'locality': locality.trim(),
      // Now mandatory server-side, so always sent.
      'phone_number': phoneNumber.trim(),
      // Required as of migration 015 — it is what makes forgot-password work.
      'email': email.trim().toLowerCase(),
      'username': username,
      'password': password,
      'upi_id': upiId.trim(),
    });
  }

  /// Cities selectable at signup. Public endpoint — no token needed, which is
  /// required since this populates the form before an account exists.
  Future<List<String>> fetchCities() async {
    final data = await _client.get('/cities');
    return ((data as List?) ?? const [])
        .whereType<Map>()
        .map((m) => m['name']?.toString() ?? '')
        .where((n) => n.isNotEmpty)
        .toList();
  }

  Future<bool> hasToken() async {
    final token = await _client.readToken();
    return token != null && token.isNotEmpty;
  }

  Future<void> logout() => _client.clearToken();

  /// `POST /auth/password/forgot` — PUBLIC, no token.
  ///
  /// The response is identical whether or not the username exists, so this
  /// never reveals which accounts are real. [maskedEmail] is non-null only
  /// when there is an address on file.
  Future<ForgotPasswordResult> forgotPassword(String username) async {
    final data = await _client.post('/auth/password/forgot', body: {
      'username': username.trim(),
    });
    final m = (data as Map).cast<String, dynamic>();
    return ForgotPasswordResult(
      message: m['message']?.toString() ?? '',
      maskedEmail: m['email_hint']?.toString(),
      needsAdminHelp: m['needs_admin_help'] == true,
    );
  }

  /// `POST /account/change-password` — requires the CURRENT password on top of
  /// the bearer token. Throws [ApiException] with 401 when it is wrong.
  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    await _client.post('/account/change-password', body: {
      'current_password': currentPassword,
      'new_password': newPassword,
    });
  }

  /// `GET /account` — drives the "add your email" prompt for legacy accounts.
  Future<AccountInfo> account() async {
    final data = await _client.get('/account');
    return AccountInfo.fromJson((data as Map).cast<String, dynamic>());
  }

  /// `PUT /account/email` — set/update the recovery email.
  Future<AccountInfo> setEmail(String email) async {
    final data = await _client.put('/account/email', body: {'email': email.trim()});
    final m = (data as Map).cast<String, dynamic>();
    return AccountInfo(
      username: '',
      email: m['email']?.toString(),
      emailHint: m['email_hint']?.toString(),
      emailVerified: false,
      needsEmail: false,
      verificationSent: m['verification_sent'] == true,
    );
  }
}

/// Outcome of a forgot-password request. Deliberately carries no signal about
/// whether the username existed.
class ForgotPasswordResult {
  const ForgotPasswordResult({
    required this.message,
    this.maskedEmail,
    this.needsAdminHelp = false,
  });

  final String message;

  /// e.g. "a*****a@g***l.com" — enough to recognise, not enough to learn.
  final String? maskedEmail;

  /// Legacy account with no email on file: recover via the admin queue.
  final bool needsAdminHelp;
}

class AccountInfo {
  const AccountInfo({
    required this.username,
    this.email,
    this.emailHint,
    this.emailVerified = false,
    this.needsEmail = true,
    this.verificationSent = false,
  });

  final String username;
  final String? email;
  final String? emailHint;
  final bool emailVerified;

  /// True for accounts predating migration 015 — prompts them to add one.
  final bool needsEmail;

  /// False while the server has no mail transport configured.
  final bool verificationSent;

  factory AccountInfo.fromJson(Map<String, dynamic> j) => AccountInfo(
        username: j['username']?.toString() ?? '',
        email: j['email']?.toString(),
        emailHint: j['email_hint']?.toString(),
        emailVerified: j['email_verified'] == true,
        needsEmail: j['needs_email'] == true,
      );
}
